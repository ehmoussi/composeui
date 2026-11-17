from __future__ import annotations

import functools
import math
from typing import TYPE_CHECKING

from textual.color import Color
from textual_fspicker import FileSave, Filters
from textual_fspicker.path_filters import Filter
from textual_plotext import PlotextPlot

from composeui.core import chartimage
from composeui.core.chartcolors import series_color
from composeui.core.signal import Signal
from composeui.core.view import Axis, ChartKind, ChartView

if TYPE_CHECKING:
    from pathlib import Path

    from textual.app import RenderResult

    from composeui.core.view import ReferenceLine, Series


#: the key saving the chart's image
SAVE_IMAGE_KEY = "s"
#: the formats the save dialog offers, the vector ones first, by its filters' names
_IMAGE_FILTERS = {"PDF": "pdf", "SVG": "svg", "PNG": "png"}


#: the columns that a time axis' label takes, with room around it
_TIME_LABEL_WIDTH = 18

#: plotext's name of a y axis' side, by whether it is the second y axis
_SIDES = {False: "left", True: "right"}


def _has_suffix(path: Path, suffix: str) -> bool:
    return path.suffix.lower() == suffix


class ComposeChart(PlotextPlot):
    """A chart drawn with plotext's characters: no zoom or hover in a terminal.

    With the `report` extra, its key `s` asks where to save its image, which
    `image_path_chosen` emits.
    """

    can_focus = True

    DEFAULT_CSS = """
    ComposeChart {
        height: 20;
        min-height: 10;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.chart_title = ""
        self.x = Axis()
        self.y = Axis()
        self.y2 = Axis()
        self.series: list[Series] = []
        self.reference_lines: list[ReferenceLine] = []
        self.categories: list[str] = []
        self.image_name = "chart.pdf"
        self.image_path_chosen: Signal[Path] = Signal()
        self.set_save_image_text("Save Image")

    def set_save_image_text(self, text: str) -> None:
        """Describe the key saving the chart's image, e.g. in the app's footer."""
        self._bindings.key_to_bindings.pop(SAVE_IMAGE_KEY, None)
        self._bindings.bind(SAVE_IMAGE_KEY, "save_image", text)
        self.refresh_bindings()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "save_image":
            return chartimage.is_available()  # matplotlib draws the image
        # Textual asks a widget about its own bindings only
        return super().check_action(action, parameters)  # pragma: no cover

    def action_save_image(self) -> None:
        filters = Filters(
            *(
                Filter(name, functools.partial(_has_suffix, suffix=f".{suffix}"))
                for name, suffix in _IMAGE_FILTERS.items()
            )
        )
        dialog = FileSave(filters=filters, default_file=self.image_name)
        self.app.push_screen(dialog, self._image_path_chosen)

    def _image_path_chosen(self, path: Path | None) -> None:
        if path is None:
            return
        if path.suffix.lstrip(".").lower() not in chartimage.FORMATS:
            path = path.with_name(f"{path.name}.pdf")
        self.image_path_chosen.emit(path)

    def render(self) -> RenderResult:
        # the figure afresh at each render, from the attributes: building a figure with a
        # log scale takes the log of its data in place, so building it twice would take
        # the log of the logs. In the theme's colors too, its series' stepped for it
        self._fill_figure()
        return super().render()

    def _fill_figure(self) -> None:
        """Give plotext the chart's title, labels and series: the bars, then what is over them."""
        plt = self.plt
        plt.clear_figure()
        plt.title(self.chart_title)
        plt.xlabel(self.x.label)
        plt.ylabel(self.y.label)
        has_y2 = ChartView.has_y2(self.series, self.reference_lines)
        if has_y2:
            # plotext labels a side, as its stub doesn't say
            plt.ylabel(self.y2.label, yside="right")  # type: ignore[call-arg]
        is_dark = self.app.current_theme.dark if self.is_mounted else False
        colors = [
            Color.parse(curve.color or series_color(index, is_dark=is_dark)).rgb
            for index, curve in enumerate(self.series)
        ]
        # a log scale only on an axis with values: plotext fails to draw the ticks of one
        # without any, e.g. an empty chart's
        lines = self._drawn_lines()
        xs, _ys = self._extent(on_y2=False)
        xs += [line.value + self._offset for line in lines if line.vertical]
        x_log = self._x_log and len(xs) > 0
        if x_log:
            plt.xscale("log")
        # an x axis of categories has no bounds: `_plot_bars` gives it their own range after
        x_limits = self._limits(self.x, xs, is_log=x_log)
        if x_limits is not None:
            plt.xlim(*x_limits)
        if ChartView.is_x_time(self.x, self.categories) and len(xs) > 0:
            # plotext takes dates as text: the ticks at round times, as many as fit
            shown = self._shown(self.x, xs)
            ticks, labels = ChartView.time_ticks(
                min(shown), max(shown), self.size.width // _TIME_LABEL_WIDTH
            )
            plt.xticks(ticks, labels)
        for on_y2 in (False, True):
            axis, ys = self._y_axis(on_y2=on_y2), self._y_values(lines, on_y2=on_y2)
            y_log = axis.is_log and len(ys) > 0
            if y_log:
                plt.yscale("log", yside=_SIDES[on_y2])
            y_limits = self._limits(axis, ys, is_log=y_log)
            if y_limits is not None:
                # plotext bounds a side, which its stub types as a number
                plt.ylim(*y_limits, yside=_SIDES[on_y2])  # type: ignore[arg-type]
        self._plot_bars(colors)
        self._plot_curves(colors)
        self._plot_reference_lines()

    @property
    def _x_log(self) -> bool:
        return ChartView.is_x_log(self.x, self.categories, self.series)

    def _y_axis(self, *, on_y2: bool) -> Axis:
        return self.y2 if on_y2 else self.y

    @property
    def _offset(self) -> int:
        """Get where plotext draws the first category: it counts them from 1."""
        return 1 if len(self.categories) > 0 else 0

    def _drawn_lines(self) -> list[ReferenceLine]:
        return ChartView.drawn_lines(
            self.reference_lines,
            x_log=self._x_log,
            y_log=self.y.is_log,
            y2_log=self.y2.is_log,
        )

    def _y_values(self, lines: list[ReferenceLine], *, on_y2: bool) -> list[float]:
        """Get the values plotext gets on a y axis: its series' and the lines across it."""
        _xs, ys = self._extent(on_y2=on_y2)
        return ys + [line.value for line in lines if not line.vertical and line.is_on_y2 == on_y2]

    @staticmethod
    def _shown(axis: Axis, values: list[float]) -> list[float]:
        """Get the ends of the range an axis with bounds shows; `values` without bounds."""
        if not axis.has_bounds or len(values) == 0:
            return values
        return list(axis.bounded(min(values), max(values)))

    @staticmethod
    def _limits(axis: Axis, values: list[float], *, is_log: bool) -> tuple[float, float] | None:
        """Get the limits of an axis with bounds, as plotext takes them: a log axis' logs.

        None without bounds, which leaves plotext fitting the values, or without values.
        """
        if not axis.has_bounds or len(values) == 0:
            return None
        low, high = axis.bounded(min(values), max(values))
        return (math.log10(low), math.log10(high)) if is_log else (low, high)

    def _points(self, curve: Series) -> tuple[list[float], list[float]]:
        """Get the points of a line or of dots as plotext draws them, in its values.

        No points when none has both an x and a y to draw: plotext fails to draw a series of
        gaps alone, and to name one without points in its legend.
        """
        y_log = self._y_axis(on_y2=curve.on_y2).is_log
        x, y = ChartView.drawn_points(curve, x_log=self._x_log, y_log=y_log)
        if not any(math.isfinite(a) and math.isfinite(b) for a, b in zip(x, y)):
            return [], []
        if curve.step and curve.kind is ChartKind.LINE:
            x, y = ChartView.step_points(x, y)
        return [value + self._offset for value in x], y

    def _plot_curves(self, colors: list[tuple[int, int, int]]) -> None:
        plt = self.plt
        for index, curve in enumerate(self.series):
            if curve.kind is ChartKind.BAR:
                continue
            draw = plt.scatter if curve.kind is ChartKind.SCATTER else plt.plot
            x, y = self._points(curve)
            if len(x) == 0:
                continue  # not drawn, nor named (see `_points`)
            side = _SIDES[curve.on_y2]
            # plotext fills in the color of the line: an area of its own, under the line
            if curve.fill and curve.fill_color is not None:
                draw(
                    x,
                    y,
                    color=Color.parse(curve.fill_color).rgb,
                    marker="braille",
                    fillx=True,
                    yside=side,
                )
            # plotext leaves a gap at a NaN itself
            draw(
                x,
                y,
                label=curve.name,
                color=colors[index],
                marker="braille",
                # down to y = 0, e.g. a shape
                fillx=curve.fill and curve.fill_color is None,
                yside=side,
            )

    def _bars(self, curve: Series) -> tuple[list[float], list[float]]:
        """Get the bars of `curve` that are drawn, as its own y axis shows them."""
        y_log = self._y_axis(on_y2=curve.on_y2).is_log
        return ChartView.bars_of(curve, self.categories, y_log=y_log)

    def _extent(self, *, on_y2: bool) -> tuple[list[float], list[float]]:
        """Get the x the series reach, and the y of those of a y axis, in plotext's values."""
        count = len(self.categories)
        xs: list[float] = [0.5, count + 0.5] if count > 0 else []
        ys: list[float] = []
        for curve in self.series:
            if curve.kind is ChartKind.BAR:
                x, y = self._bars(curve)
                x = [value + self._offset for value in x]
            else:
                x, y = self._points(curve)
            xs.extend(value for value in x if math.isfinite(value))
            if curve.on_y2 == on_y2:
                ys.extend(value for value in y if math.isfinite(value))
        return xs, ys

    def _plot_reference_lines(self) -> None:
        """Draw the reference lines, each labeled at its end, solid: a terminal has no dashes."""
        lines = self._drawn_lines()
        if len(lines) == 0:
            return
        offset = self._offset
        # the theme's text, the axes' own
        ink = Color.parse(self.app.theme_variables["foreground"]).rgb if self.is_mounted else None
        for line in lines:
            # among the lines of its own y axis: the label of one stands at the end of the range
            xs, ys = self._extent(on_y2=line.is_on_y2)
            xs += [other.value + offset for other in lines if other.vertical]
            ys += [
                other.value
                for other in lines
                if not other.vertical and other.is_on_y2 == line.is_on_y2
            ]
            # the range shown, at the axes' bounds: a label past them isn't drawn
            if len(self.categories) == 0:
                xs = self._shown(self.x, xs)
            ys = self._shown(self._y_axis(on_y2=line.is_on_y2), ys)
            color = Color.parse(line.color).rgb if line.color is not None else ink
            if line.vertical:
                x = line.value + offset
                self.plt.vline(x, color)
                if line.label != "" and len(ys) > 0:
                    # at its top, left of it (now, after the data)
                    self.plt.text(line.label, x, max(ys), color, alignment="right")
            else:
                side = _SIDES[line.is_on_y2]
                if not line.is_on_y2:
                    self.plt.hline(line.value, color)
                else:
                    # plotext draws its own horizontal line at the left axis' y only: a
                    # line across what the chart shows, at the right axis' y; without any
                    # x, across plotext's own range
                    self.plt.plot(
                        [min(xs), max(xs)] if len(xs) > 0 else [0, 1],
                        [line.value] * 2,
                        color=color,
                        marker="braille",
                        yside=side,
                    )
                if line.label != "" and len(xs) > 0:
                    # over it, at its right end
                    self.plt.text(
                        line.label, max(xs), line.value, color, alignment="right", yside=side
                    )

    def _plot_bars(self, colors: list[tuple[int, int, int]]) -> None:
        """Draw the bar series, each in its slot of the group of bars at an x."""
        count = len(self.categories)
        bars = {
            index: self._bars(curve)
            for index, curve in enumerate(self.series)
            if curve.kind is ChartKind.BAR
        }
        xs = sorted({x for bar_xs, _heights in bars.values() for x in bar_xs})
        if count > 0:
            xs = [float(category) for category in range(count)]
            # plotext counts the categories from 1
            self.plt.xticks([category + 1 for category in xs], self.categories)
            self.plt.xlim(0.5, count + 0.5)
        if len(xs) == 0:
            return
        # plotext takes a bar's width as a share of the average room between the x
        spread = (xs[-1] - xs[0]) / (len(xs) - 1) if len(xs) > 1 else 1.0
        slots = ChartView.bar_slots(self.series, self.categories)
        for index, (bar_xs, bar_heights) in bars.items():
            curve = self.series[index]
            base = 0.0
            if self._y_axis(on_y2=curve.on_y2).is_log:
                # from the power of 10 under the lowest bar of its y axis: a log axis has no 0
                drawn = [
                    height
                    for other, (_xs, heights) in bars.items()
                    if self.series[other].on_y2 == curve.on_y2
                    for height in heights
                ]
                base = 10.0 ** math.floor(math.log10(min(drawn))) if len(drawn) > 0 else 1.0
            offset, width = slots[index]
            heights = dict(zip(bar_xs, bar_heights))
            self.plt.bar(
                [x + self._offset + offset for x in xs],
                # plotext draws numbers only: no bar is a bar from the base to itself
                [heights.get(x, base) for x in xs],
                label=curve.name,
                color=colors[index],
                minimum=base,
                width=width / spread,
                yside=_SIDES[curve.on_y2],
                reset_ticks=False,  # the categories', or plotext's own of a numeric axis
            )

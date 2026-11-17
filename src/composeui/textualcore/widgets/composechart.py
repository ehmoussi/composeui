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
from composeui.core.view import BAR_GROUP_WIDTH, Axis, ChartKind, ChartView

if TYPE_CHECKING:
    from pathlib import Path

    from textual.app import RenderResult

    from composeui.core.view import ReferenceLine, Series


#: the key saving the chart's image
SAVE_IMAGE_KEY = "s"
#: the formats the save dialog offers, the vector ones first, by its filters' names
_IMAGE_FILTERS = {"PDF": "pdf", "SVG": "svg", "PNG": "png"}


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
        is_dark = self.app.current_theme.dark if self.is_mounted else False
        colors = [
            Color.parse(curve.color or series_color(index, is_dark=is_dark)).rgb
            for index, curve in enumerate(self.series)
        ]
        if self._x_log:
            plt.xscale("log")
        if self.y.is_log:
            plt.yscale("log")
        self._plot_bars(colors)
        self._plot_curves(colors)
        self._plot_reference_lines()

    @property
    def _x_log(self) -> bool:
        return ChartView.is_x_log(self.x, self.categories, self.series)

    @property
    def _offset(self) -> int:
        """Get where plotext draws the first category: it counts them from 1."""
        return 1 if len(self.categories) > 0 else 0

    def _plot_curves(self, colors: list[tuple[int, int, int]]) -> None:
        plt = self.plt
        for index, curve in enumerate(self.series):
            if curve.kind is ChartKind.BAR:
                continue
            is_dots = curve.kind is ChartKind.SCATTER
            draw = plt.scatter if is_dots else plt.plot
            x, y = ChartView.drawn_points(curve, x_log=self._x_log, y_log=self.y.is_log)
            if curve.step and not is_dots:
                x, y = ChartView.step_points(x, y)
            x = [value + self._offset for value in x]
            # plotext fills in the color of the line: an area of its own, under the line
            if curve.fill and curve.fill_color is not None:
                draw(x, y, color=Color.parse(curve.fill_color).rgb, marker="braille", fillx=True)
            # plotext leaves a gap at a NaN itself
            draw(
                x,
                y,
                label=curve.name,
                color=colors[index],
                marker="braille",
                # down to y = 0, e.g. a shape
                fillx=curve.fill and curve.fill_color is None,
            )

    def _extent(self) -> tuple[list[float], list[float]]:
        """Get the x and y the series reach, in plotext's values."""
        count = len(self.categories)
        xs: list[float] = [0.5, count + 0.5] if count > 0 else []
        ys: list[float] = []
        for curve in self.series:
            if curve.kind is ChartKind.BAR:
                x, y = ChartView.bars_of(curve, self.categories, y_log=self.y.is_log)
            else:
                x, y = ChartView.drawn_points(curve, x_log=self._x_log, y_log=self.y.is_log)
            xs.extend(value + self._offset for value in x if math.isfinite(value))
            ys.extend(value for value in y if math.isfinite(value))
        return xs, ys

    def _plot_reference_lines(self) -> None:
        """Draw the reference lines, each labeled at its end, solid: a terminal has no dashes."""
        lines = ChartView.drawn_lines(self.reference_lines, x_log=self._x_log, y_log=self.y.is_log)
        if len(lines) == 0:
            return
        offset = self._offset
        xs, ys = self._extent()
        xs += [line.value + offset for line in lines if line.vertical]
        ys += [line.value for line in lines if not line.vertical]
        # the theme's text, the axes' own
        ink = Color.parse(self.app.theme_variables["foreground"]).rgb if self.is_mounted else None
        for line in lines:
            color = Color.parse(line.color).rgb if line.color is not None else ink
            if line.vertical:
                x = line.value + offset
                self.plt.vline(x, color)
                if line.label != "" and len(ys) > 0:
                    # at its top, left of it (now, after the data)
                    self.plt.text(line.label, x, max(ys), color, alignment="right")
            else:
                self.plt.hline(line.value, color)
                if line.label != "" and len(xs) > 0:
                    # over it, at its right end
                    self.plt.text(line.label, max(xs), line.value, color, alignment="right")

    def _plot_bars(self, colors: list[tuple[int, int, int]]) -> None:
        """Draw the bar series, a group of their bars at each x."""
        count = len(self.categories)
        bars = [
            (index, ChartView.bars_of(curve, self.categories, y_log=self.y.is_log))
            for index, curve in enumerate(self.series)
            if curve.kind is ChartKind.BAR
        ]
        xs = sorted({x for _index, (bar_xs, _heights) in bars for x in bar_xs})
        if count > 0:
            xs = [float(category) for category in range(count)]
            if len(bars) == 0:
                # no bars to name them: the categories under the lines and dots
                self.plt.xticks([category + 1 for category in xs], self.categories)
                self.plt.xlim(0.5, count + 0.5)
        if len(bars) == 0 or len(xs) == 0:
            return
        drawn = [height for _index, (_xs, heights) in bars for height in heights]
        base = 0.0
        if self.y.is_log:
            # from the power of 10 under the lowest bar: a log axis has no 0
            base = 10.0 ** math.floor(math.log10(min(drawn))) if len(drawn) > 0 else 1.0
        # plotext draws numbers only: no bar is a bar from the base to itself
        heights = [
            [dict(zip(bar_xs, bar_heights)).get(x, base) for x in xs]
            for _index, (bar_xs, bar_heights) in bars
        ]
        # plotext takes a group's width as a share of the average room between the x
        spread = (xs[-1] - xs[0]) / (len(xs) - 1) if len(xs) > 1 else 1.0
        step = ChartView.bar_step(self.series, self.categories)
        # plotext takes a label and a color per series, as its stub doesn't say
        self.plt.multiple_bar(  # type: ignore[call-arg]
            self.categories if count > 0 else xs,
            heights,
            labels=[self.series[index].name for index, _bars in bars],
            color=[colors[index] for index, _bars in bars],  # type: ignore[arg-type]
            minimum=base,
            width=BAR_GROUP_WIDTH * step / spread,
        )

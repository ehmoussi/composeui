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
from composeui.core.view import ChartKind, ChartView

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
        self.x_label = ""
        self.y_label = ""
        self.series: list[Series] = []
        self.reference_lines: list[ReferenceLine] = []
        self.kind = ChartKind.LINE
        self.categories: list[str] = []
        self.x_log = False
        self.y_log = False
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
        return super().check_action(action, parameters)

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
        """Give plotext the chart's title, labels and series."""
        plt = self.plt
        plt.clear_figure()
        plt.title(self.chart_title)
        plt.xlabel(self.x_label)
        plt.ylabel(self.y_label)
        is_dark = self.app.current_theme.dark if self.is_mounted else False
        colors = [
            Color.parse(curve.color or series_color(index, is_dark=is_dark)).rgb
            for index, curve in enumerate(self.series)
        ]
        if self.kind is ChartKind.BAR:
            self._plot_bars(colors)
        else:
            self._plot_curves(colors)
        self._plot_reference_lines()

    def _plot_curves(self, colors: list[tuple[int, int, int]]) -> None:
        plt = self.plt
        if self.x_log:
            plt.xscale("log")
        if self.y_log:
            plt.yscale("log")
        for index, curve in enumerate(self.series):
            draw = (
                plt.scatter
                if ChartView.kind_of(curve, self.kind) is ChartKind.SCATTER
                else plt.plot
            )
            x, y = ChartView.drawn_points(curve, x_log=self.x_log, y_log=self.y_log)
            # plotext leaves a gap at a NaN itself
            draw(
                x,
                y,
                label=curve.name,
                color=colors[index],
                marker="braille",
                # down to y = 0, e.g. a shape
                fillx=curve.fill,
            )

    def _extent(self) -> tuple[list[float], list[float]]:
        """Get the x and y the series reach, in plotext's values: a bar chart's x from 1."""
        if self.kind is ChartKind.BAR:
            heights = [
                height
                for curve in self.series
                for height in ChartView.bar_heights(curve, len(self.categories), y_log=self.y_log)
                if math.isfinite(height)
            ]
            return [0.5, len(self.categories) + 0.5], heights
        xs: list[float] = []
        ys: list[float] = []
        for curve in self.series:
            x, y = ChartView.drawn_points(curve, x_log=self.x_log, y_log=self.y_log)
            xs.extend(value for value in x if math.isfinite(value))
            ys.extend(value for value in y if math.isfinite(value))
        return xs, ys

    def _plot_reference_lines(self) -> None:
        """Draw the reference lines, each labeled at its end: a terminal draws no dashes."""
        is_bar = self.kind is ChartKind.BAR
        lines = ChartView.drawn_lines(
            self.reference_lines, x_log=self.x_log and not is_bar, y_log=self.y_log
        )
        if len(lines) == 0:
            return
        # plotext draws a bar chart's categories from 1
        offset = 1 if is_bar else 0
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
        if len(self.series) == 0 or len(self.categories) == 0:
            return
        heights = [
            ChartView.bar_heights(curve, len(self.categories), y_log=self.y_log)
            for curve in self.series
        ]
        drawn = [height for bars in heights for height in bars if math.isfinite(height)]
        base = 0.0
        if self.y_log:
            self.plt.yscale("log")
            # from the power of 10 under the lowest bar: a log axis has no 0
            base = 10.0 ** math.floor(math.log10(min(drawn))) if len(drawn) > 0 else 1.0
        # plotext draws numbers only: no bar is a bar from the base to itself
        heights = [[h if math.isfinite(h) else base for h in bars] for bars in heights]
        # plotext takes a label and a color per series, as its stub doesn't say
        self.plt.multiple_bar(  # type: ignore[call-arg]
            self.categories,
            heights,
            labels=[curve.name for curve in self.series],
            color=colors,  # type: ignore[arg-type]
            minimum=base,
        )

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from textual.color import Color
from textual_plotext import PlotextPlot

from composeui.core.chartcolors import series_color
from composeui.core.view import ChartKind, ChartView

if TYPE_CHECKING:
    from textual.app import RenderResult

    from composeui.core.view import Series


class ComposeChart(PlotextPlot):
    """A chart drawn with plotext's characters: no zoom or hover in a terminal."""

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
        self.kind = ChartKind.LINE
        self.categories: list[str] = []
        self.x_log = False
        self.y_log = False

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
            Color.parse(series_color(index, is_dark=is_dark)).rgb
            for index in range(len(self.series))
        ]
        if self.kind is ChartKind.BAR:
            self._plot_bars(colors)
            return
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
            )

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

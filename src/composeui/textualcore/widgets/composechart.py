from __future__ import annotations

import math
from typing import TYPE_CHECKING

from textual.color import Color
from textual_plotext import PlotextPlot

from composeui.core.chartcolors import series_color
from composeui.core.view import ChartKind, ChartView

if TYPE_CHECKING:
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

    def on_mount(self) -> None:
        super().on_mount()
        # the series' colors are stepped for a light or a dark theme
        self.app.theme_changed_signal.subscribe(self, lambda _theme: self.replot())
        self.replot()

    def replot(self) -> None:
        """Draw the chart again from its attributes."""
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
            if len(self.series) > 0 and len(self.categories) > 0:
                heights = [
                    # plotext draws numbers only: no bar is a bar of nothing
                    [
                        height if math.isfinite(height) else 0
                        for height in ChartView.bar_heights(curve, len(self.categories))
                    ]
                    for curve in self.series
                ]
                # plotext takes a label and a color per series, as its stub doesn't say
                plt.multiple_bar(  # type: ignore[call-arg]
                    self.categories,
                    heights,
                    labels=[curve.name for curve in self.series],
                    color=colors,  # type: ignore[arg-type]
                )
            self.refresh()
            return
        for index, curve in enumerate(self.series):
            draw = (
                plt.scatter
                if ChartView.kind_of(curve, self.kind) is ChartKind.SCATTER
                else plt.plot
            )
            # plotext leaves a gap at a NaN itself
            draw(
                curve.x,
                curve.y,
                label=curve.name,
                color=colors[index],
                marker="braille",
            )
        self.refresh()

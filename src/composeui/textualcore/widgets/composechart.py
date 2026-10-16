from __future__ import annotations

from typing import TYPE_CHECKING

from textual.color import Color
from textual_plotext import PlotextPlot

from composeui.core.chartcolors import series_color

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
        for index, curve in enumerate(self.series):
            # plotext leaves a gap at a NaN itself
            plt.plot(
                curve.x,
                curve.y,
                label=curve.name,
                color=Color.parse(series_color(index, is_dark=is_dark)).rgb,
                marker="braille",
            )
        self.refresh()

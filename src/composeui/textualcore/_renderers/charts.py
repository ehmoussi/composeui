"""Textual charts."""

from __future__ import annotations

from typing import TYPE_CHECKING

from typing_extensions import Protocol, override

from composeui.core import chartimage
from composeui.core.renderer import ViewLike
from composeui.core.view import ChartView
from composeui.textualcore.textualrenderer import TextualWidgetRenderer
from composeui.textualcore.widgets.composechart import ComposeChart

if TYPE_CHECKING:
    from pathlib import Path

    from composeui.core.view import Axis, BarMode, ReferenceLine, Series


class ChartViewLike(ViewLike, Protocol):
    title: str
    x: Axis
    y: Axis
    y2: Axis
    series: list[Series]
    reference_lines: list[ReferenceLine]
    categories: list[str]
    bar_mode: BarMode
    horizontal: bool
    save_image_text: str
    height: int | None


#: the pixels of a terminal's row, about: a chart's height is in pixels
PIXELS_PER_ROW = 16


#: the rows a chart takes at least, to show its axes and a curve between them
MIN_CHART_ROWS = 5


class TextualChartRenderer(TextualWidgetRenderer[ChartViewLike, ComposeChart]):
    def __init__(self, view: ChartViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "title": self._refresh_title,
                "x": self._refresh_x,
                "y": self._refresh_y,
                "y2": self._refresh_y2,
                "series": self._refresh_series,
                "reference_lines": self._refresh_reference_lines,
                "categories": self._refresh_categories,
                "bar_mode": self._refresh_bar_mode,
                "horizontal": self._refresh_horizontal,
                "save_image_text": self._refresh_save_image_text,
                "height": self._refresh_height,
            }
        )

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = ComposeChart()
            self._rendered_object.image_path_chosen.connect(self._save_image)

    @staticmethod
    def _refresh_title(_view: ChartViewLike, rendered_object: ComposeChart, value: str) -> None:
        rendered_object.chart_title = value
        rendered_object.image_name = chartimage.image_name(value, "pdf")
        rendered_object.refresh()

    @staticmethod
    def _refresh_x(_view: ChartViewLike, rendered_object: ComposeChart, value: Axis) -> None:
        rendered_object.x = value
        rendered_object.refresh()

    @staticmethod
    def _refresh_y(_view: ChartViewLike, rendered_object: ComposeChart, value: Axis) -> None:
        rendered_object.y = value
        rendered_object.refresh()

    @staticmethod
    def _refresh_y2(_view: ChartViewLike, rendered_object: ComposeChart, value: Axis) -> None:
        rendered_object.y2 = value
        rendered_object.refresh()

    @staticmethod
    def _refresh_series(
        _view: ChartViewLike, rendered_object: ComposeChart, value: list[Series]
    ) -> None:
        rendered_object.series = value
        rendered_object.refresh()

    @staticmethod
    def _refresh_reference_lines(
        _view: ChartViewLike, rendered_object: ComposeChart, value: list[ReferenceLine]
    ) -> None:
        rendered_object.reference_lines = value
        rendered_object.refresh()

    @staticmethod
    def _refresh_categories(
        _view: ChartViewLike, rendered_object: ComposeChart, value: list[str]
    ) -> None:
        rendered_object.categories = value
        rendered_object.refresh()

    @staticmethod
    def _refresh_bar_mode(
        _view: ChartViewLike, rendered_object: ComposeChart, value: BarMode
    ) -> None:
        rendered_object.bar_mode = value
        rendered_object.refresh()

    @staticmethod
    def _refresh_horizontal(
        _view: ChartViewLike, rendered_object: ComposeChart, value: bool
    ) -> None:
        rendered_object.horizontal = value
        rendered_object.refresh()

    @staticmethod
    def _refresh_save_image_text(
        _view: ChartViewLike, rendered_object: ComposeChart, value: str
    ) -> None:
        rendered_object.set_save_image_text(value)

    @staticmethod
    def _refresh_height(
        _view: ChartViewLike, rendered_object: ComposeChart, value: int | None
    ) -> None:
        # None: the widget's own CSS height; its minimum too, under a smaller height
        rows = None if value is None else max(MIN_CHART_ROWS, round(value / PIXELS_PER_ROW))
        rendered_object.styles.height = rows
        rendered_object.styles.min_height = rows

    def _save_image(self, path: Path) -> None:
        """Save the whole chart's image: a terminal has no zoom."""
        assert isinstance(self._view, ChartView)
        chartimage.save_chart_image(self._view, path)

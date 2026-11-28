"""The Qt chart renderer and its image-export helpers."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from qtpy.QtWidgets import QFileDialog
from typing_extensions import Protocol, override

from composeui.core import chartimage
from composeui.core.renderer import ViewLike
from composeui.core.view import ChartView
from composeui.qtcore.qtrenderer import _QWIDGETSIZE_MAX, QtWidgetRenderer
from composeui.qtcore.widgets.qchart import QChart

if TYPE_CHECKING:
    from composeui.core.signal import Signal
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
    clicked: Signal[float, float]
    height: int | None


#: the formats the Save Image dialog offers, the vector ones first, by its filters
_IMAGE_FILTERS = {"PDF (*.pdf)": "pdf", "SVG (*.svg)": "svg", "PNG (*.png)": "png"}


class QtChartRenderer(QtWidgetRenderer[ChartViewLike, QChart]):
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
            self._rendered_object = QChart()
            self._connect(self._rendered_object.save_image_requested, self._save_image)
            self._rendered_object.point_clicked.connect(self._view.clicked.emit)
            self.refresh()

    @staticmethod
    def _refresh_title(_view: ChartViewLike, rendered_object: QChart, value: str) -> None:
        rendered_object.set_title(value)

    @staticmethod
    def _refresh_x(_view: ChartViewLike, rendered_object: QChart, value: Axis) -> None:
        rendered_object.set_axis("bottom", value)

    @staticmethod
    def _refresh_y(_view: ChartViewLike, rendered_object: QChart, value: Axis) -> None:
        rendered_object.set_axis("left", value)

    @staticmethod
    def _refresh_y2(_view: ChartViewLike, rendered_object: QChart, value: Axis) -> None:
        rendered_object.set_axis("right", value)

    @staticmethod
    def _refresh_series(_view: ChartViewLike, rendered_object: QChart, value: list[Series]) -> None:
        rendered_object.set_series(value)

    @staticmethod
    def _refresh_reference_lines(
        _view: ChartViewLike, rendered_object: QChart, value: list[ReferenceLine]
    ) -> None:
        rendered_object.set_reference_lines(value)

    @staticmethod
    def _refresh_categories(
        _view: ChartViewLike, rendered_object: QChart, value: list[str]
    ) -> None:
        rendered_object.set_categories(value)

    @staticmethod
    def _refresh_bar_mode(_view: ChartViewLike, rendered_object: QChart, value: BarMode) -> None:
        rendered_object.set_bar_mode(value)

    @staticmethod
    def _refresh_horizontal(_view: ChartViewLike, rendered_object: QChart, value: bool) -> None:
        rendered_object.set_horizontal(horizontal=value)

    @staticmethod
    def _refresh_save_image_text(_view: ChartViewLike, rendered_object: QChart, value: str) -> None:
        rendered_object.save_image_action.setText(f"{value}…")

    @staticmethod
    def _refresh_height(_view: ChartViewLike, rendered_object: QChart, value: int | None) -> None:
        # None: as tall as the layout makes it
        rendered_object.setMinimumHeight(0 if value is None else value)
        rendered_object.setMaximumHeight(_QWIDGETSIZE_MAX if value is None else value)
        # the layout lays it out again, back at its share of the column too
        rendered_object.updateGeometry()

    def _save_image(self) -> None:
        """Ask where to save the chart's image, and save it as it shows, zoomed in too."""
        chart, view = self._rendered_object, self._view
        assert chart is not None
        assert isinstance(view, ChartView)
        path, chosen = QFileDialog.getSaveFileName(
            chart,
            view.save_image_text,
            chartimage.image_name(view.title, "pdf"),
            ";;".join(_IMAGE_FILTERS),
        )
        if path == "":
            return
        filepath = Path(path)
        if filepath.suffix.lstrip(".").lower() not in chartimage.FORMATS:
            filepath = filepath.with_name(f"{filepath.name}.{_IMAGE_FILTERS.get(chosen, 'pdf')}")
        x_range, y_range = chart.shown_range()
        options = chartimage.ImageOptions(
            x_range=x_range, y_range=y_range, y2_range=chart.shown_y2_range()
        )
        chartimage.save_chart_image(view, filepath, options)

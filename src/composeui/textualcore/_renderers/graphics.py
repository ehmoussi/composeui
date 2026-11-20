"""Textual drawings."""

from __future__ import annotations

from typing import TYPE_CHECKING

from typing_extensions import Protocol, override

from composeui.core.renderer import ViewLike
from composeui.textualcore._renderers.charts import MIN_CHART_ROWS, PIXELS_PER_ROW
from composeui.textualcore.textualrenderer import TextualWidgetRenderer
from composeui.textualcore.widgets.composedrawing import ComposeDrawing

if TYPE_CHECKING:
    from composeui.core.view import Shape


class DrawingViewLike(ViewLike, Protocol):
    shapes: list[Shape]
    bounds: tuple[float, float, float, float] | None
    description: str
    height: int | None


class TextualDrawingRenderer(TextualWidgetRenderer[DrawingViewLike, ComposeDrawing]):
    def __init__(self, view: DrawingViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "shapes": self._refresh_shapes,
                "bounds": self._refresh_bounds,
                "description": self._refresh_description,
                "height": self._refresh_height,
            }
        )

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = ComposeDrawing()

    @staticmethod
    def _refresh_shapes(
        _view: DrawingViewLike, rendered_object: ComposeDrawing, value: list[Shape]
    ) -> None:
        rendered_object.shapes = value
        rendered_object.set_drawing()

    @staticmethod
    def _refresh_bounds(
        _view: DrawingViewLike,
        rendered_object: ComposeDrawing,
        value: tuple[float, float, float, float] | None,
    ) -> None:
        rendered_object.bounds = value
        rendered_object.set_drawing()

    @staticmethod
    def _refresh_description(
        _view: DrawingViewLike, rendered_object: ComposeDrawing, value: str
    ) -> None:
        rendered_object.description = value
        rendered_object.set_drawing()

    @staticmethod
    def _refresh_height(
        _view: DrawingViewLike, rendered_object: ComposeDrawing, value: int | None
    ) -> None:
        rows = None if value is None else max(MIN_CHART_ROWS, round(value / PIXELS_PER_ROW))
        rendered_object.styles.height = rows
        rendered_object.styles.min_height = rows

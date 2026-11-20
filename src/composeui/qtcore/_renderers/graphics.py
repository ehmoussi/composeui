"""The Qt drawing renderer and the lazy map renderer factory."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

from typing_extensions import Protocol, override

from composeui.core.renderer import Renderer, ViewLike
from composeui.qtcore.qtrenderer import _QWIDGETSIZE_MAX, QtWidgetRenderer
from composeui.qtcore.widgets.qdrawing import QDrawing

if TYPE_CHECKING:
    from composeui.core.view import Shape


def _map_renderer(view: Any) -> Renderer[Any, Any]:
    # Qt Quick and its native libraries are needed only by applications that use maps.
    renderer: Renderer[Any, Any] = import_module("composeui.qtcore.maprenderer").QtMapRenderer(view)
    return renderer


class DrawingViewLike(ViewLike, Protocol):
    shapes: list[Shape]
    bounds: tuple[float, float, float, float] | None
    description: str
    height: int | None


class QtDrawingRenderer(QtWidgetRenderer[DrawingViewLike, QDrawing]):
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
            self._rendered_object = QDrawing()
            self.refresh()

    @staticmethod
    def _refresh_shapes(
        _view: DrawingViewLike, rendered_object: QDrawing, value: list[Shape]
    ) -> None:
        rendered_object.shapes = value
        rendered_object.set_drawing()

    @staticmethod
    def _refresh_bounds(
        _view: DrawingViewLike,
        rendered_object: QDrawing,
        value: tuple[float, float, float, float] | None,
    ) -> None:
        rendered_object.bounds = value
        rendered_object.set_drawing()

    @staticmethod
    def _refresh_description(_view: DrawingViewLike, rendered_object: QDrawing, value: str) -> None:
        rendered_object.description = value
        rendered_object.set_drawing()

    @staticmethod
    def _refresh_height(
        _view: DrawingViewLike, rendered_object: QDrawing, value: int | None
    ) -> None:
        rendered_object.setMinimumHeight(0 if value is None else value)
        rendered_object.setMaximumHeight(_QWIDGETSIZE_MAX if value is None else value)
        rendered_object.updateGeometry()

"""The map renderer, loaded only when an application uses a map."""

from __future__ import annotations

from typing import TYPE_CHECKING

from typing_extensions import Protocol

from composeui.core.renderer import ViewLike
from composeui.core.view import MapPoint
from composeui.qtcore.qtrenderer import QtWidgetRenderer
from composeui.qtcore.widgets.qmap import QMap

if TYPE_CHECKING:
    from composeui.core.signal import Signal, SignalNoArgs


class MapViewLike(ViewLike, Protocol):
    title: str
    center: MapPoint
    zoom: float
    points: list[MapPoint]
    height: int
    tiles: bool
    user_agent: str
    clicked: Signal[float, float]
    viewport_changed: SignalNoArgs


class QtMapRenderer(QtWidgetRenderer[MapViewLike, QMap]):
    def __init__(self, view: MapViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "title": self._refresh_title,
                "center": self._refresh_center,
                "zoom": self._refresh_zoom,
                "points": self._refresh_points,
                "height": self._refresh_height,
                "tiles": self._refresh_tiles,
                "user_agent": self._refresh_user_agent,
            }
        )

    def render(self) -> None:
        if self._rendered_object is None:
            widget = self._rendered_object = QMap(self._view.user_agent, tiles=self._view.tiles)
            widget.viewport_moved.connect(self._viewport_moved)
            widget.point_clicked.connect(self._view.clicked.emit)
            self.refresh()

    @staticmethod
    def _refresh_title(_view: MapViewLike, widget: QMap, value: str) -> None:
        widget.title.setText(value)
        widget.title.setVisible(bool(value))
        widget.map.setAccessibleName(value)

    @staticmethod
    def _refresh_center(_view: MapViewLike, widget: QMap, value: MapPoint) -> None:
        widget.root.setProperty("latitude", value.latitude)
        widget.root.setProperty("longitude", value.longitude)

    @staticmethod
    def _refresh_zoom(_view: MapViewLike, widget: QMap, value: float) -> None:
        widget.root.setProperty("zoom", value)

    @staticmethod
    def _refresh_points(_view: MapViewLike, widget: QMap, value: list[MapPoint]) -> None:
        widget.root.setProperty("points", [[p.latitude, p.longitude] for p in value])

    @staticmethod
    def _refresh_height(_view: MapViewLike, widget: QMap, value: int) -> None:
        widget.map.setFixedHeight(value)

    def _configure(self, view: MapViewLike, widget: QMap, user_agent: str, *, tiles: bool) -> None:
        widget.configure(user_agent, tiles=tiles)
        self._refresh_center(view, widget, view.center)
        self._refresh_zoom(view, widget, view.zoom)
        self._refresh_points(view, widget, view.points)

    def _refresh_tiles(self, view: MapViewLike, widget: QMap, value: bool) -> None:
        self._configure(view, widget, view.user_agent, tiles=value)

    def _refresh_user_agent(self, view: MapViewLike, widget: QMap, value: str) -> None:
        self._configure(view, widget, value, tiles=view.tiles)

    def _viewport_moved(self, latitude: float, longitude: float, zoom: float) -> None:
        with self.stop_refresh():
            self._view.center = MapPoint(latitude, longitude)
            self._view.zoom = zoom
        self._view.viewport_changed.emit()

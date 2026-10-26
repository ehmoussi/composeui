"""A map and its observable events, shared by renderer and browser tests."""

from __future__ import annotations

from composeui.core.view import (
    ButtonView,
    LabelView,
    MainView,
    MapPoint,
    MapView,
    child,
    define_view,
)


@define_view
class MapMainView(MainView):
    app_title = "Maps"
    extension = ".maps"

    map: MapView = child(
        MapView,
        title="Pickup locations",
        tiles=False,
        center=MapPoint(latitude=40.73, longitude=-73.98),
        zoom=11,
        points=[MapPoint(latitude=40.73, longitude=-73.98)],
    )
    result: LabelView = child(LabelView, text="No map event")
    move: ButtonView = child(ButtonView, text="Move map")
    clear: ButtonView = child(ButtonView, text="Clear points")

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.map.clicked.connect(self._clicked)
        self.map.viewport_changed.connect(self._moved)
        self.move.clicked.connect(self._move)
        self.clear.clicked.connect(self._clear)

    def _clicked(self, latitude: float, longitude: float) -> None:
        self.result.text = f"Clicked {latitude:.2f}, {longitude:.2f}"

    def _moved(self) -> None:
        center = self.map.center
        self.result.text = (
            f"Zoom {self.map.zoom:.0f}; center {center.latitude:.5f}, {center.longitude:.5f}"
        )

    def _move(self) -> None:
        self.map.center = MapPoint(latitude=48.86, longitude=2.35)
        self.map.zoom = 12
        self.map.points = [MapPoint(latitude=48.86, longitude=2.35)]

    def _clear(self) -> None:
        self.map.points = []
        self.result.text = "Points cleared"


@define_view
class AutoMapMainView(MapMainView):
    map: MapView = child(MapView, title="Pickup locations", tiles=False)

    def _move(self) -> None:
        self.map.points = [
            MapPoint(latitude=48.85, longitude=2.34),
            MapPoint(latitude=48.87, longitude=2.36),
        ]

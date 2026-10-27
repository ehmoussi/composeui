"""Map coordinates and the state saved independently of a renderer."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from composeui.core.registry import RendererType
from composeui.core.view import MapPoint, MapView
from tests.maps import MapMainView

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    ("latitude", "longitude"), [(90, 0), (0, 181), (float("nan"), 0), (0, float("inf"))]
)
def test_maps_refuse_coordinates_outside_web_mercator(latitude: float, longitude: float) -> None:
    with pytest.raises(ValueError, match="must be"):
        MapPoint(latitude=latitude, longitude=longitude)


@pytest.mark.parametrize("zoom", [-1, 20, float("nan"), float("inf")])
def test_maps_refuse_invalid_zoom(zoom: float) -> None:
    view = MapView()
    with pytest.raises(ValueError, match="must be"):
        view.zoom = zoom


@pytest.mark.parametrize("automatic", [False, True])
def test_map_state_restores_the_viewport_but_not_data_or_tile_settings(
    tmp_path: Path, automatic: bool
) -> None:
    original = MapMainView()
    center = MapPoint(latitude=48.86, longitude=2.35)
    original.map.center = None if automatic else center
    original.map.zoom = None if automatic else 12
    original.map.points = [center]
    original.map.tiles = True
    original.map.user_agent = "Other app"
    original.map.height = 500
    path = tmp_path / "map.json"
    original.save_state(path)
    saved = json.loads(path.read_text())["views"]
    assert "points" not in saved["map"]
    restored = MapMainView()
    restored.load_state(path)
    assert restored.map.center == (None if automatic else center)
    assert restored.map.zoom == (None if automatic else 12)
    assert restored.map.points == [MapPoint(latitude=40.73, longitude=-73.98)]
    assert not restored.map.tiles
    assert restored.map.user_agent != "Other app"
    assert restored.map.height == 400


@pytest.mark.parametrize(
    ("coordinates", "override", "expected"),
    [
        ([], None, (0, 0, 1, 1)),
        ([], (40, -74), (40, -74, 1, 1)),
        ([(10, 179)], None, (10, 179, 0, 0)),
        ([(10, 179), (10, 179)], None, (10, 179, 0, 0)),
        ([(0, -10), (0, 10)], None, (0, 0, 20 / 360, 0)),
        ([(10, 179), (10, -179)], None, (10, -180, 2 / 360, 0)),
        ([(0, 0), (60, 0)], None, (35.264389682754654, 0, 0, 0.20960035913949132)),
        ([(0, 10), (60, 20)], (0, 0), (0, 0, 40 / 360, 0.41920071827898264)),
        ([(85.05112878, -1), (85.05112878, 1)], None, (85.05112878, 0, 2 / 360, 0)),
    ],
)
def test_map_bounds_follow_mercator_and_the_shortest_longitude_arc(
    coordinates: list[tuple[float, float]],
    override: tuple[float, float] | None,
    expected: tuple[float, float, float, float],
) -> None:
    points = [MapPoint(latitude=lat, longitude=lon) for lat, lon in coordinates]
    override_center = (
        None if override is None else MapPoint(latitude=override[0], longitude=override[1])
    )
    center, span_x, span_y = MapView.point_bounds(points, override_center)
    assert (center.latitude, center.longitude, span_x, span_y) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("span_x", "span_y", "width", "height", "expected"),
    [
        (0, 0, 640, 400, 12),
        (1 / 8, 0, 1088, 100, 5),
        (0, 1 / 8, 100, 576, 4),
        (1 / 8, 1 / 8, 1088, 576, 4),
        (1, 1, 1, 1, 0),
        (1e-12, 1e-12, 640, 400, 19),
    ],
)
def test_fitted_zoom_leaves_padding_and_respects_zoom_limits(
    span_x: float, span_y: float, width: int, height: int, expected: float
) -> None:
    assert MapView.fitted_zoom(span_x, span_y, width, height) == pytest.approx(expected)


def test_terminal_omits_the_map_without_losing_other_views() -> None:
    pytest.importorskip("textual")
    view = MapMainView()
    view.render(RendererType.TEXTUAL)
    assert view.map.renderer is None
    assert view.move.renderer is not None

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
        MapPoint(latitude, longitude)


@pytest.mark.parametrize("zoom", [-1, 20, float("nan"), float("inf")])
def test_maps_refuse_invalid_zoom(zoom: float) -> None:
    view = MapView()
    with pytest.raises(ValueError, match="must be"):
        view.zoom = zoom


def test_map_state_restores_the_viewport_but_not_data_or_tile_settings(tmp_path: Path) -> None:
    original = MapMainView()
    original.map.center = MapPoint(48.86, 2.35)
    original.map.zoom = 12
    original.map.points = [original.map.center]
    original.map.tiles = True
    original.map.user_agent = "Other app"
    original.map.height = 500
    path = tmp_path / "map.json"
    original.save_state(path)
    saved = json.loads(path.read_text())
    assert "points" not in saved["map"]
    restored = MapMainView()
    restored.load_state(path)
    assert restored.map.center == MapPoint(48.86, 2.35)
    assert restored.map.zoom == 12
    assert restored.map.points == [MapPoint(40.73, -73.98)]
    assert not restored.map.tiles
    assert restored.map.user_agent != "Other app"
    assert restored.map.height == 400


def test_terminal_omits_the_map_without_losing_other_views() -> None:
    pytest.importorskip("textual")
    view = MapMainView()
    view.render(RendererType.TEXTUAL)
    assert view.map.renderer is None
    assert view.move.renderer is not None

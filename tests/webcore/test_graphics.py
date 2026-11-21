"""Tests of the web map."""

from __future__ import annotations

import json
import sys

import pytest

pytest.importorskip("starlette")
# Starlette's test client: httpx2, which needs Python 3.11, or httpx before it
pytest.importorskip("httpx2" if sys.version_info >= (3, 11) else "httpx")

from composeui.webcore.webapplication import WebApplication
from tests.maps import MapMainView
from tests.webcore.support import _Browser, _element, _find, _widget_id


def test_map_http_updates_events_and_tile_attribution() -> None:
    view = MapMainView()
    app = WebApplication(build_main_view=lambda: view)
    with _Browser(app.create_starlette_app()) as client:
        response = client.get("/")
        widget = _widget_id(view.map.renderer)
        figure = _element(response.text, widget)
        attributes = next(attrs for _tag, attrs in figure.descendants if "data-map" in attrs)
        data_map = attributes["data-map"]
        assert data_map is not None
        spec = json.loads(data_map)
        assert spec["points"] == [[-73.98, 40.73]]
        assert spec["tiles"] is False
        assert "OpenStreetMap contributors" not in figure.text
        response = client.post(
            f"/widget/{widget}",
            data={"event": "viewport", "latitude": "48.86", "longitude": "2.35", "zoom": "12"},
        )
        assert response.is_success
        center = view.map.center
        assert center is not None
        assert center.latitude == 48.86
        assert center.longitude == 2.35
        assert view.map.zoom == 12
        assert "Zoom 12" in response.text
        assert _find(response.text, widget) is None
        response = client.post(
            f"/widget/{widget}", data={"event": "click", "latitude": "48.86", "longitude": "2.35"}
        )
        assert "Clicked 48.86, 2.35" in response.text
        view.map.tiles = True
        response = client.get("/")
        assert "© OpenStreetMap contributors" in response.text
        assert 'href="https://www.openstreetmap.org/copyright"' in response.text


@pytest.mark.parametrize(
    "data",
    [
        {"event": "unknown"},
        {"event": "click", "latitude": "nan", "longitude": "0"},
        {"event": "click", "latitude": "0", "longitude": "181"},
        {"event": "click", "latitude": "text", "longitude": "0"},
        {"event": "viewport", "latitude": "0", "longitude": "0", "zoom": "20"},
        {"event": "viewport", "latitude": "0", "longitude": "0", "zoom": "nan"},
    ],
)
def test_map_refuses_invalid_browser_events(data: dict[str, str]) -> None:
    view = MapMainView()
    with _Browser(WebApplication(build_main_view=lambda: view).create_starlette_app()) as client:
        client.get("/")
        widget = _widget_id(view.map.renderer)
        assert client.post(f"/widget/{widget}", data=data).status_code == 400
        assert view.result.text == "No map event"


def test_map_refuses_events_when_disabled() -> None:
    view = MapMainView()
    view.map.is_enabled = False
    with _Browser(WebApplication(build_main_view=lambda: view).create_starlette_app()) as client:
        client.get("/")
        widget = _widget_id(view.map.renderer)
        response = client.post(
            f"/widget/{widget}", data={"event": "click", "latitude": "40.73", "longitude": "-73.98"}
        )
        assert response.status_code == 400
        assert view.result.text == "No map event"

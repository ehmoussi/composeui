"""Tests of the Qt map."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from qtpy.QtCore import Qt, QUrl

from composeui.core.registry import RendererType
from composeui.core.view import (
    MapPoint,
    MapView,
)
from composeui.qtcore.qtrenderer import QtWidgetRenderer
from composeui.qtcore.widgets.qmap import QMap
from tests.maps import MapMainView

if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot


def test_map_renders_points_and_syncs_the_viewport_and_clicks(qtbot: QtBot) -> None:
    view = MapMainView()
    view.map.render(RendererType.QT)
    assert isinstance(view.map.renderer, QtWidgetRenderer)
    widget = view.map.renderer.qt_object
    assert isinstance(widget, QMap)
    qtbot.addWidget(widget)
    widget.resize(640, 440)
    widget.show()
    assert not widget.map.errors()
    assert widget.title.text() == "Pickup locations"
    assert widget.root.property("latitude") == 40.73
    assert widget.root.property("longitude") == -73.98
    assert widget.root.property("zoom") == 11
    assert widget.map.height() == 400

    widget.map.setFocus()
    widget.activateWindow()
    qtbot.waitUntil(widget.map.hasFocus)
    qtbot.keyClick(widget.map, Qt.Key.Key_Plus)
    assert view.map.zoom == 12
    assert view.result.text.startswith("Zoom 12;")
    view.map.renderer.render()
    assert widget.root.property("zoom") == 12

    qtbot.mouseClick(widget.map, Qt.MouseButton.LeftButton, pos=widget.map.rect().center())
    qtbot.waitUntil(lambda: view.result.text.startswith("Clicked"))
    assert view.result.text == "Clicked 40.73, -73.98"
    image = widget.map.grabFramebuffer()
    assert not image.isNull()
    color = image.pixelColor(image.width() // 2, image.height() // 2)
    assert color.blue() > color.green() > color.red()
    qtbot.keyClick(widget.map, Qt.Key.Key_Right)
    center = view.map.center
    assert center is not None
    assert center.longitude > -73.98
    assert center.latitude == pytest.approx(40.73)
    view.map.center = MapPoint(latitude=48.86, longitude=2.35)
    view.map.zoom = 12
    view.map.points = [MapPoint(latitude=48.86, longitude=2.35)]
    assert widget.root.property("latitude") == 48.86
    assert widget.root.property("longitude") == 2.35
    assert widget.root.property("zoom") == 12
    assert widget.root.property("points") == [[48.86, 2.35]]
    view.map.title = "Paris"
    view.map.height = 250
    view.map.user_agent = "ComposeUI test"
    assert widget.title.text() == "Paris"
    assert widget.map.height() == 250
    assert widget.root.property("latitude") == 48.86
    assert widget.root.property("zoom") == 12


def test_map_fits_late_points_and_resizes_until_the_user_chooses_a_viewport(qtbot: QtBot) -> None:
    view = MapView(tiles=False)
    events: list[tuple[MapPoint | None, float | None]] = []
    view.viewport_changed.connect(lambda: events.append((view.center, view.zoom)))
    view.render(RendererType.QT)
    assert isinstance(view.renderer, QtWidgetRenderer)
    widget = view.renderer.qt_object
    assert isinstance(widget, QMap)
    qtbot.addWidget(widget)
    widget.resize(640, 440)
    widget.show()
    assert widget.root.property("latitude") == 0
    assert widget.root.property("longitude") == 0

    view.points = [MapPoint(latitude=0, longitude=-10), MapPoint(latitude=0, longitude=10)]
    qtbot.waitUntil(lambda: widget.map.width() == widget.width())
    assert widget.root.property("longitude") == pytest.approx(0)
    zoom = widget.root.property("zoom")
    widget.resize(2 * widget.width() - 64, widget.height())
    qtbot.waitUntil(lambda: widget.root.property("zoom") > zoom)
    fitted_zoom = widget.root.property("zoom")
    assert fitted_zoom == pytest.approx(zoom + 1)

    view.center = MapPoint(latitude=0, longitude=10)
    assert widget.root.property("longitude") == 10
    assert widget.root.property("zoom") == pytest.approx(fitted_zoom - 1)
    view.zoom = 8
    assert widget.root.property("zoom") == 8
    view.center = None
    assert widget.root.property("longitude") == pytest.approx(0)
    assert widget.root.property("zoom") == 8
    view.zoom = None
    assert widget.root.property("zoom") == pytest.approx(fitted_zoom)
    assert events == []

    widget.activateWindow()
    widget.map.setFocus()
    qtbot.waitUntil(widget.map.hasFocus)
    qtbot.keyClick(widget.map, Qt.Key.Key_Plus)
    assert len(events) == 1
    center, chosen_zoom = events[0]
    assert center is not None
    assert chosen_zoom == pytest.approx(fitted_zoom + 1)
    view.points = [MapPoint(latitude=48.86, longitude=2.35)]
    widget.resize(640, 440)
    assert widget.root.property("latitude") == center.latitude
    assert widget.root.property("longitude") == center.longitude
    assert widget.root.property("zoom") == chosen_zoom

    view.center = None
    view.zoom = None
    assert widget.root.property("latitude") == 48.86
    assert widget.root.property("longitude") == 2.35
    assert widget.root.property("zoom") == 12
    assert len(events) == 1


def test_an_unloaded_qml_map_reports_a_deployment_error(qtbot: QtBot) -> None:
    widget = QMap("ComposeUI test", tiles=False)
    qtbot.addWidget(widget)
    widget.map.setSource(QUrl())
    with pytest.raises(RuntimeError, match="Cannot load the Qt Location map"):
        _ = widget.root

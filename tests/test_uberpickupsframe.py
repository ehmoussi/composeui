"""The pickups example on a Polars frame: loading, failures, and its table, chart and map."""

from __future__ import annotations

import datetime
import gzip
from typing import TYPE_CHECKING, TypeVar, cast

import pytest

pytest.importorskip("narwhals")
pytest.importorskip("polars")
import polars as pl

from composeui.core.application import ModelApplication
from composeui.core.registry import RendererType
from composeui.core.renderer import RendererContainer
from composeui.core.view import MapPoint
from examples import uberpickupsframe

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from pytestqt.qtbot import QtBot

    from composeui.core.view import View
    from composeui.qtcore.qtrenderer import QtWidgetRenderer


App = ModelApplication[uberpickupsframe.UberPickupsMainView, uberpickupsframe.UberPickupsModel]
# a pickup without a date counts in no hour, but shows in the table
_CSV = (
    "Date/Time,Lat,Lon,Base\n"
    "9/1/2014 11:01:00,40.7,-73.9,B02512\n"
    "9/1/2014 13:05:00,40.8,-73.8,B02598\n"
    ",40.9,-73.7,B02512\n"
)


def _csv(tmp_path: Path, text: str = _CSV) -> str:
    path = tmp_path / "pickups.csv.gz"
    path.write_bytes(gzip.compress(text.encode()))
    return str(path)  # Polars reads a path, not a file:// URL


def _app() -> App:
    return App(
        build_main_view=uberpickupsframe.UberPickupsMainView,
        build_model=uberpickupsframe.UberPickupsModel,
        setup_model=uberpickupsframe.UberPickupsMainView.connect_model,
    )


@pytest.fixture
def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[App]:
    monkeypatch.setattr(uberpickupsframe, "DATA_URL", _csv(tmp_path))
    app = _app()
    yield app
    app.main_view.jobs.wait()


def test_pickups_load_into_the_table_the_hourly_chart_and_the_map(app: App) -> None:
    app.main_view.jobs.wait()
    page = app.main_view
    assert not page.status.is_visible
    assert page.pickups_chart.is_visible
    assert page.pickups_map.is_visible
    assert page.pickups_chart.series[0].y == [*([0] * 11), 1, 0, 1, *([0] * 10)]
    assert page.pickups_map.points == [MapPoint(latitude=40.7, longitude=-73.9)]
    source = page.table.source
    assert source is not None
    assert source.count() == 3
    assert source.cells([0], ["Date/Time", "Base"]) == {
        0: [datetime.datetime.fromisoformat("2014-09-01T11:01"), "B02512"]
    }


WidgetT = TypeVar("WidgetT")


def _qt_object(renderer: object, widget_type: type[WidgetT]) -> WidgetT:
    """Get the Qt widget of `renderer`, checked to be a `widget_type`."""
    renderer_type: type[QtWidgetRenderer] = pytest.importorskip(
        "composeui.qtcore.qtrenderer"
    ).QtWidgetRenderer
    assert isinstance(renderer, renderer_type)
    widget = cast("QtWidgetRenderer", renderer).qt_object
    assert isinstance(widget, widget_type)
    return widget


def _qt_widget(view: View, widget_type: type[WidgetT]) -> WidgetT:
    """Get the Qt widget that shows `view`, checked to be a `widget_type`."""
    return _qt_object(view.renderer, widget_type)


def _qt_field(row: View, widget_type: type[WidgetT]) -> WidgetT:
    """Get the Qt widget of the form row `row`'s field, checked to be a `widget_type`."""
    assert isinstance(row.renderer, RendererContainer)
    return _qt_object(row.renderer.get_renderer("field"), widget_type)


def test_the_raw_data_checkbox_and_the_hour_slider_drive_the_table_and_map(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    qt_widgets = pytest.importorskip("qtpy.QtWidgets")
    monkeypatch.setattr(uberpickupsframe, "DATA_URL", _csv(tmp_path))
    app = _app()
    view = app.main_view
    view.pickups_map.tiles = False
    try:
        app.render(RendererType.QT)
        qtbot.addWidget(_qt_widget(view, qt_widgets.QWidget))
        qtbot.waitUntil(lambda: view.pickups_chart.is_visible)

        window = _qt_widget(view, qt_widgets.QWidget)
        checkbox = _qt_field(view.sidebar.filters.show_raw_data, qt_widgets.QCheckBox)
        slider = _qt_field(view.sidebar.filters.hour, qt_widgets.QSlider)
        # the filters show in the sidebar, beside the content
        assert checkbox.isVisibleTo(window)
        assert slider.isVisibleTo(window)
        assert not view.table.is_visible
        checkbox.click()
        assert view.table.is_visible

        slider.setValue(13)
        assert view.pickups_map.points == [MapPoint(latitude=40.8, longitude=-73.8)]
    finally:
        view.jobs.drop()


def test_an_invalid_csv_is_shown_as_a_loading_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _csv(tmp_path, f"{_CSV}invalid-date,40.7,-73.9,B\n")
    monkeypatch.setattr(uberpickupsframe, "DATA_URL", path)
    app = _app()
    app.main_view.jobs.wait()
    page = app.main_view
    assert page.status.is_visible
    assert page.status.text.startswith("Failed to read the CSV:")
    assert not page.pickups_chart.is_visible
    assert not page.pickups_map.is_visible
    assert page.table.source is None


def test_map_sampling_bounds_large_datasets_and_skips_polar_coordinates() -> None:
    at = datetime.datetime.fromisoformat("2014-09-01T00:01")
    frame = pl.DataFrame(
        {
            "Date/Time": [at] * 10001,
            "Lat": [90.0, *(40.7 + i / 1_000_000 for i in range(10000))],
            "Lon": [0.0] + [-73.9] * 10000,
            "Base": ["B"] * 10001,
        }
    )

    points = uberpickupsframe.pickup_points(frame, 0)

    assert 0 < len(points) <= 10000
    assert len(set(points)) == len(points)
    assert all(40.7 <= point.latitude <= 40.71 for point in points)
    assert sum(uberpickupsframe.pickups_by_hour(frame)) == 10001

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
from composeui.core.jobs import Job
from composeui.core.registry import RendererType
from composeui.core.view import MapPoint
from examples import uberpickupsframe

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from pytestqt.qtbot import QtBot

    from composeui.core.view import View
    from composeui.qtcore.qtrenderer import QtWidgetRenderer


App = ModelApplication[
    uberpickupsframe.UberPickupsFrameMainView, uberpickupsframe.UberPickupsFrameModel
]
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
        build_main_view=uberpickupsframe.UberPickupsFrameMainView,
        build_model=uberpickupsframe.UberPickupsFrameModel,
        setup_model=uberpickupsframe.UberPickupsFrameMainView.connect_model,
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
    assert page.data_load_state.text == "Done! (using Polars)"
    assert not page.data_load_status.is_visible
    assert page.data.is_visible
    assert page.data.pickups_chart.series[0].y == [*([0] * 11), 1, 0, 1, *([0] * 10)]
    assert page.data.pickups_map.points == [MapPoint(latitude=40.7, longitude=-73.9)]
    source = page.data.table.source
    assert source is not None
    assert source.count() == 3
    assert source.cells([0], ["date_time", "base"]) == {
        0: [datetime.datetime.fromisoformat("2014-09-01T11:01"), "B02512"]
    }


WidgetT = TypeVar("WidgetT")


def _qt_widget(view: View, widget_type: type[WidgetT]) -> WidgetT:
    """Get the Qt widget that shows `view`, checked to be a `widget_type`."""
    renderer_type: type[QtWidgetRenderer] = pytest.importorskip(
        "composeui.qtcore.qtrenderer"
    ).QtWidgetRenderer
    assert isinstance(view.renderer, renderer_type)
    widget = cast("QtWidgetRenderer", view.renderer).qt_object
    assert isinstance(widget, widget_type)
    return widget


def test_the_raw_data_checkbox_and_the_hour_slider_drive_the_table_and_map(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    qt_widgets = pytest.importorskip("qtpy.QtWidgets")
    monkeypatch.setattr(uberpickupsframe, "DATA_URL", _csv(tmp_path))
    app = ModelApplication(
        build_main_view=uberpickupsframe.UberPickupsFrameMainView,
        build_model=uberpickupsframe.UberPickupsFrameModel,
    )
    view = app.main_view
    view.data.pickups_map.tiles = False
    try:
        app.render(RendererType.QT)
        qtbot.addWidget(_qt_widget(view, qt_widgets.QWidget))
        view.connect_model(app.model)
        qtbot.waitUntil(lambda: not view.loader.is_running)

        checkbox = _qt_widget(view.show_raw_data, qt_widgets.QCheckBox)
        assert not view.data.table.is_visible
        checkbox.click()
        assert view.data.table.is_visible

        slider = _qt_widget(view.data.slider_hours, qt_widgets.QSlider)
        slider.setValue(13)
        assert view.data.pickups_map.points == [MapPoint(latitude=40.8, longitude=-73.8)]
    finally:
        view.jobs.drop()


def test_an_invalid_csv_is_shown_as_a_loading_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _csv(tmp_path, f"{_CSV}invalid-date,40.7,-73.9,B\n")
    monkeypatch.setattr(uberpickupsframe, "DATA_URL", path)
    app = _app()
    app.main_view.status_bar.timeout = 0
    app.main_view.jobs.wait()
    page = app.main_view
    assert page.data_load_state.text == "Failed to load data"
    assert not page.data.is_visible
    assert "Failed to read the CSV:" in page.status_bar.message
    assert app.model.pickups.count() == 0


def test_a_canceled_load_gives_no_hours_nor_points(tmp_path: Path) -> None:
    model = uberpickupsframe.UberPickupsFrameModel()
    job: Job[uberpickupsframe.PickupData, int] = Job(lambda _job, callback: callback())
    job.cancel()

    result = model.load_pickups(job, _csv(tmp_path), 11)

    assert (result.hours, result.points) == ([], [])


def test_map_sampling_bounds_large_datasets_and_skips_polar_coordinates() -> None:
    at = datetime.datetime.fromisoformat("2014-09-01T00:01")
    frame = pl.DataFrame(
        {
            "date_time": [at] * 10001,
            "lat": [90.0, *(40.7 + i / 1_000_000 for i in range(10000))],
            "lon": [0.0] + [-73.9] * 10000,
            "base": ["B"] * 10001,
        }
    )

    points = uberpickupsframe.pickup_points(frame, 0)

    assert 0 < len(points) <= 10000
    assert len(set(points)) == len(points)
    assert all(40.7 <= point.latitude <= 40.71 for point in points)
    assert sum(uberpickupsframe.pickups_by_hour(frame)) == 10001

"""CSV loading, failures, and study restoration in the pickups example."""

from __future__ import annotations

import gzip
from typing import TYPE_CHECKING

import pytest

from composeui.core.application import ModelApplication
from composeui.core.jobs import Job
from composeui.core.reload import load_reloaded_state, save_reloaded_state
from examples import uberpickups

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


App = ModelApplication[uberpickups.UberPickupsMainView, uberpickups.UberPickupsModel]
_CSV = (
    "Date/Time,Lat,Lon,Base\n"
    "9/1/2014 0:01:00,40.7,-73.9,B02512\n"
    "9/1/2014 13:05:00,40.8,-73.8,B02512\n"
)


def _app() -> App:
    return App(
        build_main_view=uberpickups.UberPickupsMainView,
        build_model=uberpickups.UberPickupsModel,
        setup_model=uberpickups.UberPickupsMainView.connect_model,
    )


@pytest.fixture
def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[App]:
    path = tmp_path / "pickups.csv.gz"
    path.write_bytes(gzip.compress(_CSV.encode()))
    monkeypatch.setattr(uberpickups, "DATA_URL", path.as_uri())
    app = _app()
    yield app
    app.main_view.jobs.wait()
    app.model.close()


def test_pickups_load_progress_table_and_hourly_chart(app: App) -> None:
    app.main_view.jobs.wait()
    page = app.main_view.page
    assert page.data_load_state.text == "Done! (using SQLite)"
    assert page.data_load_status.text == "Read 2 rows from CSV"
    assert not page.data_load_status.is_visible
    assert page.pickups_chart.is_visible
    assert page.pickups_chart.series[0].y == [1, *([0] * 12), 1, *([0] * 10)]
    assert page.table.source is not None
    assert page.table.source.count() == 2
    page.show_raw_data.is_checked = True
    page.show_raw_data.toggled.emit(page.show_raw_data.is_checked)
    assert page.table.is_visible
    assert not page.pickups_chart.is_visible
    page.show_raw_data.is_checked = False
    page.show_raw_data.toggled.emit(page.show_raw_data.is_checked)
    assert not page.table.is_visible
    assert page.pickups_chart.is_visible


def test_reload_reconnects_saved_rows_without_downloading_them_again(
    app: App, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app.main_view.jobs.wait()
    save_reloaded_state(app.main_view, app.model, tmp_path)
    restored = _app()
    try:
        # The saved database must suffice even when the original download is unavailable.
        monkeypatch.setattr(uberpickups, "DATA_URL", (tmp_path / "missing.csv.gz").as_uri())
        load_reloaded_state(restored.main_view, restored.model, tmp_path)
        restored.main_view.jobs.wait()
        page = restored.main_view.page
        assert page.table.source is not None
        assert page.table.source.count() == 2
        assert page.pickups_chart.series[0].y == app.main_view.page.pickups_chart.series[0].y
        assert page.pickups_chart.is_visible
        assert not page.data_load_status.is_visible
        assert page.data_load_state.text == "Done! (using SQLite)"
    finally:
        restored.model.close()


@pytest.mark.parametrize(("lat", "lon"), [(91, 0), (-91, 0), (0, 181), (0, -181)])
def test_invalid_pickup_coordinates_are_shown_as_a_loading_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, lat: int, lon: int
) -> None:
    path = tmp_path / "invalid.csv.gz"
    path.write_bytes(
        gzip.compress(f"Date/Time,Lat,Lon,Base\n9/1/2014 0:01:00,{lat},{lon},B\n".encode())
    )
    monkeypatch.setattr(uberpickups, "DATA_URL", path.as_uri())
    app = _app()
    app.main_view.status_bar.timeout = 0
    try:
        app.main_view.jobs.wait()
        page = app.main_view.page
        assert page.data_load_state.text == "Failed to load data"
        assert not page.data_load_status.is_visible
        assert not page.pickups_chart.is_visible
        assert not page.table.is_visible
        assert "Failed to read the CSV:" in app.main_view.status_bar.message
        assert "must be" in app.main_view.status_bar.message
        assert app.model.uber_data.fetch_column("SELECT COUNT(*) FROM uber_data") == [0]
    finally:
        app.model.close()


def test_a_canceled_csv_job_rolls_back_before_showing_any_rows(
    tmp_path: Path,
) -> None:
    path = tmp_path / "pickups.csv.gz"
    path.write_bytes(gzip.compress(_CSV.encode()))
    model = uberpickups.UberPickupsModel()
    page = uberpickups.UberPickupsPageView()
    # Cancel before the first yielded batch, as New/Open can do during a download.
    job: Job[list[int]] = Job(lambda _job, callback: callback())
    job.cancel()
    try:
        assert page.fill(job, model, path.as_uri()) == []
        assert model.uber_data.fetch_column("SELECT COUNT(*) FROM uber_data") == [0]
        assert not page.table.is_visible
        assert not page.pickups_chart.is_visible
    finally:
        model.close()


def test_hourly_counts_ignore_rows_without_a_valid_hour() -> None:
    model = uberpickups.UberPickupsModel()
    try:
        with model.uber_data.connection() as db:
            db.execute("INSERT INTO uber_data VALUES ('not a timestamp', 0, 0, 'B')")
        assert model.uber_data.pickups_by_hour() == [0] * 24
    finally:
        model.close()

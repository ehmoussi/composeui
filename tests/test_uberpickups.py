"""CSV loading, failures, and study restoration in the pickups example."""

from __future__ import annotations

import gzip
import threading
from html.parser import HTMLParser
from typing import TYPE_CHECKING, TypeVar, cast

import pytest

from composeui.core.application import ModelApplication
from composeui.core.jobs import Job
from composeui.core.registry import RendererType
from composeui.core.reload import load_reloaded_state, save_reloaded_state
from composeui.core.renderer import RendererContainer
from composeui.core.view import MapPoint
from examples import uberpickups

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from pytestqt.qtbot import QtBot

    from composeui.core.view import View
    from composeui.qtcore.qtrenderer import QtWidgetRenderer
    from composeui.webcore.webrenderer import WebRenderer


App = ModelApplication[uberpickups.UberPickupsMainView, uberpickups.UberPickupsModel]
_CSV = (
    "Date/Time,Lat,Lon,Base\n"
    "9/1/2014 11:01:00,40.7,-73.9,B02512\n"
    "9/1/2014 13:05:00,40.8,-73.8,B02512\n"
)


class _VisibilityParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.hidden_ids: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        element_id = attributes.get("id")
        if element_id is not None:
            self.ids.add(element_id)
            if "hidden" in attributes:
                self.hidden_ids.add(element_id)


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
    page = app.main_view
    assert not page.status.is_visible
    assert page.status.text == "Read 2 rows from CSV"
    assert page.pickups_chart.series[0].y == [*([0] * 11), 1, 0, 1, *([0] * 10)]
    assert page.table.source is not None
    assert page.table.source.count() == 2
    assert page.pickups_map.points == [
        MapPoint(latitude=40.7, longitude=-73.9),
    ]
    assert page.pickups_chart.is_visible
    assert page.pickups_map.is_visible


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


def _qt_field(row: View, widget_type: type[WidgetT]) -> WidgetT:
    """Get the Qt widget of the form row `row`'s field, checked to be a `widget_type`."""
    assert isinstance(row.renderer, RendererContainer)
    return _qt_object(row.renderer.get_renderer("field"), widget_type)


def _select_hour(
    view: uberpickups.UberPickupsMainView, hour: int, expected_points: list[MapPoint]
) -> None:
    qt_widgets = pytest.importorskip("qtpy.QtWidgets")
    slider = _qt_field(view.filters.hour, qt_widgets.QSlider)
    slider.setValue(hour)
    assert view.pickups_map.points == expected_points
    assert view.pickups_chart.series[0].y == [*([0] * 11), 1, 0, 1, *([0] * 10)]
    assert view.table.source is not None
    assert view.table.source.count() == 2


def test_visibility_follows_loading_and_real_checkbox_clicks(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    qt_widgets = pytest.importorskip("qtpy.QtWidgets")
    path = tmp_path / "pickups.csv.gz"
    path.write_bytes(gzip.compress(_CSV.encode()))
    monkeypatch.setattr(uberpickups, "DATA_URL", path.as_uri())
    app = _app()
    view = app.main_view
    view.pickups_map.tiles = False
    try:
        # the loader started with the app, before it renders: its outcome still shows
        app.render(RendererType.QT)
        window = _qt_object(view.renderer, qt_widgets.QWidget)
        qtbot.addWidget(window)
        checkbox = _qt_object(view.filters.show_raw_data.renderer, qt_widgets.QCheckBox)
        table, chart, map_widget, status = (
            _qt_object(child.renderer, qt_widgets.QWidget)
            for child in (view.table, view.pickups_chart, view.pickups_map, view.status)
        )
        # the filters show in the sidebar, beside the content
        for widget in (checkbox, _qt_field(view.filters.hour, qt_widgets.QSlider)):
            assert window.isAncestorOf(widget)  # a widget never added is "visible" too
            assert widget.isVisibleTo(window)

        def assert_visibility(*, loaded: bool, raw: bool) -> None:
            assert chart.isVisibleTo(window) == loaded
            assert map_widget.isVisibleTo(window) == loaded
            assert status.isVisibleTo(window) == (not loaded)
            assert table.isVisibleTo(window) == raw

        qtbot.waitUntil(lambda: not view.loader.is_running)
        assert_visibility(loaded=True, raw=False)

        checkbox.click()
        assert_visibility(loaded=True, raw=True)
        _select_hour(view, 13, [MapPoint(latitude=40.8, longitude=-73.8)])
        checkbox.click()
        assert_visibility(loaded=True, raw=False)
        assert view.pickups_map.points == [MapPoint(latitude=40.8, longitude=-73.8)]
        _select_hour(view, 12, [])
        view.jobs.drop()
        checkbox.click()
        assert_visibility(loaded=False, raw=True)
    finally:
        view.close()  # its window first: a table shown reads the model as it paints
        app.model.close()


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
        page = restored.main_view
        assert page.table.source is not None
        assert page.table.source.count() == 2
        assert page.pickups_chart.series[0].y == app.main_view.pickups_chart.series[0].y
        assert page.pickups_chart.is_visible
        assert not page.status.is_visible
    finally:
        restored.model.close()


def test_web_csv_commit_does_not_restart_the_running_loader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    web = pytest.importorskip("composeui.webcore.webapplication")
    renderer_type: type[WebRenderer] = pytest.importorskip(
        "composeui.webcore.webrenderer"
    ).WebRenderer
    testclient = pytest.importorskip("starlette.testclient")
    path = tmp_path / "pickups.csv.gz"
    path.write_bytes(gzip.compress(_CSV.encode()))
    monkeypatch.setattr(uberpickups, "DATA_URL", path.as_uri())
    views: list[uberpickups.UberPickupsMainView] = []
    models: list[uberpickups.UberPickupsModel] = []

    def build_view() -> uberpickups.UberPickupsMainView:
        view = uberpickups.UberPickupsMainView()
        views.append(view)
        return view

    def build_model() -> uberpickups.UberPickupsModel:
        model = uberpickups.UberPickupsModel()
        models.append(model)
        return model

    app = web.WebModelApplication(build_main_view=build_view, build_model=build_model)
    done = threading.Event()
    with testclient.TestClient(app.create_starlette_app()) as client:
        client.get("/")
        view, model = views[-1], models[-1]
        # Start after rendering, as a download that outlasts the initial page render does.
        view.connect_model(model)

        def finished() -> None:
            if not view.loader.is_running:
                done.set()

        view.loader.changed.connect(finished, now=True)
        assert done.wait(10)
        response = client.get("/jobs")
        visibility = _VisibilityParser()
        visibility.feed(response.text)

        def widget_id_of(renderer: object) -> str:
            assert isinstance(renderer, renderer_type)
            return cast("WebRenderer", renderer).widget_id

        def widget_id(child: View) -> str:
            return widget_id_of(child.renderer)

        for child in (view.pickups_chart, view.pickups_map):
            assert widget_id(child) in visibility.ids
            assert widget_id(child) not in visibility.hidden_ids
        assert widget_id(view.status) in visibility.hidden_ids
        page = _VisibilityParser()
        page.feed(client.get("/").text)
        # the filters in the sidebar: the check box, and the slider's field, not only its label
        hour = view.filters.hour.renderer
        assert isinstance(hour, RendererContainer)
        for renderer in (view.filters.show_raw_data.renderer, hour.get_renderer("field")):
            assert widget_id_of(renderer) in page.ids
        assert view.loader.error is None


@pytest.mark.parametrize(
    "row",
    ["invalid-date,40.7,-73.9,B", "9/1/2014 0:01:00,invalid-lat,-73.9,B"],
)
def test_invalid_csv_is_shown_as_a_loading_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, row: str
) -> None:
    path = tmp_path / "invalid.csv.gz"
    path.write_bytes(gzip.compress(f"{_CSV}{row}\n".encode()))
    monkeypatch.setattr(uberpickups, "DATA_URL", path.as_uri())
    app = _app()
    try:
        app.main_view.jobs.wait()
        page = app.main_view
        assert page.status.is_visible
        assert page.status.text.startswith("Failed to read the CSV:")
        assert not page.pickups_chart.is_visible
        assert not page.pickups_map.is_visible
        assert app.model.uber_data.fetch_column("SELECT COUNT(*) FROM uber_data") == [0]
    finally:
        app.model.close()


def test_a_canceled_csv_job_rolls_back_before_showing_any_rows(
    tmp_path: Path,
) -> None:
    path = tmp_path / "pickups.csv.gz"
    path.write_bytes(gzip.compress(_CSV.encode()))
    model = uberpickups.UberPickupsModel()
    # Cancel before the first yielded batch, as New/Open can do during a download.
    job: Job[uberpickups.PickupData, int] = Job(lambda _job, callback: callback())
    job.cancel()
    try:
        assert model.load_pickups(job, path.as_uri(), 11) == uberpickups.PickupData(
            hours=[], points=[]
        )
        assert model.uber_data.fetch_column("SELECT COUNT(*) FROM uber_data") == [0]
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


def test_map_sampling_bounds_large_datasets_and_skips_polar_coordinates() -> None:
    model = uberpickups.UberPickupsModel()
    try:
        with model.uber_data.connection() as db:
            db.executemany(
                "INSERT INTO uber_data VALUES (?, ?, ?, ?)",
                [
                    ("2014-09-01T00:01:00", 90, 0, "B"),
                    *(
                        ("2014-09-01T00:01:00", 40.7 + i / 1_000_000, -73.9, "B")
                        for i in range(10000)
                    ),
                ],
            )
        points = model.uber_data.pickup_points(0)
        assert 0 < len(points) <= 10000
        assert len(set(points)) == len(points)
        assert all(40.7 <= point.latitude <= 40.71 for point in points)
        assert sum(model.uber_data.pickups_by_hour()) == 10001
    finally:
        model.close()

"""The first dashboard: pickups read from a CSV, filtered by base, day and hour, downloaded."""

from __future__ import annotations

import datetime
import io
import re
import time
from typing import TYPE_CHECKING, BinaryIO, cast

import pytest

pytest.importorskip("polars")
pytest.importorskip("starlette")
import polars as pl
from starlette.testclient import TestClient

from composeui.core.application import Application
from composeui.core.renderer import RendererContainer
from composeui.core.view import DownloadSink, MapPoint, StreamContent
from composeui.webcore.webapplication import WebApplication
from composeui.webcore.webrenderer import WebRenderer
from examples import uberdashboard
from examples.uberdashboard import UberDashboardMainView

if TYPE_CHECKING:
    from pathlib import Path

    from composeui.core.view import View

# two bases, three days, and a pickup without a date: in no day and no hour
_CSV = (
    "Date/Time,Lat,Lon,Base\n"
    "9/1/2014 11:01:00,40.7,-73.9,B02512\n"
    "9/2/2014 13:05:00,40.8,-73.8,B02598\n"
    "9/3/2014 13:30:00,40.75,-73.85,B02512\n"
    ",40.9,-73.7,B02512\n"
)


@pytest.fixture(autouse=True)
def data_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "pickups.csv"
    path.write_text(_CSV, encoding="utf-8")
    monkeypatch.setattr(uberdashboard, "DATA_URL", str(path))
    return path


def _written(content: StreamContent) -> bytes:
    pieces: list[bytes] = []
    # not seekable, as the web's
    sink = cast("BinaryIO", DownloadSink(pieces.append))
    content.write(sink)
    sink.close()
    return b"".join(pieces)


def test_the_filters_drive_the_summary_the_chart_the_map_the_table_and_the_download() -> None:
    page = Application(build_main_view=UberDashboardMainView).main_view
    page.jobs.wait()
    filters = page.filters
    assert list(filters.bases.values) == ["B02512", "B02598"]
    assert (filters.days.minimum, filters.days.maximum) == (
        datetime.date(2014, 9, 1),
        datetime.date(2014, 9, 3),
    )
    assert (filters.hours.minimum, filters.hours.maximum) == (11, 13)
    # untouched, the filters keep every pickup: the one without a date too
    assert page.summary.pickups.value == "4"

    filters.bases.selected = ["B02512"]
    filters.days.value = (datetime.date(2014, 9, 2), None)

    assert page.summary.pickups.value == "1"
    assert page.summary.bases.value == "1"
    assert page.summary.busiest_hour.value == "13:00"
    assert page.by_hour.series[0].y == [*([0] * 13), 1, *([0] * 10)]
    assert page.pickups_map.points == [MapPoint(latitude=40.75, longitude=-73.85)]
    assert page.table.row_count == 1
    content = page.download_rows.content
    assert content is not None
    file = content()
    assert isinstance(file, StreamContent)
    assert pl.read_csv(io.BytesIO(_written(file))).get_column("Base").to_list() == ["B02512"]

    filters.hours.value = (11, 11)
    assert page.summary.pickups.value == "0"
    assert page.summary.busiest_hour.value == "-"


def test_a_csv_that_can_t_be_read_shows_why(data_url: Path) -> None:
    data_url.write_text(f"{_CSV}invalid-date,40.7,-73.9,B\n", encoding="utf-8")

    page = Application(build_main_view=UberDashboardMainView).main_view
    page.jobs.wait()

    assert page.status.is_visible
    assert page.status.text.startswith("Failed: ")
    assert not page.summary.is_visible
    assert not page.download_rows.is_visible


def _field_id(row: View) -> str:
    assert isinstance(row.renderer, RendererContainer)
    renderer = row.renderer.get_renderer("field")
    assert isinstance(renderer, WebRenderer)
    return renderer.widget_id


def test_a_user_unchecks_a_base_on_the_web_and_downloads_the_rows_shown() -> None:
    views: list[UberDashboardMainView] = []

    class DashboardApp(WebApplication[UberDashboardMainView]):
        def setup_session(self, main_view: UberDashboardMainView) -> None:
            views.append(main_view)

    app = DashboardApp(build_main_view=UberDashboardMainView)
    with TestClient(
        app.create_starlette_app(), headers={"Sec-Fetch-Site": "same-origin"}
    ) as client:
        client.get("/")
        (page,) = views
        for _ in range(600):  # the page's poller: it brings the job's result to the views
            client.get("/jobs")
            if page.loader.has_result:
                break
            time.sleep(0.05)
        assert page.summary.pickups.value == "4"

        # a base's key is its text: a page posts it as it shows it
        client.post(
            f"/widget/{_field_id(page.filters.bases)}",
            data={"event": "toggle", "key": "B02512"},  # unchecked: no "checked"
        )
        assert page.summary.pickups.value == "1"

        assert isinstance(page.download_rows.renderer, WebRenderer)
        body = client.post(
            f"/widget/{page.download_rows.renderer.widget_id}", data={"event": "click"}
        ).text
        # the newest: the answer names each file not fetched yet
        *_, address = re.findall(r'href="(/download/[^"]+)"', body)
        downloaded = client.get(address)

    assert downloaded.status_code == 200
    assert "pickups.csv" in downloaded.headers["content-disposition"]
    assert pl.read_csv(io.BytesIO(downloaded.content)).get_column("Base").to_list() == ["B02598"]

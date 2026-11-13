"""The data explorer example: a user's file uploaded, read, filtered and exported."""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Any

import pytest

pytest.importorskip("polars")
pytest.importorskip("starlette")
import polars as pl
from starlette.testclient import TestClient

from composeui.core.application import Application
from composeui.core.dashboard import read_frame
from composeui.core.view import UploadedFile
from composeui.webcore.webapplication import WebApplication
from composeui.webcore.webrenderer import WebRenderer
from examples import dataexplorer
from examples.dataexplorer import DataExplorerMainView, size_text

if TYPE_CHECKING:
    from pathlib import Path

_CSV = "base,count\nB02512,1\nB02764,2\nB02764,3\n"


@pytest.fixture
def main_view() -> DataExplorerMainView:
    return Application(build_main_view=DataExplorerMainView).main_view


def _give(main_view: DataExplorerMainView, path: Path) -> None:
    main_view.upload.take_file(UploadedFile.of_path(path))
    main_view.jobs.wait()


def test_a_csv_or_parquet_file_shows_its_rows_and_its_summary(
    main_view: DataExplorerMainView, tmp_path: Path
) -> None:
    assert main_view.status.text == "Choose a CSV or Parquet file to explore."
    assert not main_view.table.is_visible
    csv = tmp_path / "pickups.csv"
    csv.write_text(_CSV, encoding="utf-8")

    _give(main_view, csv)

    assert main_view.table.is_visible
    assert main_view.table.row_count == 3
    assert main_view.summary.rows.value == "3"
    assert main_view.summary.columns.value == "2"
    assert main_view.table.export_filename == "pickups-filtered.csv"

    parquet = tmp_path / "more.parquet"
    pl.DataFrame({"name": ["a", "b"], "x": [1, 2], "y": [3, 4]}).write_parquet(parquet)
    _give(main_view, parquet)

    assert main_view.table.row_count == 2
    assert main_view.summary.columns.value == "3"


def test_the_summary_and_the_export_keep_to_the_rows_shown_during_a_new_read(
    main_view: DataExplorerMainView, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = tmp_path / "first.csv"
    first.write_text(_CSV, encoding="utf-8")
    _give(main_view, first)
    size = main_view.summary.size.value
    second = tmp_path / "second.csv"
    second.write_text("x\n" + "1\n" * 5000, encoding="utf-8")
    release = threading.Event()

    def wait_then_read(path: Path, *, backend: Any) -> Any:
        assert release.wait(30)
        return read_frame(path, backend=backend)

    monkeypatch.setattr(dataexplorer, "read_frame", wait_then_read)
    main_view.upload.take_file(UploadedFile.of_path(second))

    assert main_view.table.export_filename == "first-filtered.csv"
    assert main_view.summary.size.value == size

    release.set()
    main_view.jobs.wait()
    assert main_view.table.export_filename == "second-filtered.csv"
    assert main_view.summary.rows.value == "5,000"


@pytest.mark.parametrize(
    ("size", "text"), [(2048, "2.0 KiB"), (3 * 1024**2, "3.0 MiB")], ids=["small", "large"]
)
def test_a_file_s_size_reads_in_a_unit_that_fits_it(size: int, text: str) -> None:
    assert size_text(size) == text


def test_a_file_that_can_t_be_read_says_why_and_shows_no_old_rows(
    main_view: DataExplorerMainView, tmp_path: Path
) -> None:
    good = tmp_path / "good.csv"
    good.write_text(_CSV, encoding="utf-8")
    _give(main_view, good)
    bad = tmp_path / "bad.parquet"
    bad.write_text("not parquet", encoding="utf-8")

    _give(main_view, bad)

    assert main_view.status.text.startswith("Can't read the file: ")
    assert not main_view.table.is_visible
    assert not main_view.summary.is_visible


def test_a_user_uploads_a_dataset_filters_it_and_exports_the_rows_shown() -> None:
    views: list[DataExplorerMainView] = []

    class ExplorerApp(WebApplication[DataExplorerMainView]):
        def setup_session(self, main_view: DataExplorerMainView) -> None:
            views.append(main_view)

    app = ExplorerApp(build_main_view=DataExplorerMainView)
    dataset = b"base,count\n" + b"B02512,1\nB02764,2\n" * 5000
    with TestClient(
        app.create_starlette_app(), headers={"Sec-Fetch-Site": "same-origin"}
    ) as client:
        client.get("/")
        (main_view,) = views
        assert isinstance(main_view.upload.renderer, WebRenderer)
        response = client.post(
            f"/widget/{main_view.upload.renderer.widget_id}/file",
            files={"file": ("pickups.csv", dataset, "text/csv")},
        )
        assert "pickups.csv" in response.text
        for _ in range(600):  # the page's poller: it brings the job's result to the views
            client.get("/jobs")
            if main_view.table.row_count > 0:
                break
            time.sleep(0.05)
        assert main_view.table.row_count == 10000

        assert isinstance(main_view.table.renderer, WebRenderer)
        table_id = main_view.table.renderer.widget_id
        client.post(f"/widget/{table_id}", data={"event": "search", "search": "B02764"})
        assert main_view.table.row_count == 5000

        response = client.get(f"/widget/{table_id}/csv")
        assert "pickups-filtered.csv" in response.headers["content-disposition"]
        exported = response.text.splitlines()
        assert exported[:2] == ["base,count", "B02764,2"]
        assert len(exported) == 5001

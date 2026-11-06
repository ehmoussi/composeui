"""The data explorer example: a user's file uploaded, read, filtered and exported."""

from __future__ import annotations

import csv
import gzip
import threading
import time
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("narwhals")
pytest.importorskip("polars")
pytest.importorskip("starlette")
import polars as pl
from starlette.testclient import TestClient

from composeui.core.application import Application
from composeui.core.view import UploadedFile
from composeui.webcore.webapplication import WebApplication
from composeui.webcore.webrenderer import WebRenderer
from examples import dataexplorer
from examples.dataexplorer import DataExplorerMainView, csv_separator, size_text

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

    def wait_then_find(path: Path) -> str:
        assert release.wait(30)
        return csv_separator(path)

    monkeypatch.setattr(dataexplorer, "csv_separator", wait_then_find)
    main_view.upload.take_file(UploadedFile.of_path(second))

    assert main_view.table.export_filename == "first-filtered.csv"
    assert main_view.summary.size.value == size

    release.set()
    main_view.jobs.wait()
    assert main_view.table.export_filename == "second-filtered.csv"
    assert main_view.summary.rows.value == "5,000"


@pytest.mark.parametrize("separator", [",", ";", "\t", "|"])
def test_a_csv_file_shows_its_columns_whatever_its_separator(
    main_view: DataExplorerMainView, tmp_path: Path, separator: str
) -> None:
    path = tmp_path / "trips.csv"
    lines = [["base", "count", "note"], ["B02512", "1", "a, b"], ["B02764", "2", "c"]]
    with path.open("w", encoding="utf-8", newline="") as file:
        csv.writer(file, delimiter=separator).writerows(lines)

    _give(main_view, path)

    assert main_view.loader.error is None
    assert main_view.summary.columns.value == "3"
    assert main_view.table.row_count == 2


def test_a_separator_inside_quotes_on_the_first_line_doesn_t_count(tmp_path: Path) -> None:
    path = tmp_path / "trips.csv"
    path.write_text('"a,b,c,d";count\n"1,2,3,4";5\n', encoding="utf-8")

    assert csv_separator(path) == ";"


def test_a_crafted_csv_file_doesn_t_hold_up_the_server(tmp_path: Path) -> None:
    """`csv.Sniffer` took 18 s on this, with every other thread stopped."""
    path = tmp_path / "crafted.csv"
    path.write_text(',"' * 32768, encoding="utf-8")

    start = time.monotonic()
    csv_separator(path)

    assert time.monotonic() - start < 2


@pytest.mark.parametrize(
    "start",
    [gzip.compress(b"a,b\n1,2\n"), b"\x28\xb5\x2f\xfd rest", b"\x78\x9c rest"],
    ids=["gzip", "zstd", "zlib"],
)
def test_a_compressed_csv_file_is_refused_before_it_is_unpacked(
    main_view: DataExplorerMainView, tmp_path: Path, start: bytes
) -> None:
    path = tmp_path / "small.csv"
    path.write_bytes(start)

    _give(main_view, path)

    assert main_view.status.text == "Can't read the file: a compressed file isn't accepted"
    assert not main_view.table.is_visible


def test_a_csv_file_of_one_column_reads_as_one_column(
    main_view: DataExplorerMainView, tmp_path: Path
) -> None:
    path = tmp_path / "names.csv"
    path.write_text("name\nAda\nGrace\n", encoding="utf-8")

    _give(main_view, path)

    assert main_view.summary.columns.value == "1"
    assert main_view.table.row_count == 2


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

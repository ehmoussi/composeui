"""Explore a CSV or Parquet file of the user's: upload it, filter its rows, export them."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

import polars as pl

from composeui.core.application import run
from composeui.core.dashboard import DashboardView
from composeui.core.dataframesource import DataFrameSource
from composeui.core.reactivity import reactive
from composeui.core.view import (
    FileUploadView,
    HorizontalView,
    LabelView,
    MetricView,
    SourceTableView,
    UploadedFile,
    child,
    define_view,
)

if TYPE_CHECKING:
    from composeui.core.jobs import Job


#: the separators that a CSV file can use, the first winning a tie, and the longest first line
#: read to find it. Not `csv.Sniffer`: on a crafted file, it stops every session for seconds
SEPARATORS = ",;\t|"
MAX_HEADER_LENGTH = 64 * 1024
#: how a compressed file starts, which Polars would unpack: gzip, zstd and zlib. A small file can
#: unpack to more than the server's memory, whatever `max_upload_size` says
COMPRESSED_STARTS = (
    b"\x1f\x8b",
    b"\x28\xb5\x2f\xfd",
    b"\x78\x01",
    b"\x78\x5e",
    b"\x78\x9c",
    b"\x78\xda",
)


def csv_separator(path: Path) -> str:
    """Find the separator of a CSV file: the most frequent on its first line, outside quotes."""
    with path.open(encoding="utf-8", errors="replace", newline="") as file:
        header = file.readline(MAX_HEADER_LENGTH)
    counts = dict.fromkeys(SEPARATORS, 0)
    is_quoted = False
    for character in header:
        if character == '"':
            is_quoted = not is_quoted
        elif character in counts and not is_quoted:
            counts[character] += 1
    return max(SEPARATORS, key=lambda separator: counts[separator])


def check_not_compressed(path: Path) -> None:
    with path.open("rb") as file:
        start = file.read(4)
    if start.startswith(COMPRESSED_STARTS):
        msg = "a compressed file isn't accepted"
        raise ValueError(msg)


class Table(NamedTuple):
    """A file's rows, with the file they came from: a newer one may be on its way."""

    frame: pl.DataFrame
    file: UploadedFile


def read_table(_job: Job[Table, int], file: UploadedFile) -> Table:
    path = file.path
    if path.suffix.lower() == ".parquet":
        return Table(pl.read_parquet(path), file)
    check_not_compressed(path)
    return Table(pl.read_csv(path, separator=csv_separator(path)), file)


def size_text(size: int) -> str:
    return f"{size / 1024:.1f} KiB" if size < 1024**2 else f"{size / 1024**2:.1f} MiB"


@define_view
class Summary(HorizontalView):
    rows: MetricView = child(MetricView, label="Rows")
    columns: MetricView = child(MetricView, label="Columns")
    size: MetricView = child(MetricView, label="Size")


@define_view
class DataExplorerMainView(DashboardView):
    app_title = "Data explorer"
    # the frame stays in memory, and each session has its own: a public app sets this for its RAM
    max_upload_size = 50 * 1024 * 1024

    upload: FileUploadView = child(
        FileUploadView, extensions={"Data": (".csv", ".parquet")}, browse_text="Choose a data file"
    )
    status: LabelView = child(LabelView)
    summary: Summary = child(Summary, is_visible=False)
    table: SourceTableView = child(SourceTableView, is_visible=False)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        # a new file replaces the one being read, at once
        self.loader = self.jobs.task(read_table, debounce=0.0)
        self.upload.uploaded.connect(self._read)

    def _read(self, file: UploadedFile) -> None:
        self.loader.start_latest(file)

    @reactive
    def show_state(self) -> None:
        has_table = self.loader.has_result and self.loader.error is None
        self.summary.is_visible = has_table
        self.table.is_visible = has_table
        if self.loader.is_running:
            self.status.text = "Reading the file..."
        elif self.loader.error is not None:
            self.status.text = f"Can't read the file: {self.loader.error}"
        elif has_table:
            self.status.text = "Filter the rows, then export those shown as CSV."
        else:
            self.status.text = "Choose a CSV or Parquet file to explore."

    @reactive
    def show_table(self) -> None:
        table = self.loader.result
        if table is not None:
            frame, file = table
            self.summary.rows.value = f"{frame.height:,}"
            self.summary.columns.value = str(frame.width)
            self.summary.size.value = size_text(file.size)
            self.table.source = DataFrameSource(frame)
            self.table.filterable_columns = frame.columns
            self.table.export_filename = f"{Path(file.name).stem}-filtered.csv"


def main() -> None:
    run(DataExplorerMainView)


if __name__ == "__main__":
    main()

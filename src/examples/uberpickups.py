"""Explore Uber pickups in NYC, based on Streamlit's app tutorial."""

from __future__ import annotations

import contextlib
import gzip
import io
import logging
from datetime import datetime
from typing import TYPE_CHECKING
from urllib.request import urlopen

import attrs

from composeui.core.application import run
from composeui.core.sqlitemodel import CSVSqliteTable, SqliteModel, SqliteSource, csv_field, table
from composeui.core.view import (
    ChartKind,
    ChartView,
    CheckBoxView,
    DataTableView,
    LabelView,
    MainView,
    PageView,
    PageWidth,
    Series,
    SourceColumn,
    child,
    define_view,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from composeui.core.jobs import Job

COLUMNS = (
    SourceColumn("date_time", "Date/Time", datetime),
    SourceColumn("lat", "Latitude", float),
    SourceColumn("lon", "Longitude", float),
    SourceColumn("base", "Base"),
)
logger = logging.getLogger("COMPOSEUI")


@attrs.define
class UberPickup:
    date_time: datetime = csv_field("Date/Time", date_format="%m/%d/%Y %H:%M:%S")
    lat: float = csv_field(
        "Lat", validator=attrs.validators.and_(attrs.validators.ge(-90), attrs.validators.le(90))
    )
    lon: float = csv_field(
        "Lon", validator=attrs.validators.and_(attrs.validators.ge(-180), attrs.validators.le(180))
    )
    base: str = csv_field("Base")


class UberPickupsTable(CSVSqliteTable, row_type=UberPickup, name="uber_data"):
    def pickups_by_hour(self) -> list[int]:
        with self.connection() as db:
            cursor = db.execute("""--sql
            SELECT
                CAST(strftime('%H', date_time) AS INTEGER) AS hour,
                COUNT(*) AS pickups
            FROM uber_data
            GROUP BY hour
            ORDER BY hour
            """)
            rows = cursor.fetchall()
            pickups = [0] * 24
            for hour, count in rows:
                if hour is not None:
                    pickups[hour] = count
            return pickups

    def fill_from_url(self, url: str, *, nb_rows: int | None = 10_000) -> Generator[int]:
        """Fill the table with Uber data from the given url."""
        with (
            urlopen(url) as response,  # noqa: S310 (the example supplies its fixed data URL)
            gzip.GzipFile(fileobj=response, mode="rb") as gz,
            io.TextIOWrapper(gz, encoding="utf-8", newline="") as text,
            contextlib.closing(self.fill(text, limit=nb_rows)) as batches,
        ):
            for nb_read in batches:
                logger.info("Read %s rows from CSV", nb_read)
                yield nb_read


class UberPickupsModel(SqliteModel):
    uber_data = table(UberPickupsTable)


DATA_URL: str = "https://s3-us-west-2.amazonaws.com/streamlit-demo-data/uber-raw-data-sep14.csv.gz"


@define_view
class UberPickupsPageView(PageView):
    width = PageWidth.WIDE

    data_load_state: LabelView = child(LabelView, text="Loading data...")
    show_raw_data: CheckBoxView = child(CheckBoxView, text="Show raw data", is_checked=False)
    data_load_status: LabelView = child(
        LabelView, text="Start reading rows from CSV", is_visible=True
    )
    table: DataTableView = child(
        DataTableView,
        is_visible=False,
        filterable_columns=[column.name for column in COLUMNS],
        export_filename="uber-raw-data-sep14.csv",
    )
    pickups_chart: ChartView = child(
        ChartView,
        is_visible=False,
        title="Number of pickups by hour",
        kind=ChartKind.BAR,
        x_title="Hour of day",
        y_title="Number of pickups",
        categories=[f"{hour:02d}:00" for hour in range(24)],
        height=400,
    )

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.table.source = None
        self.show_raw_data.toggled.connect(self._display_table)

    def _display_table(self, is_checked: bool) -> None:
        is_data_available = self.table.source is not None
        self.table.is_visible = is_data_available and is_checked
        self.pickups_chart.is_visible = is_data_available and not is_checked

    def fill(self, job: Job[list[int], int], model: UberPickupsModel, url: str) -> list[int]:
        if self._has_data(model):
            return model.uber_data.pickups_by_hour()
        with contextlib.closing(model.uber_data.fill_from_url(url, nb_rows=None)) as batches:
            for nb_read in batches:
                if job.is_canceled:
                    return []
                job.report_progress(nb_read)
        return model.uber_data.pickups_by_hour()

    def _has_data(self, model: UberPickupsModel) -> bool:
        return bool(model.uber_data.fetch_column("SELECT EXISTS(SELECT 1 FROM uber_data)")[0])

    def start_reading_load_status(self) -> None:
        self.data_load_state.text = "Loading data..."
        self.data_load_status.text = "Loading rows from SQLite or CSV"
        self.data_load_status.is_visible = True
        self.table.source = None
        self._display_table(self.show_raw_data.is_checked)

    def finish_reading_load_status(self) -> None:
        self.data_load_state.text = "Done! (using SQLite)"
        self.data_load_status.is_visible = False
        self._display_table(self.show_raw_data.is_checked)

    def update_load_status(self, nb_read: int) -> None:
        self.data_load_status.text = f"Read {nb_read:,} rows from CSV"


@define_view
class UberPickupsMainView(MainView):
    app_title = "Uber pickups in NYC"
    extension = ".streamlit"
    page: UberPickupsPageView = child(UberPickupsPageView)

    def connect_model(self, model: UberPickupsModel) -> None:
        model.uber_data.changed.connect(self._start_loading)
        self._start_loading(model)

    def _start_loading(self, model: UberPickupsModel) -> None:
        if self.jobs.is_running:
            return
        self.page.start_reading_load_status()
        job = self.jobs.start(self.page.fill, model, DATA_URL)
        job.progress.connect(self.page.update_load_status)
        job.finished.connect(self._finish_filling)
        job.failed.connect(self._fail_filling)

    def _fail_filling(self, error: Exception) -> None:
        self.page.data_load_state.text = "Failed to load data"
        self.page.data_load_status.is_visible = False
        self.status_bar.show_message(self.tr("Failed to read the CSV: {error}").format(error=error))

    def _finish_filling(self, pickups_by_hour: list[int], model: UberPickupsModel) -> None:
        self.page.table.source = SqliteSource(
            model.uber_data, "SELECT rowid AS id, * FROM uber_data", id_column="id", columns=COLUMNS
        )
        self.page.pickups_chart.series = [
            Series(name="Pickups", x=list(range(24)), y=pickups_by_hour)
        ]
        self.page.finish_reading_load_status()


if __name__ == "__main__":
    run(
        UberPickupsMainView,
        build_model=UberPickupsModel,
        setup_model=UberPickupsMainView.connect_model,
    )

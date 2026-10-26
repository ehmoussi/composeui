"""Explore Uber pickups in NYC, based on Streamlit's app tutorial."""

from __future__ import annotations

import contextlib
from datetime import datetime
from typing import TYPE_CHECKING

import attrs

from composeui.core.application import run
from composeui.core.reactivity import reactive
from composeui.core.sqlitemodel import CSVSqliteTable, SqliteModel, csv_field, table
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
    child,
    define_view,
)

if TYPE_CHECKING:
    from composeui.core.jobs import Job


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
    def has_data(self) -> bool:
        with self.connection() as db:
            return db.execute("SELECT 1 FROM uber_data LIMIT 1").fetchone() is not None

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


class UberPickupsModel(SqliteModel):
    uber_data = table(UberPickupsTable)

    def load_pickups(self, job: Job[list[int], int], url: str) -> list[int]:
        if not self.uber_data.has_data():
            with contextlib.closing(self.uber_data.fill_from_url(url)) as batches:
                for nb_read in batches:
                    if job.is_canceled:
                        return []
                    job.report_progress(nb_read)
        return self.uber_data.pickups_by_hour()


DATA_URL: str = "https://s3-us-west-2.amazonaws.com/streamlit-demo-data/uber-raw-data-sep14.csv.gz"


@define_view
class UberPickupsPageView(PageView):
    width = PageWidth.WIDE

    data_load_state: LabelView = child(LabelView, text="Loading data...")
    show_raw_data: CheckBoxView = child(CheckBoxView, text="Show raw data", is_checked=False)
    data_load_status: LabelView = child(
        LabelView, text="Start reading rows from CSV", is_visible=False
    )
    table: DataTableView = child(DataTableView, is_visible=False)
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


@define_view
class UberPickupsMainView(MainView):
    app_title = "Uber pickups in NYC"
    extension = ".streamlit"
    page: UberPickupsPageView = child(UberPickupsPageView)

    def connect_model(self, model: UberPickupsModel) -> None:
        self.page.table.source = model.uber_data.source()
        self.loader = self.jobs.task(model.load_pickups)
        self.loader.changed.connect(self._show_outcome)
        self.activate_reactions()
        model.uber_data.changed.connect(self._start_loading, now=True)

    def _start_loading(self) -> None:
        if not self.loader.is_running:
            self.loader.start(DATA_URL)

    @reactive
    def _show_loading(self) -> None:
        page, loader = self.page, self.loader
        page.data_load_status.is_visible = loader.is_running
        page.pickups_chart.is_visible = loader.has_result
        page.table.is_visible = loader.has_result and page.show_raw_data.is_checked
        if loader.is_running:
            page.data_load_status.text = (
                "Loading rows from SQLite or CSV"
                if loader.progress is None
                else f"Read {loader.progress:,} rows from CSV"
            )

    def _show_outcome(self) -> None:
        page, loader = self.page, self.loader
        if loader.result is not None:
            page.pickups_chart.series = [Series(name="Pickups", x=list(range(24)), y=loader.result)]
            page.data_load_state.text = "Done! (using SQLite)"
        else:
            page.data_load_state.text = "Loading data..."
            if loader.error is not None:
                page.data_load_state.text = "Failed to load data"
                self.status_bar.show_message(
                    self.tr("Failed to read the CSV: {error}").format(error=loader.error)
                )


if __name__ == "__main__":
    run(
        UberPickupsMainView,
        build_model=UberPickupsModel,
        setup_model=UberPickupsMainView.connect_model,
    )

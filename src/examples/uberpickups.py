"""Explore NYC pickups with hourly counts and a sampled map, based on Streamlit's tutorial."""

from __future__ import annotations

import contextlib
from datetime import datetime
from types import MappingProxyType
from typing import TYPE_CHECKING

import attrs

from composeui.core.application import run
from composeui.core.dashboard import DashboardView, bar_chart
from composeui.core.reactivity import reactive
from composeui.core.sqlitemodel import (
    CSVSqliteTable,
    SqliteModel,
    SqliteSource,
    csv_field,
    define_csv_row,
    table,
)
from composeui.core.view import (
    ChartView,
    CheckBoxView,
    LabelRowSliderView,
    LabelView,
    MapPoint,
    MapView,
    ReferenceLine,
    Series,
    SidebarView,
    SourceTableView,
    child,
    define_view,
)

if TYPE_CHECKING:
    import sqlite3

    from composeui.core.jobs import Job


@define_csv_row
class UberPickup:
    date_time: datetime = csv_field(name="Date/Time", date_format="%m/%d/%Y %H:%M:%S")
    lat: float = csv_field(
        name="Lat",
        validator=attrs.validators.and_(attrs.validators.ge(-90), attrs.validators.le(90)),
    )
    lon: float = csv_field(
        name="Lon",
        validator=attrs.validators.and_(attrs.validators.ge(-180), attrs.validators.le(180)),
    )
    base: str = csv_field(name="Base")


class UberPickupsTable(CSVSqliteTable, row_type=UberPickup, name="uber_data"):
    # the queries below filter on this same expression: without it, each reads every row
    indexes = """--sql
    CREATE INDEX uber_data_hour ON uber_data(CAST(strftime('%H', date_time) AS INTEGER));
    """

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

    def source_at(self, at_hour: int) -> SqliteSource:
        """Get a source of the rows picked up during the hour `at_hour`."""
        # a source's query takes no parameter: the hour goes in it as an int
        hour = f"CAST(strftime('%H', date_time) AS INTEGER) = {int(at_hour)}"
        query = f"SELECT rowid AS rowid, * FROM uber_data WHERE {hour}"  # noqa: S608 (an int)
        return SqliteSource(self, query, id_column="rowid", columns=self.source().columns)

    def pickup_points(self, at_hour: int) -> list[MapPoint]:
        with self.connection() as db:
            count = db.execute(
                """--sql
                SELECT COUNT(*) FROM uber_data
                WHERE CAST(strftime('%H', date_time) AS INTEGER) = :at_hour
                """,
                {"at_hour": at_hour},
            ).fetchone()[0]
            stride = max(1, (count + 9999) // 10000)
            rows = db.execute(
                """--sql
                SELECT lat, lon
                FROM uber_data
                WHERE (rowid - 1) % :stride = 0
                    AND CAST(strftime('%H', date_time) AS INTEGER) = :at_hour
                    AND lat BETWEEN -85.05112878 AND 85.05112878
                    AND lon BETWEEN -180 AND 180 ORDER BY rowid LIMIT 10000
                """,
                {"stride": stride, "at_hour": at_hour},
            )
            return [MapPoint(latitude=lat, longitude=lon) for lat, lon in rows]


def _index_hours(db: sqlite3.Connection) -> None:
    db.execute(UberPickupsTable.indexes)


class UberPickupsModel(SqliteModel):
    schema_version = 2
    migrations = MappingProxyType({1: _index_hours})

    uber_data = table(UberPickupsTable)

    def load_pickups(self, job: Job[list[int], int], url: str) -> list[int]:
        """Read the rows, unless the table has them already; get the pickups by hour."""
        if not self.uber_data.has_data():
            with contextlib.closing(self.uber_data.fill_from_url(url)) as batches:
                for nb_read in batches:
                    if job.is_canceled:
                        return []
                    job.report_progress(nb_read)
        return self.uber_data.pickups_by_hour()

    def load_points(self, _job: Job[list[MapPoint]], at_hour: int) -> list[MapPoint]:
        return self.uber_data.pickup_points(at_hour)


DATA_URL: str = "https://s3-us-west-2.amazonaws.com/streamlit-demo-data/uber-raw-data-sep14.csv.gz"
HOURS = [f"{hour:02d}:00" for hour in range(24)]


@define_view
class PickupFilters(SidebarView):
    show_raw_data: CheckBoxView = child(CheckBoxView, text="Show raw data")
    hour: LabelRowSliderView = child(LabelRowSliderView, label="Hour", maximum=23, value=11)


@define_view
class UberPickupsMainView(DashboardView):
    app_title = "Uber pickups in NYC"
    # a study keeps the rows read, so that opening it downloads none
    has_file_menu = True
    extension = ".streamlit"

    filters: PickupFilters = child(PickupFilters, title="Filters")
    status: LabelView = child(LabelView)
    # the user filters the hour's rows further, e.g. by base
    table: SourceTableView = child(
        SourceTableView, filterable_columns=["date_time", "lat", "lon", "base"]
    )
    pickups_chart: ChartView = bar_chart(
        "Number of pickups by hour",
        HOURS,
        x_title="Hour of day",
        y_title="Number of pickups",
        height=400,
    )
    pickups_map: MapView = child(MapView, title="Pickup locations (up to 10,000 sampled pickups)")

    def connect_model(self, model: UberPickupsModel) -> None:
        self.model = model
        self.loader = self.jobs.task(model.load_pickups)
        self.points = self.jobs.task(model.load_points)
        self.loader.show_state(
            self.status,
            views=[self.pickups_chart, self.pickups_map],
            loading_text="Loading rows from SQLite or CSV",
            progress_text="Read {progress:,} rows from CSV",
            failed_text="Failed to read the CSV: {error}",
        )
        self.filters.show_raw_data.shows(self.table)
        # New and Open replace the rows: read them again
        model.uber_data.changed.connect(self._start_loading, now=True)

    def _start_loading(self) -> None:
        if not self.loader.is_running:
            self.loader.start(DATA_URL)

    @reactive
    def show_pickups(self) -> None:
        self.pickups_chart.series = [Series.bars("Pickups", self.loader.result or [])]

    @reactive
    def show_hour(self) -> None:
        # the hour picked filters the table and the map, and stands out on the chart
        hour = self.filters.hour.value
        self.table.source = self.model.uber_data.source_at(hour)
        self.pickups_chart.reference_lines = [ReferenceLine(hour, HOURS[hour], vertical=True)]
        if self.loader.has_result:
            # a query per hour picked: the latest one shows, however long the previous ones take
            self.points.start_latest(hour)

    @reactive
    def show_points(self) -> None:
        self.pickups_map.points = self.points.result or []


def main() -> None:
    run(
        UberPickupsMainView,
        build_model=UberPickupsModel,
        setup_model=UberPickupsMainView.connect_model,
    )


if __name__ == "__main__":
    main()

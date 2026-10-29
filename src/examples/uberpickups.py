"""Explore NYC pickups with hourly counts and a sampled map, based on Streamlit's tutorial."""

from __future__ import annotations

import contextlib
from datetime import datetime
from typing import TYPE_CHECKING

import attrs

from composeui.core.application import run
from composeui.core.dashboard import DashboardView, bar_chart
from composeui.core.sqlitemodel import CSVSqliteTable, SqliteModel, csv_field, define_csv_row, table
from composeui.core.view import (
    ChartView,
    CheckBoxView,
    LabelRowSliderView,
    LabelView,
    MapPoint,
    MapView,
    Series,
    SidebarView,
    SourceTableView,
    child,
    define_view,
)

if TYPE_CHECKING:
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


@attrs.frozen(kw_only=True)
class PickupData:
    hours: list[int]
    points: list[MapPoint]


class UberPickupsModel(SqliteModel):
    uber_data = table(UberPickupsTable)

    def load_pickups(self, job: Job[PickupData, int], url: str, at_hour: int) -> PickupData:
        if not self.uber_data.has_data():
            with contextlib.closing(self.uber_data.fill_from_url(url)) as batches:
                for nb_read in batches:
                    if job.is_canceled:
                        return PickupData(hours=[], points=[])
                    job.report_progress(nb_read)
        return PickupData(
            hours=self.uber_data.pickups_by_hour(),
            points=self.uber_data.pickup_points(at_hour),
        )


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
    table: SourceTableView = child(SourceTableView)
    pickups_chart: ChartView = bar_chart(
        "Number of pickups by hour",
        HOURS,
        x_title="Hour of day",
        y_title="Number of pickups",
        height=400,
    )
    pickups_map: MapView = child(MapView, title="Pickup locations (up to 10,000 sampled pickups)")

    def connect_model(self, model: UberPickupsModel) -> None:
        self.table.source = model.uber_data.source()
        self.loader = self.jobs.task(model.load_pickups)
        self.loader.show_state(
            self.status,
            views=[self.pickups_chart, self.pickups_map],
            loading_text="Loading rows from SQLite or CSV",
            progress_text="Read {progress:,} rows from CSV",
            failed_text="Failed to read the CSV: {error}",
        )
        self.filters.show_raw_data.shows(self.table)
        self.loader.finished.connect(self._show_pickups)
        self.filters.hour.value_changed.connect(self._show_map)
        # New and Open replace the rows: read them again
        model.uber_data.changed.connect(self._start_loading, now=True)

    def _start_loading(self) -> None:
        if not self.loader.is_running:
            self.loader.start(DATA_URL, self.filters.hour.value)

    def _show_pickups(self, result: PickupData) -> None:
        self.pickups_chart.series = [Series.bars("Pickups", result.hours)]
        self.pickups_map.points = result.points

    def _show_map(self, hour: int, model: UberPickupsModel) -> None:
        self.pickups_map.points = model.uber_data.pickup_points(hour)


def main() -> None:
    run(
        UberPickupsMainView,
        build_model=UberPickupsModel,
        setup_model=UberPickupsMainView.connect_model,
    )


if __name__ == "__main__":
    main()

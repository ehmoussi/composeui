"""Explore NYC pickups with hourly counts and a sampled map, based on Streamlit's tutorial."""

from __future__ import annotations

import contextlib
from datetime import datetime
from typing import TYPE_CHECKING

import attrs

from composeui.core.application import run
from composeui.core.sqlitemodel import CSVSqliteTable, SqliteModel, csv_field, table
from composeui.core.view import (
    ChartKind,
    ChartView,
    CheckBoxView,
    DataTableView,
    LabelView,
    MainView,
    MapPoint,
    MapView,
    PageWidth,
    Series,
    SliderView,
    VerticalView,
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


@define_view
class UberPickupsDataView(VerticalView):
    table: DataTableView = child(DataTableView, is_visible=False)
    pickups_chart: ChartView = child(
        ChartView,
        title="Number of pickups by hour",
        kind=ChartKind.BAR,
        x_title="Hour of day",
        y_title="Number of pickups",
        categories=[f"{hour:02d}:00" for hour in range(24)],
        height=400,
    )
    slider_hours: SliderView = child(SliderView, minimum=0, maximum=23, step=1, value=11)
    pickups_map: MapView = child(
        MapView,
        title="Pickup locations (up to 10,000 sampled pickups)",
    )

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.slider_hours.value_changed.connect(self._update_map)

    def _update_map(self, value: int, model: UberPickupsModel) -> None:
        self.pickups_map.points = model.uber_data.pickup_points(value)


@define_view
class UberPickupsMainView(MainView):
    app_title = "Uber pickups in NYC"
    extension = ".streamlit"
    width = PageWidth.WIDE

    data_load_state: LabelView = child(LabelView, text="Loading data...")
    show_raw_data: CheckBoxView = child(CheckBoxView, text="Show raw data", is_checked=False)
    data_load_status: LabelView = child(
        LabelView, text="Start reading rows from CSV", is_visible=False
    )
    data: UberPickupsDataView = child(UberPickupsDataView, is_visible=False)

    def connect_model(self, model: UberPickupsModel) -> None:
        self.data.table.source = model.uber_data.source()
        self.loader = self.jobs.task(model.load_pickups)
        self.loader.changed.connect(self._show_loading)
        self.show_raw_data.toggled.connect(self._show_raw_data)
        model.uber_data.changed.connect(self._start_loading, now=True)

    def _start_loading(self) -> None:
        if not self.loader.is_running:
            self.loader.start(DATA_URL, self.data.slider_hours.value)

    def _show_raw_data(self) -> None:
        self.data.table.is_visible = self.show_raw_data.is_checked

    def _show_loading(self) -> None:
        loader = self.loader
        self.data_load_status.is_visible = loader.is_running
        self.data.table.is_visible = self.show_raw_data.is_checked
        self.data.is_visible = loader.has_result
        if loader.result is not None:
            self.data.pickups_chart.series = [
                Series(name="Pickups", x=list(range(24)), y=loader.result.hours)
            ]
            self.data.pickups_map.points = loader.result.points
            self.data_load_state.text = "Done! (using SQLite)"
        else:
            self.data_load_state.text = "Loading data..."
            if loader.error is not None:
                self.data_load_state.text = "Failed to load data"
                self.status_bar.show_message(
                    self.tr("Failed to read the CSV: {error}").format(error=loader.error)
                )
            elif loader.is_running:
                self.data_load_status.text = (
                    "Loading rows from SQLite or CSV"
                    if loader.progress is None
                    else f"Read {loader.progress:,} rows from CSV"
                )


def main() -> None:
    run(
        UberPickupsMainView,
        build_model=UberPickupsModel,
        setup_model=UberPickupsMainView.connect_model,
    )


if __name__ == "__main__":
    main()

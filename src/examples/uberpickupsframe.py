"""Explore NYC pickups as `uberpickups`, the rows in a Polars frame instead of SQLite."""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

from composeui.core.application import run
from composeui.core.dashboard import DashboardView, bar_chart
from composeui.core.dataframesource import DataFrameSource, points_of
from composeui.core.model import Model
from composeui.core.view import (
    ChartView,
    FormView,
    LabelRowSliderView,
    LabelView,
    MapPoint,
    MapView,
    RowCheckBoxView,
    Series,
    SidebarView,
    SourceTableView,
    child,
    define_view,
)

if TYPE_CHECKING:
    from composeui.core.jobs import Job


def read_pickups(_job: Job[pl.DataFrame, int], url: str) -> pl.DataFrame:
    return pl.read_csv(url).with_columns(pl.col("Date/Time").str.to_datetime("%m/%d/%Y %H:%M:%S"))


def pickups_by_hour(frame: pl.DataFrame) -> list[int]:
    counts = dict(frame.get_column("Date/Time").dt.hour().drop_nulls().value_counts().iter_rows())
    return [counts.get(hour, 0) for hour in range(24)]


def pickup_points(frame: pl.DataFrame, at_hour: int) -> list[MapPoint]:
    at = frame.filter(pl.col("Date/Time").dt.hour() == at_hour)
    # at most 10,000 pickups, spread over the hour
    return points_of(at.gather_every(max(1, (at.height + 9999) // 10000)), "Lat", "Lon")


class UberPickupsModel(Model):
    def __init__(self) -> None:
        #: the pickups, once read; set on the main thread
        self.frame = pl.DataFrame()


DATA_URL: str = "https://s3-us-west-2.amazonaws.com/streamlit-demo-data/uber-raw-data-sep14.csv.gz"
HOURS = [f"{hour:02d}:00" for hour in range(24)]


@define_view
class PickupFilters(FormView):
    show_raw_data: RowCheckBoxView = child(RowCheckBoxView, text="Show raw data")
    hour: LabelRowSliderView = child(LabelRowSliderView, label="Hour", maximum=23, value=11)


@define_view
class PickupSidebar(SidebarView):
    filters: PickupFilters = child(PickupFilters)


@define_view
class UberPickupsMainView(DashboardView):
    app_title = "Uber pickups in NYC"

    sidebar: PickupSidebar = child(PickupSidebar, title="Filters")
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

    def connect_model(self, _model: UberPickupsModel) -> None:
        self.loader = self.jobs.task(read_pickups)
        self.loader.show_state(
            self.status,
            views=[self.pickups_chart, self.pickups_map],
            failed_text="Failed to read the CSV: {error}",
        )
        self.sidebar.filters.show_raw_data.shows(self.table)
        self.loader.finished.connect(self._show_pickups)
        self.sidebar.filters.hour.value_changed.connect(self._show_map)
        self.loader.start(DATA_URL)

    def _show_pickups(self, frame: pl.DataFrame, model: UberPickupsModel) -> None:
        model.frame = frame
        self.table.source = DataFrameSource(frame)
        self.pickups_chart.series = [Series.bars("Pickups", pickups_by_hour(frame))]
        self._show_map(self.sidebar.filters.hour.value, model)

    def _show_map(self, hour: int, model: UberPickupsModel) -> None:
        self.pickups_map.points = pickup_points(model.frame, hour)


def main() -> None:
    run(
        UberPickupsMainView,
        build_model=UberPickupsModel,
        setup_model=UberPickupsMainView.connect_model,
    )


if __name__ == "__main__":
    main()

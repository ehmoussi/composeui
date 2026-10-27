"""Explore NYC pickups as `uberpickups`, the rows in a Polars frame instead of SQLite."""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

from composeui.core.application import run
from composeui.core.dataframesource import DataFrameSource
from composeui.core.model import Model
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


def read_pickups(url: str) -> pl.DataFrame:
    return pl.read_csv(url).with_columns(pl.col("Date/Time").str.to_datetime("%m/%d/%Y %H:%M:%S"))


def pickups_by_hour(frame: pl.DataFrame) -> list[int]:
    counts = frame.group_by(pl.col("Date/Time").dt.hour().alias("hour")).len()
    pickups = [0] * 24
    for hour, count in counts.iter_rows():
        if hour is not None:
            pickups[hour] = count
    return pickups


def pickup_points(frame: pl.DataFrame, at_hour: int) -> list[MapPoint]:
    at = frame.filter(pl.col("Date/Time").dt.hour() == at_hour)
    stride = max(1, (at.height + 9999) // 10000)
    rows = (
        at.gather_every(stride)
        .filter(pl.col("Lat").is_between(-85.05112878, 85.05112878))
        .filter(pl.col("Lon").is_between(-180, 180))
        .head(10000)
        .select("Lat", "Lon")
    )
    return [MapPoint(latitude=lat, longitude=lon) for lat, lon in rows.iter_rows()]


class UberPickupsFrameModel(Model):
    def __init__(self) -> None:
        #: the pickups, once read; set on the main thread
        self.frame = pl.DataFrame()

    def load_pickups(self, _job: Job[pl.DataFrame, int], url: str) -> pl.DataFrame:
        return read_pickups(url)


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

    def _update_map(self, value: int, model: UberPickupsFrameModel) -> None:
        self.pickups_map.points = pickup_points(model.frame, value)


@define_view
class UberPickupsFrameMainView(MainView):
    app_title = "Uber pickups in NYC"
    extension = ".streamlit"
    width = PageWidth.WIDE

    data_load_state: LabelView = child(LabelView, text="Loading data...")
    show_raw_data: CheckBoxView = child(CheckBoxView, text="Show raw data", is_checked=False)
    data_load_status: LabelView = child(LabelView, text="Reading the CSV", is_visible=False)
    data: UberPickupsDataView = child(UberPickupsDataView, is_visible=False)

    def connect_model(self, model: UberPickupsFrameModel) -> None:
        self.loader = self.jobs.task(model.load_pickups)
        self.loader.changed.connect(self._show_loading)
        self.show_raw_data.toggled.connect(self._show_raw_data)
        self.loader.start(DATA_URL)

    def _show_raw_data(self) -> None:
        self.data.table.is_visible = self.show_raw_data.is_checked

    def _show_loading(self, model: UberPickupsFrameModel) -> None:
        loader = self.loader
        self.data_load_status.is_visible = loader.is_running
        self.data.table.is_visible = self.show_raw_data.is_checked
        self.data.is_visible = loader.has_result
        if loader.result is not None:
            model.frame = loader.result
            self.data.table.source = DataFrameSource(model.frame)
            self.data.pickups_chart.series = [
                Series(name="Pickups", x=list(range(24)), y=pickups_by_hour(model.frame))
            ]
            self.data.pickups_map.points = pickup_points(model.frame, self.data.slider_hours.value)
            self.data_load_state.text = "Done! (using Polars)"
        else:
            self.data_load_state.text = "Loading data..."
            if loader.error is not None:
                self.data_load_state.text = "Failed to load data"
                self.status_bar.show_message(
                    self.tr("Failed to read the CSV: {error}").format(error=loader.error)
                )


def main() -> None:
    run(
        UberPickupsFrameMainView,
        build_model=UberPickupsFrameModel,
        setup_model=UberPickupsFrameMainView.connect_model,
    )


if __name__ == "__main__":
    main()

"""A first dashboard from a CSV: NYC pickups filtered by base, day and hour, then downloaded."""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

from composeui.core.application import run
from composeui.core.dashboard import (
    DashboardView,
    bar_chart,
    column_filter,
    counts_of,
    fill_filters,
    filtered,
    frame_content,
    show_frame,
)
from composeui.core.dataframesource import points_of
from composeui.core.reactivity import reactive
from composeui.core.view import (
    ChartView,
    DownloadView,
    HorizontalView,
    LabelRowDateRangeInputView,
    LabelRowMultiComboBoxView,
    LabelRowRangeSliderView,
    LabelView,
    MapView,
    MetricView,
    Series,
    SidebarView,
    SourceTableView,
    child,
    define_view,
)

if TYPE_CHECKING:
    from composeui.core.jobs import Job

DATA_URL = "https://s3-us-west-2.amazonaws.com/streamlit-demo-data/uber-raw-data-sep14.csv.gz"
HOURS = [f"{hour:02d}:00" for hour in range(24)]


def read_pickups(_job: Job[pl.DataFrame, int], url: str) -> pl.DataFrame:
    pickups = pl.read_csv(url).with_columns(
        pl.col("Date/Time").str.to_datetime("%m/%d/%Y %H:%M:%S")
    )
    return pickups.with_columns(Hour=pl.col("Date/Time").dt.hour())


@define_view
class Filters(SidebarView):
    bases: LabelRowMultiComboBoxView[str] = column_filter(
        LabelRowMultiComboBoxView[str], "Base", label="Bases"
    )
    days: LabelRowDateRangeInputView = column_filter(
        LabelRowDateRangeInputView, "Date/Time", label="Days"
    )
    hours: LabelRowRangeSliderView = column_filter(LabelRowRangeSliderView, "Hour", label="Hours")


@define_view
class Summary(HorizontalView):
    pickups: MetricView = child(MetricView, label="Pickups")
    bases: MetricView = child(MetricView, label="Bases")
    busiest_hour: MetricView = child(MetricView, label="Busiest hour")


@define_view
class UberDashboardMainView(DashboardView):
    app_title = "Uber pickups in NYC"

    filters: Filters = child(Filters, title="Filters")
    status: LabelView = child(LabelView)
    summary: Summary = child(Summary)
    by_hour: ChartView = bar_chart("Pickups by hour", HOURS, y_title="Pickups", height=300)
    pickups_map: MapView = child(MapView, title="Pickups (up to 10,000)")
    table: SourceTableView = child(SourceTableView)
    download_rows: DownloadView = child(
        DownloadView, text="Download these pickups", filename="pickups.csv"
    )

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.loader = self.jobs.task(read_pickups)
        self.loader.show_state(
            self.status,
            views=[self.summary, self.by_hour, self.pickups_map, self.table, self.download_rows],
        )
        self.loader.start(DATA_URL)

    @reactive
    def fill(self) -> None:
        pickups = self.loader.result
        if pickups is not None:
            fill_filters(self, pickups)

    @reactive
    def show_pickups(self) -> None:
        pickups = self.loader.result
        if pickups is None:
            return
        rows: pl.DataFrame = filtered(pickups, self)
        by_hour = counts_of(rows, "Hour", range(24))
        self.summary.pickups.value = f"{rows.height:,}"
        self.summary.bases.value = str(rows.get_column("Base").n_unique())
        self.summary.busiest_hour.value = HOURS[by_hour.index(max(by_hour))] if rows.height else "-"
        self.by_hour.series = [Series.bars("Pickups", by_hour)]
        self.pickups_map.points = points_of(
            rows.sample(min(rows.height, 10_000), seed=0), "Lat", "Lon"
        )
        show_frame(self.table, rows)
        self.download_rows.content = lambda: frame_content(rows)


def main() -> None:
    run(UberDashboardMainView)


if __name__ == "__main__":
    main()

"""Charts on the second of two pages, shared by the backend tests of `ChartView`."""

from __future__ import annotations

import datetime

from attrs import Factory

from composeui.core.view import (
    Axis,
    ChartView,
    LabelView,
    LineStyle,
    MainView,
    PageView,
    ReferenceLine,
    Router,
    Scale,
    Series,
    child,
    define_view,
)


@define_view
class NotesPage(PageView):
    route = "notes"
    page_title = "Notes"

    note: LabelView = child(LabelView, text="No chart here")


@define_view
class ChartPage(PageView):
    route = "chart"
    page_title = "Chart"

    chart: ChartView = child(
        ChartView,
        title="Pressure",
        x=Axis("Time", unit="s"),
        y=Axis(unit="kPa"),
        series=[Series.line("Inlet", [0, 1, 2, 3], [1, 3, 2, 4])],
        # off the grid's lines, the maximum and minimum past the data
        reference_lines=[
            ReferenceLine(4.6, "Max: 4.6", color="#d03030", style=LineStyle.SOLID),
            ReferenceLine(0.6, "Min: 0.6", color="#208040", style=LineStyle.DOTTED),
            ReferenceLine(2.3, "Now", vertical=True),
        ],
    )
    energy: ChartView = child(
        ChartView,
        title="Energy",
        y=Axis(unit="kWh"),
        categories=["Kitchen", "Bedroom", "Office"],
        series=[
            Series.bars("Heating", [120, 80, 95]),
            # no cooling in the bedroom
            Series.bars("Cooling", [30, 45], x=[0, 2]),
        ],
    )
    orders: ChartView = child(
        ChartView,
        title="Orders",
        y=Axis(unit="k"),
        categories=["Jan", "Feb", "Mar"],
        # a line over the bars of two series, on the same categories
        series=[
            Series.bars("Shop", [120, 140, 90]),
            Series.line("Target", [0, 1, 2], [100, 110, 125]),
            Series.bars("Online", [80, 95, 130]),
        ],
    )
    sales: ChartView = child(
        ChartView,
        title="Sales",
        x=Axis("Month"),
        y=Axis("Units"),
        y2=Axis("Revenue", unit="k€", scale=Scale.LOG),
        series=[
            Series.bars("Units", [120, 150, 90], x=[1, 2, 3]),
            # at the right, on a log axis: the 0 of month 3 leaves a gap, as it wouldn't at
            # the left
            Series.line("Revenue", [1, 2, 3], [3.2, 41, 0], on_y2=True),
        ],
        reference_lines=[
            ReferenceLine(100, "Minimum"),
            # past the revenue's power of 10: the right axis' range takes it in
            ReferenceLine(200, "Target", on_y2=True),
            # no value of the right axis, though one of the left
            ReferenceLine(0, "Break-even", on_y2=True),
        ],
    )
    load: ChartView = child(
        ChartView,
        title="Load",
        # the app's bounds: x from 0 to 10, y from 0 with its top fitting the data
        x=Axis("Time", unit="s", minimum=0, maximum=10),
        y=Axis("Load", unit="kN", minimum=0),
        series=[Series.line("Crane", [1, 5, 12], [3, 8, -2])],
        reference_lines=[
            # within the bounds, past the data: the top takes it in
            ReferenceLine(20, "Max: 20"),
            # past the x bounds: not drawn, nor labeled
            ReferenceLine(15, "Late", vertical=True),
        ],
    )
    visits: ChartView = child(
        ChartView,
        title="Visits",
        x=Axis("Day", scale=Scale.TIME),
        # a bar a day, given as dates; the line's ends as times
        series=[
            Series.bars(
                "Visits",
                [5, 8, 6, 9, 12, 4, 3],
                x=[datetime.date(2026, 11, day) for day in range(1, 8)],
            ),
            Series.line(
                "Trend",
                [
                    datetime.datetime(2026, 11, 1, tzinfo=datetime.timezone.utc),
                    datetime.datetime(2026, 11, 7, tzinfo=datetime.timezone.utc),
                ],
                [6, 7],
            ),
        ],
        reference_lines=[
            ReferenceLine(
                datetime.datetime(2026, 11, 4, 12, tzinfo=datetime.timezone.utc),
                "Release",
                vertical=True,
            )
        ],
    )
    ages: ChartView = child(
        ChartView,
        title="Ages",
        x=Axis(unit="y", scale=Scale.LOG),
        # no categories: a bar at each x, whose axis then stays linear
        series=[Series.bars("People", [4, 6, 5], x=[10, 20, 40])],
    )
    decay: ChartView = child(
        ChartView,
        title="Decay",
        x=Axis(unit="s", scale=Scale.LOG),
        y=Axis(scale=Scale.LOG),
        # a log axis shows neither 0 nor -1
        series=[Series.line("Activity", [0, 1, 10, 100, 1000], [1, 1000, -1, 10, 1])],
    )
    jobs: ChartView = child(
        ChartView,
        title="Jobs",
        x=Axis(unit="h"),
        # each count held until the next change; the queue's from 1 h, on its own x
        series=[
            Series.line(
                "Running",
                [0, 2, 5, 6],
                [1, 3, 2, 4],
                color="#204080",
                step=True,
                fill=True,
                fill_color="#c0d0f0",
            ),
            Series.line("Queued", [1, 4], [0.5, 1], step=True),
        ],
    )


@define_view
class ChartRouter(Router):
    notes: NotesPage = Factory(NotesPage)
    chart: ChartPage = Factory(ChartPage)


@define_view
class ChartPagesMainView(MainView):
    app_title = "Charts"
    extension = ".charts"

    router: ChartRouter = Factory(ChartRouter)

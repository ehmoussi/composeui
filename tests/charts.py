"""Charts on the second of two pages, shared by the backend tests of `ChartView`."""

from __future__ import annotations

from attrs import Factory

from composeui.core.view import (
    ChartKind,
    ChartView,
    LabelView,
    LineStyle,
    MainView,
    PageView,
    ReferenceLine,
    Router,
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
        x_title="Time",
        x_unit="s",
        y_unit="kPa",
        series=[Series(name="Inlet", x=[0, 1, 2, 3], y=[1, 3, 2, 4])],
        # off the grid's lines, the maximum and minimum past the data
        reference_lines=[
            ReferenceLine(4.6, "Max: 4.6", color="#d03030", style=LineStyle.SOLID),
            ReferenceLine(0.6, "Min: 0.6", color="#208040", style=LineStyle.DOTTED),
            ReferenceLine(2.3, "Now", vertical=True),
        ],
    )
    energy: ChartView = child(
        ChartView,
        kind=ChartKind.BAR,
        title="Energy",
        y_unit="kWh",
        categories=["Kitchen", "Bedroom", "Office"],
        series=[
            Series(name="Heating", x=[0, 1, 2], y=[120, 80, 95]),
            # no cooling in the bedroom
            Series(name="Cooling", x=[0, 2], y=[30, 45]),
        ],
    )
    decay: ChartView = child(
        ChartView,
        title="Decay",
        x_unit="s",
        x_log=True,
        y_log=True,
        # a log axis shows neither 0 nor -1
        series=[Series(name="Activity", x=[0, 1, 10, 100, 1000], y=[1, 1000, -1, 10, 1])],
    )
    jobs: ChartView = child(
        ChartView,
        title="Jobs",
        x_unit="h",
        # each count held until the next change; the queue's from 1 h, on its own x
        series=[
            Series(name="Running", x=[0, 2, 5, 6], y=[1, 3, 2, 4], step=True, fill=True),
            Series(name="Queued", x=[1, 4], y=[0.5, 1], step=True),
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

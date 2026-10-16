"""A chart on the second of two pages, shared by the backend tests of `ChartView`."""

from attrs import Factory

from composeui.core.view import (
    ChartView,
    LabelView,
    MainView,
    PageView,
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

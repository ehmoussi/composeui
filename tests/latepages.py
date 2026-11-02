"""Pages and tabs holding tables and dialogs, for the tests of a page built once shown."""

from __future__ import annotations

from attrs import Factory

from composeui.core.view import (
    ContentDialogView,
    DialogView,
    FormView,
    InputView,
    LabelRowInputView,
    MainView,
    PageView,
    RecordTableView,
    Router,
    SourceTableView,
    TabPage,
    TabView,
    child,
    define_view,
)
from tests.tables import SORTED_COLUMNS, GatedSource, Room


@define_view
class StartPage(PageView):
    route = "start"
    page_title = "Start"

    name: InputView = Factory(InputView)


@define_view
class RoomsPage(PageView):
    route = "rooms"
    page_title = "Rooms"

    rooms: RecordTableView[Room] = child(RecordTableView[Room], columns=SORTED_COLUMNS)
    readings: SourceTableView = child(SourceTableView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.readings.source = GatedSource()


@define_view
class NameForm(FormView):
    name: LabelRowInputView = child(LabelRowInputView, label="Name")


@define_view
class SummaryTab(TabPage):
    name: InputView = Factory(InputView)


@define_view
class ToolsTab(TabPage):
    tool: DialogView = child(DialogView, title="Tool", text="Run the tool?")


@define_view
class DialogTabs(TabView):
    summary: SummaryTab = child(SummaryTab, title="Summary")
    tools: ToolsTab = child(ToolsTab, title="Tools")


@define_view
class DialogsPage(PageView):
    route = "dialogs"
    page_title = "Dialogs"

    confirm: DialogView = child(DialogView, title="Confirm", text="Sure?")
    rename: ContentDialogView[NameForm] = Factory(lambda: ContentDialogView(content=NameForm()))
    tabs: DialogTabs = Factory(DialogTabs)


@define_view
class LatePagesRouter(Router):
    start: StartPage = Factory(StartPage)
    rooms: RoomsPage = Factory(RoomsPage)
    dialogs: DialogsPage = Factory(DialogsPage)


@define_view
class LatePagesMainView(MainView):
    app_title = "Late pages"
    extension = ".late"

    router: LatePagesRouter = Factory(LatePagesRouter)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.status_bar.timeout = 0

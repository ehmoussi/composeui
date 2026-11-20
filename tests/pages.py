"""Pages under routers, shared by the core and backend tests of pages."""

from __future__ import annotations

from attrs import Factory

from composeui.core.view import (
    ButtonView,
    ExpanderView,
    InputView,
    LabelView,
    MainView,
    MarkdownView,
    PageView,
    PageWidth,
    ProgressBarView,
    Router,
    SidebarView,
    TabPage,
    TabView,
    VerticalView,
    child,
    define_view,
)


@define_view
class InputsPage(PageView):
    route = "inputs"
    page_title = "Inputs"

    name: InputView = Factory(InputView)
    submit: ButtonView = Factory(ButtonView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.submit.text = "Submit"


@define_view
class ResultsPage(PageView):
    route = "results"
    page_title = "Results"
    width = PageWidth.WIDE

    total: LabelView = Factory(LabelView)
    progress: ProgressBarView = Factory(ProgressBarView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.total.text = "Total: 0"


@define_view
class PagesRouter(Router):
    inputs: InputsPage = Factory(InputsPage)
    results: ResultsPage = Factory(ResultsPage)


@define_view
class PagesMainView(MainView):
    app_title = "Pages"
    extension = ".pages"

    router: PagesRouter = Factory(PagesRouter)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.router.inputs.submit.clicked.connect(self._submit)

    def _submit(self) -> None:
        self.router.results.total.text = f"Submitted: {self.router.inputs.name.text}"


@define_view
class WidePageMainView(MainView):
    """A wide page right in the window, with no router."""

    app_title = "Wide page"
    extension = ".wide"

    results: ResultsPage = Factory(ResultsPage)


@define_view
class NotesExpander(ExpanderView):
    notes: LabelView = child(LabelView, text="\n".join(f"Note {number}" for number in range(40)))


@define_view
class NotesPage(PageView):
    route = "notes"
    page_title = "Notes"

    #: taller than the window once expanded
    notes: NotesExpander = child(NotesExpander, title="Notes")


@define_view
class NotesRouter(Router):
    notes: NotesPage = Factory(NotesPage)


@define_view
class NotesMainView(MainView):
    """A page that gets taller than the window."""

    app_title = "Notes"
    extension = ".notes"

    router: NotesRouter = Factory(NotesRouter)


@define_view
class HeaderContext(VerticalView):
    project: LabelView = child(LabelView, text="Project: bridge")
    study: LabelView = child(LabelView, text="Study: load case 1")


@define_view
class PageHeader(VerticalView):
    title: LabelView = child(LabelView, text="Studies")
    #: a column in the column
    context: HeaderContext = Factory(HeaderContext)


@define_view
class HeaderPage(PageView):
    route = "header"
    page_title = "Header"

    #: much shorter than the window
    header: PageHeader = Factory(PageHeader)
    name: InputView = Factory(InputView)


@define_view
class HelpColumn(VerticalView):
    title: LabelView = child(LabelView, text="Help")
    #: scrolls within itself
    help: MarkdownView = child(MarkdownView, text="Every study of the project")


@define_view
class HelpPage(PageView):
    route = "help"
    page_title = "Help"

    help: HelpColumn = Factory(HelpColumn)


@define_view
class ColumnsRouter(Router):
    header: HeaderPage = Factory(HeaderPage)
    help: HelpPage = Factory(HelpPage)


@define_view
class ColumnsMainView(MainView):
    """Pages holding a column of views."""

    app_title = "Columns"
    extension = ".columns"

    router: ColumnsRouter = Factory(ColumnsRouter)


@define_view
class DocumentTab(TabPage):
    title_label: LabelView = child(LabelView, text="Help")
    #: scrolls within itself
    help: MarkdownView = child(MarkdownView, text="Every study of the project")


@define_view
class TallTab(TabPage):
    notes: LabelView = child(LabelView, text="\n".join(f"Note {number}" for number in range(30)))


@define_view
class DocumentTabs(TabView):
    document: DocumentTab = child(DocumentTab, title="Help")
    #: taller than the other tab: it leaves that one height to spare
    tall: TallTab = child(TallTab, title="Notes")


@define_view
class DocumentTabMainView(MainView):
    """A document in a tab, next to a taller tab."""

    app_title = "Tabs"
    extension = ".tabs"

    tabs: DocumentTabs = Factory(DocumentTabs)


@define_view
class DocumentSidebar(SidebarView):
    title_label: LabelView = child(LabelView, text="Help")
    #: scrolls within itself
    help: MarkdownView = child(MarkdownView, text="Every study of the project")


@define_view
class DocumentSidebarMainView(MainView):
    """A document in a sidebar."""

    app_title = "Sidebar"
    extension = ".sidebar"

    side: DocumentSidebar = child(DocumentSidebar, title="Help")
    name: InputView = Factory(InputView)

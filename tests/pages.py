"""Pages under routers, shared by the core and backend tests of pages."""

from __future__ import annotations

from attrs import Factory

from composeui.core.view import (
    ButtonView,
    ExpanderView,
    InputView,
    LabelView,
    MainView,
    PageView,
    PageWidth,
    ProgressBarView,
    Router,
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

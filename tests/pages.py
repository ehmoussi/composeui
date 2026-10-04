"""Two pages under a router, shared by the core and backend tests of pages."""

from attrs import Factory

from composeui.core.view import InputView, LabelView, MainView, PageView, Router, define_view


@define_view
class InputsPage(PageView):
    name: InputView = Factory(InputView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self._init_route("inputs")
        self.title = "Inputs"


@define_view
class ResultsPage(PageView):
    total: LabelView = Factory(LabelView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self._init_route("results")
        self.title = "Results"
        self.total.text = "Total: 0"


@define_view
class PagesRouter(Router):
    inputs: InputsPage = Factory(InputsPage)
    results: ResultsPage = Factory(ResultsPage)


@define_view
class PagesMainView(MainView):
    router: PagesRouter = Factory(PagesRouter)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self._init_app_info(title="Pages", extension=".pages")

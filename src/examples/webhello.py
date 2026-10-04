from composeui.core.view import MainView
from composeui.webcore.webapplication import WebApplication


class TestMainView(MainView):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self._init_app_info(title="Test", extension=".web")


def _build_main_view() -> TestMainView:
    main_view = TestMainView()
    main_view.status_bar.message = "test 2"
    return main_view


class TestApp(WebApplication[TestMainView]):
    def __init__(self) -> None:
        super().__init__(build_main_view=_build_main_view)


def main() -> None:
    app = TestApp()
    app.run()


if __name__ == "__main__":
    main()

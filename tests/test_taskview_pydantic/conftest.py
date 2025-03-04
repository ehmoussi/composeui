from examples.taskview.pydantic.app import ExampleMainView, PydanticTaskViewApp

import pytest


@pytest.fixture(scope="session")
def global_app() -> PydanticTaskViewApp:
    r"""Create model and view."""
    main_view = ExampleMainView()
    app = PydanticTaskViewApp(main_view)
    app.run()
    return app


@pytest.fixture()
def app(global_app: PydanticTaskViewApp) -> PydanticTaskViewApp:
    global_app.main_view.message_view.run = lambda: True  # type: ignore[method-assign]
    # back to the initial state of the app
    global_app.main_view.menu.file.new.triggered()
    return global_app

from examples.taskview.pydantic.app import IExampleMainView, PydanticTaskViewApp

import pytest


@pytest.fixture(scope="session")
def global_app() -> PydanticTaskViewApp:
    r"""Create model and view."""
    main_view = IExampleMainView()
    app = PydanticTaskViewApp(main_view)
    app.run()
    return app


@pytest.fixture()
def app(global_app: PydanticTaskViewApp) -> PydanticTaskViewApp:
    global_app.main_view.message_view.run = lambda: True  # type: ignore[method-assign]
    # back to the initial state of the model
    global_app.main_view.menu.file.new.triggered()
    # back to the initial state of the view
    global_app.initialize()
    return global_app

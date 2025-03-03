from examples.taskview.mashumaro.app import ExampleMainView, MashumaroTaskViewApp

import pytest


@pytest.fixture(scope="session")
def global_app() -> MashumaroTaskViewApp:
    r"""Create model and view."""
    main_view = ExampleMainView()
    app = MashumaroTaskViewApp(main_view)
    app.run()
    return app


@pytest.fixture()
def app(global_app: MashumaroTaskViewApp) -> MashumaroTaskViewApp:
    global_app.main_view.message_view.run = lambda: True  # type: ignore[method-assign]
    # back to the initial state of the app
    global_app.main_view.menu.file.new.triggered()
    return global_app

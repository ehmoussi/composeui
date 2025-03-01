from examples.simpletableview.app import SimpleTableViewApp
from examples.simpletableview.example import ExampleMainView

import pytest


@pytest.fixture(scope="session")
def global_app() -> SimpleTableViewApp:
    r"""Create model and view."""
    main_view = ExampleMainView()
    app = SimpleTableViewApp(main_view)
    app.run()
    return app


@pytest.fixture()
def app(global_app: SimpleTableViewApp) -> SimpleTableViewApp:
    global_app.model.is_debug = False
    global_app.main_view.message_view.run = lambda: True  # type: ignore[method-assign]
    # back to the initial state of the model
    global_app.main_view.menu.file.new.triggered()
    # back to the initial state of the view
    global_app.initialize()
    return global_app

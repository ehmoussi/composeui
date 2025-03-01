from examples.multipleviews.app import MultipleViewsApp
from examples.multipleviews.example import IExampleMainView

import pytest


@pytest.fixture(scope="session")
def global_app() -> MultipleViewsApp:
    r"""Create model and view."""
    main_view = IExampleMainView()
    app = MultipleViewsApp(main_view)
    app.run()
    return app


@pytest.fixture()
def app(global_app: MultipleViewsApp) -> MultipleViewsApp:
    global_app.main_view.message_view.run = lambda: True  # type: ignore[method-assign]
    # back to the initial state of the model
    global_app.main_view.menu.file.new.triggered()
    # back to the initial state of the view
    global_app.initialize()
    return global_app

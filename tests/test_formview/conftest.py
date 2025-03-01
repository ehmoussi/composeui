from examples.formview.app import FormViewApp
from examples.formview.example import ExampleMainView

import pytest


@pytest.fixture(scope="session")
def global_app() -> FormViewApp:
    r"""Create model and view."""
    main_view = ExampleMainView()
    app = FormViewApp(main_view)
    app.run()
    return app


@pytest.fixture()
def app(global_app: FormViewApp) -> FormViewApp:
    global_app.main_view.message_view.run = lambda: True  # type: ignore[method-assign]
    # back to the initial state of the model
    global_app.main_view.menu.file.new.triggered()
    # back to the initial state of the view
    global_app.initialize()
    return global_app

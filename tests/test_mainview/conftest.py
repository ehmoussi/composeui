from composeui.mainview.views.imainview import MainView
from examples.mainview.app import MainViewApp

import pytest


@pytest.fixture(scope="session")
def global_app() -> MainViewApp:
    r"""Create model and view."""
    main_view = MainView()
    app = MainViewApp(main_view)
    app.run()
    return app


@pytest.fixture()
def app(global_app: MainViewApp) -> MainViewApp:
    global_app.main_view.message_view.run = lambda: True  # type: ignore[method-assign]
    # back to the initial state of the model
    global_app.main_view.menu.file.new.triggered()
    # back to the initial state of the view
    global_app.initialize()
    return global_app

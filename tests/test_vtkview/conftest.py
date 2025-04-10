from examples.vtkview.app import VTKViewApp
from examples.vtkview.example import ExampleMainView

import pytest


@pytest.fixture(scope="session")
def global_app() -> VTKViewApp:
    r"""Create model and view."""
    main_view = ExampleMainView()
    app = VTKViewApp(main_view)
    app.run()
    return app


@pytest.fixture()
def app(global_app: VTKViewApp) -> VTKViewApp:
    global_app.model.is_debug = False
    global_app.main_view.message_view.run = lambda: True  # type: ignore[method-assign]
    # back to the initial state of the app
    global_app.main_view.menu.file.new.triggered()
    return global_app

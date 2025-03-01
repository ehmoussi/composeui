from examples.treeview.app import TreeViewApp
from examples.treeview.example import ExampleMainView

import pytest


@pytest.fixture(scope="session")
def global_app() -> TreeViewApp:
    r"""Create model and view."""
    main_view = ExampleMainView()
    app = TreeViewApp(main_view)
    app.run()
    return app


@pytest.fixture()
def app(global_app: TreeViewApp) -> TreeViewApp:
    global_app.main_view.message_view.run = lambda: True  # type: ignore[method-assign]
    # back to the initial state of the model
    global_app.main_view.menu.file.new.triggered()
    # back to the initial state of the view
    global_app.initialize()
    return global_app

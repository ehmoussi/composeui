import sys

if sys.version_info < (3, 7):  # noqa: UP036
    import os

    # can't move to 2.0 with python 3.6
    os.environ["SQLALCHEMY_SILENCE_UBER_WARNING"] = "1"

from examples.linkedtableview.sqlalchemy.app import LinkedTableViewApp
from examples.linkedtableview.sqlalchemy.example import IExampleMainView

import pytest


@pytest.fixture(scope="session")
def global_app() -> LinkedTableViewApp:
    r"""Create model and view."""
    main_view = IExampleMainView()
    app = LinkedTableViewApp(main_view)
    app.run()
    return app


@pytest.fixture()
def app(global_app: LinkedTableViewApp) -> LinkedTableViewApp:
    global_app.main_view.message_view.run = lambda: True  # type: ignore[method-assign]
    # back to the initial state of the model
    global_app.main_view.menu.file.new.triggered()
    # back to the initial state of the view
    global_app.initialize()
    return global_app

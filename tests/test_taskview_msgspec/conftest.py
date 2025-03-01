import pytest

import sys
from pathlib import Path


def pytest_ignore_collect(collection_path: Path) -> bool:
    """Skip collecting tests that require msgspec if python version < 3.8."""
    return "test_taskview_msgspec" in collection_path.parts and sys.version_info < (3, 8)


if not sys.version_info < (3, 8):
    from examples.taskview.msgspec.app import IExampleMainView, MsgspecTaskViewApp

    @pytest.fixture(scope="session")
    def global_app() -> MsgspecTaskViewApp:
        r"""Create model and view."""
        main_view = IExampleMainView()
        app = MsgspecTaskViewApp(main_view)
        app.run()
        return app

    @pytest.fixture()
    def app(
        global_app: MsgspecTaskViewApp,
    ) -> MsgspecTaskViewApp:
        global_app.main_view.message_view.run = lambda: True  # type: ignore[method-assign]
        # back to the initial state of the model
        global_app.main_view.menu.file.new.triggered()
        # back to the initial state of the view
        global_app.initialize()
        return global_app

import sys
from pathlib import Path


def is_salome_running() -> bool:
    salome_path = Path(sys.base_prefix)
    return salome_path.name == "Python" and "SALOME" in salome_path.parents[1].name.upper()


def pytest_ignore_collect(collection_path: Path) -> bool:
    """Skip collecting tests that require salome if salome is not running."""
    return "test_salomeview" in collection_path.parts and not is_salome_running()


if is_salome_running():
    from examples.salomeview.app import ExampleSalomeApp, Module1App, Module2App

    import pytest

    @pytest.fixture(scope="session")
    def global_app() -> ExampleSalomeApp:
        """Create the app."""
        app = ExampleSalomeApp(is_testing=True)
        app.run()
        return app

    @pytest.fixture()
    def app(global_app: ExampleSalomeApp) -> ExampleSalomeApp:
        for module in global_app.modules:
            assert isinstance(module, (Module1App, Module2App))
            module.main_view.message_view.run = lambda: True  # type: ignore[method-assign]
            # back to the initial state of the app
            module.main_view.menu.file.new.triggered()
            # back to the initial state of the view
            module.initialize()
        return global_app

from composeui import get_version
from composeui.apps.salomeapp import SalomeApp
from composeui.apps.salomemoduleapp import SalomeModuleApp
from composeui.model.basemodel import BaseModel
from composeui.store.salomehdfstore import SalomeHDFStore
from composeui.store.sqlitestore import SqliteStore
from examples.salomeview import module1, module2
from examples.salomeview.cubedefinition import (
    CubeQuery,
    connect_cube_definition,
    initialize_cube_definition,
)
from examples.salomeview.cubetable import connect_cube_table, initialize_cube_table
from examples.salomeview.module1 import Module1MainView
from examples.salomeview.module2 import Module2MainView

from pathlib import Path
from typing import Optional

_MODEL: Optional["Model"] = None


class Model(BaseModel):
    def __init__(self) -> None:
        self._data = SqliteStore()
        self._salome_store = SalomeHDFStore()
        super().__init__(
            "example",
            get_version("composeui"),
            self._data,
            self._salome_store,
        )
        self._data.add_tables(
            [
                Path(Path(__file__).parent, "db", "cube.sql"),
            ]
        )
        self._data.create_tables()
        self.cube_query = CubeQuery(self._data)


def create_model() -> Model:
    # This is an example on how to share a model between two modules.
    global _MODEL  # noqa: PLW0603
    if _MODEL is None:
        _MODEL = Model()
    return _MODEL


class Module1App(SalomeModuleApp[Module1MainView, Model]):

    def _create_model(self) -> None:
        self._model = create_model()

    def _create_main_view(self) -> None:
        if self.is_testing:
            self._main_view = Module1MainView(self.get_module_name())
        else:
            from examples.salomeview.qtmainview1 import QtModule1MainView

            self._main_view = QtModule1MainView(self.get_module_name())

    def get_module_name(self) -> str:
        return "Example"

    def initialize_app(self) -> None:
        self.main_view.extension_study = self.get_module_name().lower()
        self.main_view.title = self.get_module_name().title()
        module1.initialize_navigation(self.main_view.toolbar.navigation, self.main_view)
        initialize_cube_definition(self.main_view.left_dock.cube_definition, self.model)

    def connect_app(self) -> None:
        connect_cube_definition(self.main_view.left_dock.cube_definition)


class Module2App(SalomeModuleApp[Module2MainView, Model]):

    def _create_model(self) -> None:
        self._model = create_model()

    def _create_main_view(self) -> None:
        if self.is_testing:
            self._main_view = Module2MainView(self.get_module_name())
        else:
            from examples.salomeview.qtmainview2 import QtModule2MainView

            self._main_view = QtModule2MainView(self.get_module_name())

    def get_module_name(self) -> str:
        return "Example2"

    def initialize_app(self) -> None:
        self.main_view.extension_study = self.get_module_name().lower()
        self.main_view.title = self.get_module_name().title()
        module2.initialize_navigation(self.main_view.toolbar.navigation, self.main_view)
        initialize_cube_table(self.main_view.cube_table, self.main_view, self.model)

    def connect_app(self) -> None:
        connect_cube_table(self.main_view.cube_table)


class ExampleSalomeApp(SalomeApp):
    def __init__(self, is_testing: bool = False) -> None:
        super().__init__([Module1App(), Module2App()], is_testing)

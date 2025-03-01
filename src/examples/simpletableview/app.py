from composeui import get_version
from composeui.apps.qtbaseapp import QtBaseApp
from composeui.model.sqlitemodel import SqliteModel
from examples.simpletableview.example import ExampleMainView, initialize_navigation
from examples.simpletableview.points import initialize_points

from pathlib import Path


class Model(SqliteModel):
    def __init__(self) -> None:
        super().__init__("example", get_version("composeui"))
        self._data.add_tables([Path(Path(__file__).parent, "db", "points.sql")])
        self._data.create_tables()


class SimpleTableViewApp(QtBaseApp[ExampleMainView, Model]):
    def __init__(self, main_view: ExampleMainView) -> None:
        super().__init__(Model(), main_view)

    def initialize_app(self) -> None:
        initialize_navigation(self.main_view.toolbar.navigation, self.main_view)
        initialize_points(self.main_view.points_view, self.main_view, self.model)

    def connect_app(self) -> None: ...

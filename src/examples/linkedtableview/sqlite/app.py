from composeui import get_version
from composeui.apps.qtbaseapp import QtBaseApp
from composeui.model.sqlitemodel import SqliteModel
from examples.linkedtableview.sqlite.example import IExampleMainView, initialize_navigation
from examples.linkedtableview.sqlite.lines import LinesQuery, initialize_lines

from pathlib import Path


class Model(SqliteModel):
    def __init__(self) -> None:
        super().__init__("example", get_version("composeui"))
        self._data.add_tables([Path(Path(__file__).parent, "db", "line.sql")])
        self._data.create_tables()
        self.lines_query = LinesQuery(self._data)


class LinkedTableViewApp(QtBaseApp[IExampleMainView, Model]):
    def __init__(self, main_view: IExampleMainView) -> None:
        super().__init__(Model(), main_view)

    def initialize_app(self) -> None:
        initialize_navigation(self.main_view.toolbar.navigation, self.main_view)
        initialize_lines(self.main_view.lines, self.main_view, self.model)

    def connect_app(self) -> None: ...  # no connections

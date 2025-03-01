from composeui import get_version
from composeui.apps.qtbaseapp import QtBaseApp
from composeui.model.sqlitemodel import SqliteModel
from examples.tableview.example import IExampleMainView, initialize_navigation
from examples.tableview.points import PointsQuery, initialize_points

from pathlib import Path


class Model(SqliteModel):
    def __init__(self) -> None:
        super().__init__("example", get_version("composeui"))
        db_dir = Path(Path(__file__).parent, "db")
        self._data.add_tables([Path(db_dir, "points.sql")])
        self._data.create_tables()
        self.points_query = PointsQuery(self._data)


class TableViewApp(QtBaseApp[IExampleMainView, Model]):
    def __init__(self, main_view: IExampleMainView) -> None:
        super().__init__(Model(), main_view)

    def initialize_app(self) -> None:
        initialize_navigation(self.main_view.toolbar.navigation, self.main_view)
        initialize_points(self.main_view.points_view, self.main_view, self.model)

    def connect_app(self) -> None: ...  # no connections

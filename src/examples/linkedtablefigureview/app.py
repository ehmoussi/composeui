from composeui import get_version
from composeui.apps.qtbaseapp import QtBaseApp
from composeui.model.sqlitemodel import SqliteModel
from examples.linkedtablefigureview.example import (
    IExampleMainView,
    initialize_navigation,
    initialize_point,
)

from pathlib import Path


class Model(SqliteModel):
    def __init__(self) -> None:
        super().__init__("Example", get_version("composeui"), is_debug=False)
        db_dir = Path(Path(__file__).parent, "db")
        self.sqlite_store.add_tables(
            (Path(db_dir, "point.sql"),),
        )
        self.sqlite_store.create_tables()


class LinkedTableFigureViewApp(QtBaseApp[IExampleMainView, Model]):
    def __init__(self, main_view: IExampleMainView) -> None:
        super().__init__(Model(), main_view)

    def initialize_app(self) -> None:
        initialize_navigation(self.main_view.toolbar.navigation)
        initialize_point(self.main_view.points, self.model)

    def connect_app(self) -> None: ...

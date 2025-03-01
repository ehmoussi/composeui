from composeui import get_version
from composeui.apps.qtbaseapp import QtBaseApp
from composeui.model.sqlalchemymodel import SqlAlchemyModel
from examples.linkedtableview.sqlalchemy.example import ExampleMainView, initialize_navigation
from examples.linkedtableview.sqlalchemy.lines import LinesQuery, initialize_lines


class Model(SqlAlchemyModel):
    def __init__(self) -> None:
        super().__init__("example", get_version("composeui"))
        # TODO: Remove LinesQuery and use SQlAlchemy directly ?
        self.lines_query = LinesQuery(self._data)


class LinkedTableViewApp(QtBaseApp[ExampleMainView, Model]):
    def __init__(self, main_view: ExampleMainView) -> None:
        super().__init__(Model(), main_view)

    def initialize_app(self) -> None:
        initialize_navigation(self.main_view.toolbar.navigation, self.main_view)
        initialize_lines(self.main_view.lines, self.main_view, self.model)

    def connect_app(self) -> None: ...  # no connections

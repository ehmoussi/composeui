from composeui import get_version
from composeui.apps.qtbaseapp import QtBaseApp
from composeui.model.sqlitemodel import SqliteModel
from examples.formview import pipeapplyform, pipeform
from examples.formview.example import ExampleMainView, initialize_navigation

from pathlib import Path


class Model(SqliteModel):
    def __init__(self) -> None:
        super().__init__("example", get_version("composeui"))
        self._data.add_tables([Path(Path(__file__).parent, "db", "pipe.sql")])
        self._data.create_tables()
        self.pipe_query = pipeform.PipeQuery(self._data, p_id=1)
        self.apply_pipe_query = pipeform.PipeQuery(self._data, p_id=2)


class FormViewApp(QtBaseApp[ExampleMainView, Model]):
    def __init__(self, main_view: ExampleMainView) -> None:
        super().__init__(Model(), main_view)

    def initialize_app(self) -> None:
        initialize_navigation(self.main_view.toolbar.navigation, self.main_view, self.model)
        pipeform.initialize_pipe(
            self.main_view.pipe_view, self.main_view, self.model, is_visible=True
        )
        pipeapplyform.initialize_apply_pipe(self.main_view.apply_pipe_view, self.model)

    def connect_app(self) -> None: ...  # no connections

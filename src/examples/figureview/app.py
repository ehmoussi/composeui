from composeui import get_version
from composeui.apps.qtbaseapp import QtBaseApp
from composeui.model.basemodel import BaseModel
from examples.figureview.batman import connect_batman, initialize_batman
from examples.figureview.example import ExampleMainView


class FigureViewApp(QtBaseApp[ExampleMainView, BaseModel]):
    def __init__(self, main_view: ExampleMainView) -> None:
        super().__init__(BaseModel("example", get_version("composeui")), main_view)

    def initialize_app(self) -> None:
        initialize_batman(self.main_view.batman)

    def connect_app(self) -> None:
        connect_batman(self.main_view.batman)

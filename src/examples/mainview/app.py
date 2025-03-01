from composeui import get_version
from composeui.apps.qtbaseapp import QtBaseApp
from composeui.mainview.views.mainview import MainView
from composeui.model.basemodel import BaseModel


class MainViewApp(QtBaseApp[MainView, BaseModel]):
    def __init__(self, main_view: MainView) -> None:
        super().__init__(BaseModel("example", get_version("composeui")), main_view)

    def initialize_app(self) -> None:
        self.main_view.extension_study = "example"
        self.main_view.title = "Example"

    def connect_app(self) -> None: ...

from composeui.mainview.qt.qtmainmenu import QtMainMenu
from composeui.mainview.qt.qtmaintoolbar import QtMainToolBar
from composeui.mainview.qt.qtmainview import QtMainView
from composeui.mainview.views.mainmenu import MainMenu
from composeui.mainview.views.maintoolbar import MainToolBar
from composeui.mainview.views.mainview import MainView

from dataclasses import dataclass, field


@dataclass(eq=False)
class QtExampleMainMenu(QtMainMenu, MainMenu): ...


@dataclass(eq=False)
class QtExampleMainToolBar(QtMainToolBar, MainToolBar): ...


@dataclass(eq=False)
class ExampleMainView(QtMainView, MainView):
    menu: QtExampleMainMenu = field(init=False, repr=False)
    toolbar: QtExampleMainToolBar = field(init=False, repr=False)

    def __post_init__(self, with_app: bool) -> None:
        super().__post_init__(with_app)
        self.menu: MainMenu = QtExampleMainMenu(self.view)
        self.toolbar: MainToolBar = QtExampleMainToolBar(self.view)

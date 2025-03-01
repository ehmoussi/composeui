from composeui.mainview.interfaces.imainmenu import IMainMenu
from composeui.mainview.interfaces.imaintoolbar import IMainToolBar
from composeui.mainview.interfaces.imainview import IMainView
from composeui.mainview.qt.qtmainmenu import QtMainMenu
from composeui.mainview.qt.qtmaintoolbar import QtMainToolBar
from composeui.mainview.qt.qtmainview import QtMainView

from dataclasses import dataclass, field


@dataclass(eq=False)
class ExampleMainMenu(QtMainMenu, IMainMenu): ...


@dataclass(eq=False)
class ExampleToolBar(QtMainToolBar, IMainToolBar): ...


@dataclass(eq=False)
class ExampleMainView(QtMainView, IMainView):
    menu: ExampleMainMenu = field(init=False)
    toolbar: ExampleToolBar = field(init=False)

    def __post_init__(self, with_app: bool) -> None:
        super().__post_init__(with_app)
        self.menu: IMainMenu = ExampleMainMenu(self.view)
        self.toolbar: IMainToolBar = ExampleToolBar(self.view)

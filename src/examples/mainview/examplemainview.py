from composeui.mainview.interfaces.imainmenu import IMainMenu
from composeui.mainview.interfaces.imaintoolbar import IMainToolBar
from composeui.mainview.interfaces.imainview import IMainView
from composeui.mainview.qt.mainmenu import MainMenu
from composeui.mainview.qt.maintoolbar import MainToolBar
from composeui.mainview.qt.mainview import MainView

from dataclasses import dataclass, field


@dataclass(eq=False)
class ExampleMainMenu(MainMenu, IMainMenu): ...


@dataclass(eq=False)
class ExampleToolBar(MainToolBar, IMainToolBar): ...


@dataclass(eq=False)
class ExampleMainView(MainView, IMainView):
    menu: ExampleMainMenu = field(init=False)
    toolbar: ExampleToolBar = field(init=False)

    def __post_init__(self, with_app: bool) -> None:
        super().__post_init__(with_app)
        self.menu: IMainMenu = ExampleMainMenu(self.view)
        self.toolbar: IMainToolBar = ExampleToolBar(self.view)

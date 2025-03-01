from composeui.items.linkedtable.qt.linkedtableview import LinkedTableView
from composeui.mainview.interfaces.imainmenu import IMainMenu
from composeui.mainview.qt.mainmenu import MainMenu
from composeui.mainview.qt.maintoolbar import MainToolBar
from composeui.mainview.qt.mainview import MainView
from examples.linkedtableview.sqlalchemy.example import IExampleMainView, IExampleToolBar
from examples.linkedtableview.sqlalchemy.lines import LinesItems, PointsItems

from dataclasses import dataclass, field


@dataclass(eq=False)
class ExampleMainMenu(MainMenu, IMainMenu): ...


@dataclass(eq=False)
class ExampleToolBar(MainToolBar, IExampleToolBar): ...


@dataclass(eq=False)
class ExampleMainView(MainView, IExampleMainView):

    menu: ExampleMainMenu = field(init=False)
    toolbar: ExampleToolBar = field(init=False)
    lines: LinkedTableView[LinesItems, PointsItems] = field(init=False)

    def __post_init__(self, with_app: bool) -> None:
        super().__post_init__(with_app)
        self.menu = ExampleMainMenu(self.view)
        self.toolbar = ExampleToolBar(self.view)
        # views
        self.lines = LinkedTableView[LinesItems, PointsItems]()
        self.central_layout.addWidget(self.lines.view)

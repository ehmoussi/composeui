from composeui.items.table.qt.tableview import SimpleTableView
from composeui.mainview.interfaces.imainmenu import IMainMenu
from composeui.mainview.qt.mainmenu import MainMenu
from composeui.mainview.qt.maintoolbar import MainToolBar
from composeui.mainview.qt.mainview import MainView
from examples.simpletableview.app import Model
from examples.simpletableview.example import IExampleMainView, IExampleToolBar

from dataclasses import dataclass, field


@dataclass(eq=False)
class ExampleMainMenu(MainMenu, IMainMenu): ...


@dataclass(eq=False)
class ExampleToolBar(MainToolBar, IExampleToolBar): ...


@dataclass(eq=False)
class ExampleMainView(MainView, IExampleMainView):
    menu: ExampleMainMenu = field(init=False)
    toolbar: ExampleToolBar = field(init=False)
    points_view: SimpleTableView[Model] = field(init=False)

    def __post_init__(self, with_app: bool) -> None:
        super().__post_init__(with_app)
        self.menu = ExampleMainMenu(self.view)
        self.toolbar = ExampleToolBar(self.view)
        # points
        self.points_view = SimpleTableView[Model]()
        self.central_layout.addWidget(self.points_view.view)

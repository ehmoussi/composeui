from composeui.items.table.qt.qttableview import QtTableView
from composeui.mainview.interfaces.imainmenu import IMainMenu
from composeui.mainview.qt.qtmainmenu import QtMainMenu
from composeui.mainview.qt.qtmaintoolbar import QtMainToolBar
from composeui.mainview.qt.qtmainview import QtMainView
from examples.tableview.example import IExampleMainView, IExampleToolBar
from examples.tableview.points import PointsItems

from dataclasses import dataclass, field


@dataclass(eq=False)
class ExampleMainMenu(QtMainMenu, IMainMenu): ...


@dataclass(eq=False)
class ExampleToolBar(QtMainToolBar, IExampleToolBar): ...


@dataclass(eq=False)
class ExampleMainView(QtMainView, IExampleMainView):
    menu: ExampleMainMenu = field(init=False)
    toolbar: ExampleToolBar = field(init=False)
    points_view: QtTableView[PointsItems] = field(init=False)

    def __post_init__(self, with_app: bool) -> None:
        super().__post_init__(with_app)
        self.menu = ExampleMainMenu(self.view)
        self.toolbar = ExampleToolBar(self.view)
        # points
        self.points_view = QtTableView[PointsItems]()
        self.central_layout.addWidget(self.points_view.view)

from composeui.items.table.qt.qttableview import QtTableView
from composeui.mainview.interfaces.imainmenu import IMainMenu
from composeui.mainview.qt.qtmainmenu import QtMainMenu
from composeui.mainview.qt.qtmaintoolbar import QtMainToolBar
from composeui.mainview.qt.qtmainview import QtMainView
from examples.tableview.example import IExampleMainToolBar, IExampleMainView
from examples.tableview.points import PointsItems

from dataclasses import dataclass, field


@dataclass(eq=False)
class QtExampleMainMenu(QtMainMenu, IMainMenu): ...


@dataclass(eq=False)
class QtExampleMainToolBar(QtMainToolBar, IExampleMainToolBar): ...


@dataclass(eq=False)
class QtExampleMainView(QtMainView, IExampleMainView):
    menu: QtExampleMainMenu = field(init=False)
    toolbar: QtExampleMainToolBar = field(init=False)
    points_view: QtTableView[PointsItems] = field(init=False)

    def __post_init__(self, with_app: bool) -> None:
        super().__post_init__(with_app)
        self.menu = QtExampleMainMenu(self.view)
        self.toolbar = QtExampleMainToolBar(self.view)
        # points
        self.points_view = QtTableView[PointsItems]()
        self.central_layout.addWidget(self.points_view.view)

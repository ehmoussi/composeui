from composeui.items.linkedtable.qt.qtlinkedtableview import QtLinkedTableView
from composeui.mainview.interfaces.imainmenu import IMainMenu
from composeui.mainview.qt.qtmainmenu import QtMainMenu
from composeui.mainview.qt.qtmaintoolbar import QtMainToolBar
from composeui.mainview.qt.qtmainview import QtMainView
from examples.linkedtableview.sqlite.example import IExampleMainToolBar, IExampleMainView
from examples.linkedtableview.sqlite.lines import LinesItems, PointsItems

from dataclasses import dataclass, field


@dataclass(eq=False)
class QtExampleMainMenu(QtMainMenu, IMainMenu): ...


@dataclass(eq=False)
class QtExampleMainToolBar(QtMainToolBar, IExampleMainToolBar): ...


@dataclass(eq=False)
class QtExampleMainView(QtMainView, IExampleMainView):
    menu: IMainMenu = field(init=False)
    toolbar: IExampleMainToolBar = field(init=False)
    lines: QtLinkedTableView[LinesItems, PointsItems] = field(init=False)

    def __post_init__(self, with_app: bool) -> None:
        super().__post_init__(with_app)
        self.menu = QtExampleMainMenu(self.view)
        self.toolbar = QtExampleMainToolBar(self.view)
        # points
        self.lines = QtLinkedTableView[LinesItems, PointsItems]()
        self.central_layout.addWidget(self.lines.view)

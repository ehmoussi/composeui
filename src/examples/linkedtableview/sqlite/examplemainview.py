from composeui.items.linkedtable.qt.qtlinkedtableview import QtLinkedTableView
from composeui.mainview.interfaces.imainmenu import IMainMenu
from composeui.mainview.qt.qtmainmenu import QtMainMenu
from composeui.mainview.qt.qtmaintoolbar import QtMainToolBar
from composeui.mainview.qt.qtmainview import QtMainView
from examples.linkedtableview.sqlite.example import IExampleMainView, IExampleToolBar
from examples.linkedtableview.sqlite.lines import LinesItems, PointsItems

from dataclasses import dataclass, field


@dataclass(eq=False)
class ExampleMainMenu(QtMainMenu, IMainMenu): ...


@dataclass(eq=False)
class ExampleToolBar(QtMainToolBar, IExampleToolBar): ...


@dataclass(eq=False)
class ExampleMainView(QtMainView, IExampleMainView):
    menu: IMainMenu = field(init=False)
    toolbar: IExampleToolBar = field(init=False)
    lines: QtLinkedTableView[LinesItems, PointsItems] = field(init=False)

    def __post_init__(self, with_app: bool) -> None:
        super().__post_init__(with_app)
        self.menu = ExampleMainMenu(self.view)
        self.toolbar = ExampleToolBar(self.view)
        # points
        self.lines = QtLinkedTableView[LinesItems, PointsItems]()
        self.central_layout.addWidget(self.lines.view)

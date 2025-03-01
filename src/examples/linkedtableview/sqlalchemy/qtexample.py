from composeui.items.linkedtable.qt.qtlinkedtableview import QtLinkedTableView
from composeui.mainview.qt.qtmainmenu import QtMainMenu
from composeui.mainview.qt.qtmaintoolbar import QtMainToolBar
from composeui.mainview.qt.qtmainview import QtMainView
from composeui.mainview.views.mainmenu import MainMenu
from examples.linkedtableview.sqlalchemy.example import ExampleMainToolBar, ExampleMainView
from examples.linkedtableview.sqlalchemy.lines import LinesItems, PointsItems

from dataclasses import dataclass, field


@dataclass(eq=False)
class QtExampleMainMenu(QtMainMenu, MainMenu): ...


@dataclass(eq=False)
class QtExampleMainToolBar(QtMainToolBar, ExampleMainToolBar): ...


@dataclass(eq=False)
class QtExampleMainView(QtMainView, ExampleMainView):

    menu: QtExampleMainMenu = field(init=False, repr=False)
    toolbar: QtExampleMainToolBar = field(init=False, repr=False)
    lines: QtLinkedTableView[LinesItems, PointsItems] = field(init=False, repr=False)

    def __post_init__(self, with_app: bool) -> None:
        super().__post_init__(with_app)
        self.menu = QtExampleMainMenu(self.view)
        self.toolbar = QtExampleMainToolBar(self.view)
        # views
        self.lines = QtLinkedTableView[LinesItems, PointsItems]()
        self.central_layout.addWidget(self.lines.view)

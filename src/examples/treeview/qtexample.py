from composeui.items.tree.qt.qttreeview import TreeGroupView
from composeui.mainview.interfaces.imainmenu import IMainMenu
from composeui.mainview.qt.qtmainmenu import QtMainMenu
from composeui.mainview.qt.qtmaintoolbar import QtMainToolBar
from composeui.mainview.qt.qtmainview import QtMainView
from examples.treeview.example import IExampleMainToolBar, IExampleMainView
from examples.treeview.lines import LinesItems

from dataclasses import dataclass, field


@dataclass(eq=False)
class QtExampleMainMenu(QtMainMenu, IMainMenu): ...


@dataclass(eq=False)
class QtExampleMainToolBar(QtMainToolBar, IExampleMainToolBar): ...


@dataclass(eq=False)
class ExampleMainView(QtMainView, IExampleMainView):
    menu: QtExampleMainMenu = field(init=False)
    toolbar: QtExampleMainToolBar = field(init=False)

    lines_view: TreeGroupView[LinesItems] = field(init=False)

    def __post_init__(self, with_app: bool) -> None:
        super().__post_init__(with_app)
        self.menu = QtExampleMainMenu(self.view)
        self.toolbar = QtExampleMainToolBar(self.view)
        # points
        self.lines_view = TreeGroupView[LinesItems]()
        self.central_layout.addWidget(self.lines_view.view)

from composeui.items.tree.qt.qttreeview import QtTreeGroupView
from composeui.mainview.qt.qtmainmenu import QtMainMenu
from composeui.mainview.qt.qtmaintoolbar import QtMainToolBar
from composeui.mainview.qt.qtmainview import QtMainView
from composeui.mainview.views.mainmenu import MainMenu
from examples.treeview.example import ExampleMainToolBar, ExampleMainView
from examples.treeview.lines import LinesItems

from dataclasses import dataclass, field


@dataclass(eq=False)
class QtExampleMainMenu(QtMainMenu, MainMenu): ...


@dataclass(eq=False)
class QtExampleMainToolBar(QtMainToolBar, ExampleMainToolBar): ...


@dataclass(eq=False)
class QtExampleMainView(QtMainView, ExampleMainView):
    menu: QtExampleMainMenu = field(init=False)
    toolbar: QtExampleMainToolBar = field(init=False)

    lines_view: QtTreeGroupView[LinesItems] = field(init=False)

    def __post_init__(self, with_app: bool) -> None:
        super().__post_init__(with_app)
        self.menu = QtExampleMainMenu(self.view)
        self.toolbar = QtExampleMainToolBar(self.view)
        # points
        self.lines_view = QtTreeGroupView[LinesItems]()
        self.central_layout.addWidget(self.lines_view.view)

from composeui.mainview.interfaces.imainmenu import IMainMenu
from composeui.mainview.qt.qtdockview import QtDockView
from composeui.mainview.qt.qtmainmenu import QtMainMenu
from composeui.mainview.qt.qtmaintoolbar import QtMainToolBar
from composeui.mainview.qt.qtmainview import QtMainView
from examples.multipleviews.component1.qtview1 import LeftView1, QtView1
from examples.multipleviews.component2.qtview2 import RightView2, View2
from examples.multipleviews.component3.qtview3 import View3
from examples.multipleviews.example import (
    IExampleMainToolBar,
    IExampleMainView,
    ILeftExampleDockView,
    IRightExampleDockView,
)

from qtpy.QtCore import Qt

from dataclasses import dataclass, field


@dataclass(eq=False)
class QtExampleMainMenu(QtMainMenu, IMainMenu): ...


@dataclass(eq=False)
class QtExampleMainToolBar(QtMainToolBar, IExampleMainToolBar): ...


@dataclass(eq=False)
class QtLeftExampleDockView(QtDockView, ILeftExampleDockView):
    view_1: LeftView1 = field(init=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.view_1 = LeftView1()
        self.central_layout.addWidget(self.view_1.view)


@dataclass(eq=False)
class QtRightExampleDockView(QtDockView, IRightExampleDockView):
    view_2: RightView2 = field(init=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.view_2 = RightView2()
        self.central_layout.addWidget(self.view_2.view)


@dataclass(eq=False)
class QtExampleMainView(QtMainView, IExampleMainView):
    menu: QtExampleMainMenu = field(init=False)
    toolbar: QtExampleMainToolBar = field(init=False)

    left_dock: QtLeftExampleDockView = field(init=False)
    right_dock: QtRightExampleDockView = field(init=False)
    view_1: QtView1 = field(init=False)
    view_2: View2 = field(init=False)
    view_3: View3 = field(init=False)

    def __post_init__(self, with_app: bool) -> None:
        super().__post_init__(with_app)
        self.menu = QtExampleMainMenu(self.view)
        self.toolbar = QtExampleMainToolBar(self.view)
        # dockviews
        self.left_dock = QtLeftExampleDockView()
        self.view.addDockWidget(Qt.LeftDockWidgetArea, self.left_dock.view)
        self.right_dock = QtRightExampleDockView()
        self.view.addDockWidget(Qt.RightDockWidgetArea, self.right_dock.view)
        # views
        self.view_1 = QtView1()
        self.central_layout.addWidget(self.view_1.view)
        self.view_2 = View2()
        self.central_layout.addWidget(self.view_2.view)
        self.view_3 = View3()
        self.central_layout.addWidget(self.view_3.view)

from composeui.mainview.qt.qtdockview import QtDockView
from composeui.mainview.qt.qtmainmenu import QtMainMenu
from composeui.mainview.qt.qtmaintoolbar import QtMainToolBar
from composeui.mainview.qt.qtmainview import QtMainView
from composeui.mainview.views.mainmenu import MainMenu
from examples.multipleviews.component1.qtview1 import QtLeftView1, QtView1
from examples.multipleviews.component2.qtview2 import QtRightView2, QtView2
from examples.multipleviews.component3.qtview3 import QtView3
from examples.multipleviews.example import (
    ExampleMainToolBar,
    ExampleMainView,
    LeftExampleDockView,
    RightExampleDockView,
)

from qtpy.QtCore import Qt

from dataclasses import dataclass, field


@dataclass(eq=False)
class QtExampleMainMenu(QtMainMenu, MainMenu): ...


@dataclass(eq=False)
class QtExampleMainToolBar(QtMainToolBar, ExampleMainToolBar): ...


@dataclass(eq=False)
class QtLeftExampleDockView(QtDockView, LeftExampleDockView):
    view_1: QtLeftView1 = field(init=False, repr=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.view_1 = QtLeftView1()
        self.central_layout.addWidget(self.view_1.view)


@dataclass(eq=False)
class QtRightExampleDockView(QtDockView, RightExampleDockView):
    view_2: QtRightView2 = field(init=False, repr=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.view_2 = QtRightView2()
        self.central_layout.addWidget(self.view_2.view)


@dataclass(eq=False)
class QtExampleMainView(QtMainView, ExampleMainView):
    menu: QtExampleMainMenu = field(init=False, repr=False)
    toolbar: QtExampleMainToolBar = field(init=False, repr=False)

    left_dock: QtLeftExampleDockView = field(init=False, repr=False)
    right_dock: QtRightExampleDockView = field(init=False, repr=False)
    view_1: QtView1 = field(init=False, repr=False)
    view_2: QtView2 = field(init=False, repr=False)
    view_3: QtView3 = field(init=False, repr=False)

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
        self.view_2 = QtView2()
        self.central_layout.addWidget(self.view_2.view)
        self.view_3 = QtView3()
        self.central_layout.addWidget(self.view_3.view)

from composeui.mainview.interfaces.imainmenu import IMainMenu
from composeui.mainview.qt.dockview import DockView
from composeui.mainview.qt.mainmenu import MainMenu
from composeui.mainview.qt.maintoolbar import MainToolBar
from composeui.mainview.qt.mainview import MainView
from examples.multipleviews.component1.view1 import LeftView1, View1
from examples.multipleviews.component2.view2 import RightView2, View2
from examples.multipleviews.component3.view3 import View3
from examples.multipleviews.example import (
    IExampleMainToolBar,
    IExampleMainView,
    ILeftExampleDockView,
    IRightExampleDockView,
)

from qtpy.QtCore import Qt

from dataclasses import dataclass, field


@dataclass(eq=False)
class ExampleMainMenu(MainMenu, IMainMenu): ...


@dataclass(eq=False)
class ExampleToolBar(MainToolBar, IExampleMainToolBar): ...


@dataclass(eq=False)
class LeftExampleDockView(DockView, ILeftExampleDockView):
    view_1: LeftView1 = field(init=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.view_1 = LeftView1()
        self.central_layout.addWidget(self.view_1.view)


@dataclass(eq=False)
class RightExampleDockView(DockView, IRightExampleDockView):
    view_2: RightView2 = field(init=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.view_2 = RightView2()
        self.central_layout.addWidget(self.view_2.view)


@dataclass(eq=False)
class ExampleMainView(MainView, IExampleMainView):
    menu: ExampleMainMenu = field(init=False)
    toolbar: ExampleToolBar = field(init=False)

    left_dock: LeftExampleDockView = field(init=False)
    right_dock: RightExampleDockView = field(init=False)
    view_1: View1 = field(init=False)
    view_2: View2 = field(init=False)
    view_3: View3 = field(init=False)

    def __post_init__(self, with_app: bool) -> None:
        super().__post_init__(with_app)
        self.menu = ExampleMainMenu(self.view)
        self.toolbar = ExampleToolBar(self.view)
        # dockviews
        self.left_dock = LeftExampleDockView()
        self.view.addDockWidget(Qt.LeftDockWidgetArea, self.left_dock.view)
        self.right_dock = RightExampleDockView()
        self.view.addDockWidget(Qt.RightDockWidgetArea, self.right_dock.view)
        # views
        self.view_1 = View1()
        self.central_layout.addWidget(self.view_1.view)
        self.view_2 = View2()
        self.central_layout.addWidget(self.view_2.view)
        self.view_3 = View3()
        self.central_layout.addWidget(self.view_3.view)

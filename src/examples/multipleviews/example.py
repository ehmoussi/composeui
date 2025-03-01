from composeui.core.views.actionview import ActionView
from composeui.mainview.views.dockview import DockView
from composeui.mainview.views.maintoolbar import MainToolBar
from composeui.mainview.views.mainview import MainView
from composeui.mainview.views.toolbar import CheckableToolBar
from examples.multipleviews.component1.view1 import LeftView1, View1
from examples.multipleviews.component2.view2 import RightView2, View2
from examples.multipleviews.component3.view3 import View3

from dataclasses import dataclass, field


@dataclass(eq=False)
class NavigationToolBar(CheckableToolBar):
    view_1: ActionView = field(init=False, repr=False, default_factory=ActionView)
    view_2: ActionView = field(init=False, repr=False, default_factory=ActionView)
    view_3: ActionView = field(init=False, repr=False, default_factory=ActionView)


@dataclass(eq=False)
class ExampleMainToolBar(MainToolBar):
    navigation: NavigationToolBar = field(
        init=False, repr=False, default_factory=NavigationToolBar
    )


@dataclass(eq=False)
class LeftExampleDockView(DockView):
    view_1: LeftView1 = field(init=False, repr=False, default_factory=LeftView1)


@dataclass(eq=False)
class RightExampleDockView(DockView):
    view_2: RightView2 = field(init=False, repr=False, default_factory=RightView2)


@dataclass(eq=False)
class ExampleMainView(MainView):
    toolbar: ExampleMainToolBar = field(
        init=False, repr=False, default_factory=ExampleMainToolBar
    )
    left_dock: LeftExampleDockView = field(
        init=False, repr=False, default_factory=LeftExampleDockView
    )
    right_dock: RightExampleDockView = field(
        init=False, repr=False, default_factory=RightExampleDockView
    )
    view_1: View1 = field(init=False, repr=False, default_factory=View1)
    view_2: View2 = field(init=False, repr=False, default_factory=View2)
    view_3: View3 = field(init=False, repr=False, default_factory=View3)


def initialize_dockviews(main_view: ExampleMainView) -> None:
    # left dock
    main_view.left_dock.is_visible = True
    # right dock
    main_view.right_dock.is_visible = False

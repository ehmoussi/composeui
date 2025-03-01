from composeui.core.interfaces.iactionview import IActionView
from composeui.mainview.interfaces.idockview import IDockView
from composeui.mainview.interfaces.imaintoolbar import IMainToolBar
from composeui.mainview.interfaces.imainview import IMainView
from composeui.mainview.interfaces.itoolbar import ICheckableToolBar
from examples.multipleviews.component1.view1 import ILeftView1, IView1
from examples.multipleviews.component2.view2 import IRightView2, IView2
from examples.multipleviews.component3.view3 import IView3

from dataclasses import dataclass, field


@dataclass(eq=False)
class INavigationToolBar(ICheckableToolBar):
    view_1: IActionView = field(init=False, default_factory=IActionView)
    view_2: IActionView = field(init=False, default_factory=IActionView)
    view_3: IActionView = field(init=False, default_factory=IActionView)


@dataclass(eq=False)
class IExampleMainToolBar(IMainToolBar):
    navigation: INavigationToolBar = field(init=False, default_factory=INavigationToolBar)


@dataclass(eq=False)
class ILeftExampleDockView(IDockView):
    view_1: ILeftView1 = field(init=False, default_factory=ILeftView1)


@dataclass(eq=False)
class IRightExampleDockView(IDockView):
    view_2: IRightView2 = field(init=False, default_factory=IRightView2)


@dataclass(eq=False)
class IExampleMainView(IMainView):
    toolbar: IExampleMainToolBar = field(init=False, default_factory=IExampleMainToolBar)
    left_dock: ILeftExampleDockView = field(init=False, default_factory=ILeftExampleDockView)
    right_dock: IRightExampleDockView = field(
        init=False, default_factory=IRightExampleDockView
    )
    view_1: IView1 = field(init=False, default_factory=IView1)
    view_2: IView2 = field(init=False, default_factory=IView2)
    view_3: IView3 = field(init=False, default_factory=IView3)


def initialize_dockviews(main_view: IExampleMainView) -> None:
    # left dock
    main_view.left_dock.is_visible = True
    # right dock
    main_view.right_dock.is_visible = False

from composeui.core.interfaces.iactionview import IActionView
from composeui.mainview.interfaces.imaintoolbar import IMainToolBar
from composeui.mainview.interfaces.imainview import IMainView
from composeui.mainview.interfaces.itoolbar import ICheckableToolBar
from examples.tableview.points import IPointsView

from dataclasses import dataclass, field


@dataclass(eq=False)
class INavigationToolBar(ICheckableToolBar):
    points: IActionView = field(init=False, default_factory=IActionView)


@dataclass(eq=False)
class IExampleToolBar(IMainToolBar):
    navigation: INavigationToolBar = field(init=False, default_factory=INavigationToolBar)


@dataclass(eq=False)
class IExampleMainView(IMainView):
    toolbar: IExampleToolBar = field(init=False, default_factory=IExampleToolBar)
    points_view: IPointsView = field(init=False, default_factory=IPointsView)


def initialize_navigation(view: INavigationToolBar, main_view: "IExampleMainView") -> None:
    view.points.is_checked = True
    view.points.text = "Points"
    view.points.visible_views = [main_view.points_view]

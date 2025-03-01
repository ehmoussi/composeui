from composeui.core.views.actionview import ActionView
from composeui.mainview.views.maintoolbar import MainToolBar
from composeui.mainview.views.mainview import MainView
from composeui.mainview.views.toolbar import CheckableToolBar
from examples.tableview.points import IPointsView

from dataclasses import dataclass, field


@dataclass(eq=False)
class NavigationToolBar(CheckableToolBar):
    points: ActionView = field(init=False, default_factory=ActionView)


@dataclass(eq=False)
class ExampleMainToolBar(MainToolBar):
    navigation: NavigationToolBar = field(init=False, default_factory=NavigationToolBar)


@dataclass(eq=False)
class ExampleMainView(MainView):
    toolbar: ExampleMainToolBar = field(init=False, default_factory=ExampleMainToolBar)
    points_view: IPointsView = field(init=False, default_factory=IPointsView)


def initialize_navigation(view: NavigationToolBar, main_view: "ExampleMainView") -> None:
    view.points.is_checked = True
    view.points.text = "Points"
    view.points.visible_views = [main_view.points_view]

from composeui.core.views.iactionview import ActionView
from composeui.items.simpletable.isimpletableview import SimpleTableView
from composeui.mainview.views.imaintoolbar import MainToolBar
from composeui.mainview.views.imainview import MainView
from composeui.mainview.views.itoolbar import CheckableToolBar

from typing_extensions import TypeAlias

import typing
from dataclasses import dataclass, field

if typing.TYPE_CHECKING:
    from examples.simpletableview.app import Model


@dataclass(eq=False)
class NavigationToolBar(CheckableToolBar):
    points: ActionView = field(init=False, default_factory=ActionView)


@dataclass(eq=False)
class ExampleMainToolBar(MainToolBar):
    navigation: NavigationToolBar = field(init=False, default_factory=NavigationToolBar)


PointsTableView: TypeAlias = SimpleTableView["Model"]


@dataclass(eq=False)
class ExampleMainView(MainView):
    toolbar: ExampleMainToolBar = field(init=False, default_factory=ExampleMainToolBar)
    points_view: PointsTableView = field(init=False, default_factory=PointsTableView)


def initialize_navigation(view: NavigationToolBar, main_view: "ExampleMainView") -> None:
    view.points.is_checked = True
    view.points.text = "Points"
    view.points.visible_views = [main_view.points_view]

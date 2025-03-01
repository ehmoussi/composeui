from composeui.core.interfaces.iactionview import IActionView
from composeui.items.simpletable import ISimpleTableView
from composeui.mainview.interfaces.imaintoolbar import IMainToolBar
from composeui.mainview.interfaces.imainview import IMainView
from composeui.mainview.interfaces.itoolbar import ICheckableToolBar

from typing_extensions import TypeAlias

import typing
from dataclasses import dataclass, field

if typing.TYPE_CHECKING:
    from examples.simpletableview.app import Model


@dataclass(eq=False)
class INavigationToolBar(ICheckableToolBar):
    points: IActionView = field(init=False, default_factory=IActionView)


@dataclass(eq=False)
class IExampleMainToolBar(IMainToolBar):
    navigation: INavigationToolBar = field(init=False, default_factory=INavigationToolBar)


IPointsTableView: TypeAlias = ISimpleTableView["Model"]


@dataclass(eq=False)
class IExampleMainView(IMainView):
    toolbar: IExampleMainToolBar = field(init=False, default_factory=IExampleMainToolBar)
    points_view: IPointsTableView = field(init=False, default_factory=IPointsTableView)


def initialize_navigation(view: INavigationToolBar, main_view: "IExampleMainView") -> None:
    view.points.is_checked = True
    view.points.text = "Points"
    view.points.visible_views = [main_view.points_view]

"""Example salome view."""

from composeui.core.interfaces.iactionview import IActionView
from composeui.items.table.itableview import ITableView
from composeui.mainview.interfaces.imaintoolbar import IMainToolBar
from composeui.mainview.interfaces.itoolbar import ICheckableToolBar
from composeui.salomewrapper.mainview.isalomemainview import ISalomeMainView

import typing
from dataclasses import dataclass, field

if typing.TYPE_CHECKING:
    from examples.salomeview.cubetable import CubeTableItems


@dataclass(eq=False)
class IModule2NavigationToolBar(ICheckableToolBar):
    cube_table: IActionView = field(init=False, default_factory=IActionView)


@dataclass(eq=False)
class IModule2MainToolBar(IMainToolBar):
    navigation: IModule2NavigationToolBar = field(
        init=False, default_factory=IModule2NavigationToolBar
    )


@dataclass(eq=False)
class IModule2MainView(ISalomeMainView):
    toolbar: IModule2MainToolBar = field(init=False, default_factory=IModule2MainToolBar)
    cube_table: ITableView["CubeTableItems"] = field(init=False, default_factory=ITableView)


def initialize_navigation(
    view: IModule2NavigationToolBar, main_view: IModule2MainView
) -> None:
    view.cube_table.is_checked = True
    view.cube_table.text = "Cube Table"
    view.cube_table.visible_views.extend([main_view.central_view, main_view.cube_table])

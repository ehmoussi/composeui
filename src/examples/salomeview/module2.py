"""Example salome view."""

from composeui.core.views.actionview import ActionView
from composeui.items.table.tableview import TableView
from composeui.mainview.views.maintoolbar import MainToolBar
from composeui.mainview.views.toolbar import CheckableToolBar
from composeui.salomewrapper.mainview.salomemainview import SalomeMainView

import typing
from dataclasses import dataclass, field

if typing.TYPE_CHECKING:
    from examples.salomeview.cubetable import CubeTableItems


@dataclass(eq=False)
class Module2NavigationToolBar(CheckableToolBar):
    cube_table: ActionView = field(init=False, repr=False, default_factory=ActionView)


@dataclass(eq=False)
class Module2MainToolBar(MainToolBar):
    navigation: Module2NavigationToolBar = field(
        init=False, repr=False, default_factory=Module2NavigationToolBar
    )


@dataclass(eq=False)
class Module2MainView(SalomeMainView):
    toolbar: Module2MainToolBar = field(
        init=False, repr=False, default_factory=Module2MainToolBar
    )
    cube_table: TableView["CubeTableItems"] = field(
        init=False, repr=False, default_factory=TableView
    )


def initialize_navigation(view: Module2NavigationToolBar, main_view: Module2MainView) -> None:
    view.cube_table.is_checked = True
    view.cube_table.text = "Cube Table"
    view.cube_table.visible_views.extend([main_view.central_view, main_view.cube_table])

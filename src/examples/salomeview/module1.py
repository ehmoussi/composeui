"""Example salome view."""

from composeui.core.views.actionview import ActionView
from composeui.mainview.views.dockview import DockView
from composeui.mainview.views.maintoolbar import MainToolBar
from composeui.mainview.views.toolbar import CheckableToolBar
from composeui.salomewrapper.mainview.salomemainview import SalomeMainView
from examples.salomeview.cubedefinition import CubeDefinitionView

from dataclasses import dataclass, field


@dataclass(eq=False)
class LeftDockView(DockView):
    cube_definition: CubeDefinitionView = field(init=False, default_factory=CubeDefinitionView)


@dataclass(eq=False)
class Module1NavigationToolBar(CheckableToolBar):
    cube_definition: ActionView = field(init=False, default_factory=ActionView)


@dataclass(eq=False)
class Module1MainToolBar(MainToolBar):
    navigation: Module1NavigationToolBar = field(
        init=False, default_factory=Module1NavigationToolBar
    )


@dataclass(eq=False)
class Module1MainView(SalomeMainView):
    toolbar: Module1MainToolBar = field(init=False, default_factory=Module1MainToolBar)
    left_dock: LeftDockView = field(init=False, default_factory=LeftDockView)


def initialize_navigation(view: Module1NavigationToolBar, main_view: Module1MainView) -> None:
    view.cube_definition.is_checked = True
    view.cube_definition.text = "Cube Definition"
    view.cube_definition.visible_views.extend(
        [
            main_view.left_dock,
            main_view.left_dock.cube_definition,
            main_view.salome_views.occ_view,
        ]
    )

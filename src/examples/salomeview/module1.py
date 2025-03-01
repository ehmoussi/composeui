"""Example salome view."""

from composeui.core.views.iactionview import IActionView
from composeui.mainview.interfaces.idockview import IDockView
from composeui.mainview.interfaces.imaintoolbar import IMainToolBar
from composeui.mainview.interfaces.itoolbar import ICheckableToolBar
from composeui.salomewrapper.mainview.isalomemainview import ISalomeMainView
from examples.salomeview.cubedefinition import ICubeDefinitionView

from dataclasses import dataclass, field


@dataclass(eq=False)
class ILeftDockView(IDockView):
    cube_definition: ICubeDefinitionView = field(
        init=False, default_factory=ICubeDefinitionView
    )


@dataclass(eq=False)
class IModule1NavigationToolBar(ICheckableToolBar):
    cube_definition: IActionView = field(init=False, default_factory=IActionView)


@dataclass(eq=False)
class IModule1MainToolBar(IMainToolBar):
    navigation: IModule1NavigationToolBar = field(
        init=False, default_factory=IModule1NavigationToolBar
    )


@dataclass(eq=False)
class IModule1MainView(ISalomeMainView):
    toolbar: IModule1MainToolBar = field(init=False, default_factory=IModule1MainToolBar)
    left_dock: ILeftDockView = field(init=False, default_factory=ILeftDockView)


def initialize_navigation(
    view: IModule1NavigationToolBar, main_view: IModule1MainView
) -> None:
    view.cube_definition.is_checked = True
    view.cube_definition.text = "Cube Definition"
    view.cube_definition.visible_views.extend(
        [
            main_view.left_dock,
            main_view.left_dock.cube_definition,
            main_view.salome_views.occ_view,
        ]
    )

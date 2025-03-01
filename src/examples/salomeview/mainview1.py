from composeui.form.formview import FormView
from composeui.mainview.interfaces.idockview import DockArea
from composeui.mainview.interfaces.imainmenu import IMainMenu
from composeui.mainview.qt.dockview import DockView
from composeui.salomewrapper.core.qt.salomemaintoolbar import SalomeMainToolBar
from composeui.salomewrapper.mainview.qt.salomemainmenu import SalomeMainMenu
from composeui.salomewrapper.mainview.qt.salomemainview import SalomeMainView
from examples.salomeview.cubedefinition import CubeDefinitionItems, ICubeDefinitionView
from examples.salomeview.module1 import ILeftDockView, IModule1MainToolBar, IModule1MainView

from qtpy.QtCore import Qt

from dataclasses import dataclass, field


@dataclass(eq=False)
class ExampleMainMenu(SalomeMainMenu, IMainMenu): ...


@dataclass(eq=False)
class Module1ToolBar(SalomeMainToolBar, IModule1MainToolBar): ...


@dataclass(eq=False)
class CubeDefinitionView(FormView[CubeDefinitionItems], ICubeDefinitionView): ...


@dataclass(eq=False)
class LeftDockView(DockView, ILeftDockView):
    cube_definition: CubeDefinitionView = field(init=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.cube_definition = CubeDefinitionView()
        self.central_layout.addWidget(self.cube_definition.view)


@dataclass(eq=False)
class Module1MainView(SalomeMainView, IModule1MainView):
    menu: ExampleMainMenu = field(init=False)
    left_dock: LeftDockView = field(init=False)
    toolbar: Module1ToolBar = field(init=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.menu = ExampleMainMenu()
        self.toolbar = Module1ToolBar(self.module_name, self.view)
        # left dock
        self.left_dock = LeftDockView()
        self.left_dock.area = DockArea.LEFT
        self.view.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.left_dock.view)

    def _set_visible(self, is_visible: bool) -> None:
        super()._set_visible(is_visible)
        self.left_dock.is_visible = is_visible

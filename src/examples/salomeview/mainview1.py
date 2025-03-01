from composeui.form.qtformview import QtFormView
from composeui.mainview.interfaces.idockview import DockArea
from composeui.mainview.interfaces.imainmenu import IMainMenu
from composeui.mainview.qt.qtdockview import QtDockView
from composeui.salomewrapper.core.qt.qtsalomemaintoolbar import QtSalomeMainToolBar
from composeui.salomewrapper.mainview.qt.qtsalomemainmenu import QtSalomeMainMenu
from composeui.salomewrapper.mainview.qt.qtsalomemainview import QtSalomeMainView
from examples.salomeview.cubedefinition import CubeDefinitionItems, ICubeDefinitionView
from examples.salomeview.module1 import ILeftDockView, IModule1MainToolBar, IModule1MainView

from qtpy.QtCore import Qt

from dataclasses import dataclass, field


@dataclass(eq=False)
class ExampleMainMenu(QtSalomeMainMenu, IMainMenu): ...


@dataclass(eq=False)
class Module1ToolBar(QtSalomeMainToolBar, IModule1MainToolBar): ...


@dataclass(eq=False)
class CubeDefinitionView(QtFormView[CubeDefinitionItems], ICubeDefinitionView): ...


@dataclass(eq=False)
class LeftDockView(QtDockView, ILeftDockView):
    cube_definition: CubeDefinitionView = field(init=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.cube_definition = CubeDefinitionView()
        self.central_layout.addWidget(self.cube_definition.view)


@dataclass(eq=False)
class Module1MainView(QtSalomeMainView, IModule1MainView):
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

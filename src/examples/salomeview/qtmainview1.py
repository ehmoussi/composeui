from composeui.form.qtformview import QtFormView
from composeui.mainview.qt.qtdockview import QtDockView
from composeui.mainview.views.dockview import DockArea
from composeui.mainview.views.mainmenu import MainMenu
from composeui.salomewrapper.core.qt.qtsalomemaintoolbar import QtSalomeMainToolBar
from composeui.salomewrapper.mainview.qt.qtsalomemainmenu import QtSalomeMainMenu
from composeui.salomewrapper.mainview.qt.qtsalomemainview import QtSalomeMainView
from examples.salomeview.cubedefinition import CubeDefinitionItems, CubeDefinitionView
from examples.salomeview.module1 import LeftDockView, Module1MainToolBar, Module1MainView

from qtpy.QtCore import Qt

from dataclasses import dataclass, field


@dataclass(eq=False)
class QtExampleMainMenu(QtSalomeMainMenu, MainMenu): ...


@dataclass(eq=False)
class QtModule1ToolBar(QtSalomeMainToolBar, Module1MainToolBar): ...


@dataclass(eq=False)
class QtCubeDefinitionView(QtFormView[CubeDefinitionItems], CubeDefinitionView): ...


@dataclass(eq=False)
class QtLeftDockView(QtDockView, LeftDockView):
    cube_definition: QtCubeDefinitionView = field(init=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.cube_definition = QtCubeDefinitionView()
        self.central_layout.addWidget(self.cube_definition.view)


@dataclass(eq=False)
class QtModule1MainView(QtSalomeMainView, Module1MainView):
    menu: QtExampleMainMenu = field(init=False)
    left_dock: QtLeftDockView = field(init=False)
    toolbar: QtModule1ToolBar = field(init=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.menu = QtExampleMainMenu()
        self.toolbar = QtModule1ToolBar(self.module_name, self.view)
        # left dock
        self.left_dock = QtLeftDockView()
        self.left_dock.area = DockArea.LEFT
        self.view.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.left_dock.view)

    def _set_visible(self, is_visible: bool) -> None:
        super()._set_visible(is_visible)
        self.left_dock.is_visible = is_visible

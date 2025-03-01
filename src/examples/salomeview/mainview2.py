from composeui.items.table.qt.qttableview import QtTableView
from composeui.mainview.interfaces.imainmenu import IMainMenu
from composeui.salomewrapper.core.qt.qtsalomemaintoolbar import QtSalomeMainToolBar
from composeui.salomewrapper.mainview.qt.qtsalomemainmenu import QtSalomeMainMenu
from composeui.salomewrapper.mainview.qt.qtsalomemainview import QtSalomeMainView
from examples.salomeview.module2 import IModule2MainToolBar, IModule2MainView

import typing
from dataclasses import dataclass, field

if typing.TYPE_CHECKING:
    from examples.salomeview.cubetable import CubeTableItems


@dataclass(eq=False)
class ExampleMainMenu(QtSalomeMainMenu, IMainMenu): ...


@dataclass(eq=False)
class Module2ToolBar(QtSalomeMainToolBar, IModule2MainToolBar): ...


@dataclass(eq=False)
class Module2MainView(QtSalomeMainView, IModule2MainView):
    menu: ExampleMainMenu = field(init=False)
    toolbar: Module2ToolBar = field(init=False)
    cube_table: QtTableView["CubeTableItems"] = field(init=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.menu = ExampleMainMenu()
        self.toolbar = Module2ToolBar(self.module_name, self.view)

    def create_central_views(self) -> None:
        super().create_central_views()
        # central views
        self.cube_table = QtTableView()
        self.central_view.layout.addWidget(self.cube_table.view)

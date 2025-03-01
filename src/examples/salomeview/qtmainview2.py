from composeui.items.table.qt.qttableview import QtTableView
from composeui.mainview.views.mainmenu import MainMenu
from composeui.salomewrapper.core.qt.qtsalomemaintoolbar import QtSalomeMainToolBar
from composeui.salomewrapper.mainview.qt.qtsalomemainmenu import QtSalomeMainMenu
from composeui.salomewrapper.mainview.qt.qtsalomemainview import QtSalomeMainView
from examples.salomeview.module2 import Module2MainToolBar, Module2MainView

import typing
from dataclasses import dataclass, field

if typing.TYPE_CHECKING:
    from examples.salomeview.cubetable import CubeTableItems


@dataclass(eq=False)
class QtExampleMainMenu(QtSalomeMainMenu, MainMenu): ...


@dataclass(eq=False)
class QtModule2ToolBar(QtSalomeMainToolBar, Module2MainToolBar): ...


@dataclass(eq=False)
class QtModule2MainView(QtSalomeMainView, Module2MainView):
    menu: QtExampleMainMenu = field(init=False, repr=False)
    toolbar: QtModule2ToolBar = field(init=False, repr=False)
    cube_table: QtTableView["CubeTableItems"] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.menu = QtExampleMainMenu()
        self.toolbar = QtModule2ToolBar(self.module_name, self.view)

    def create_central_views(self) -> None:
        super().create_central_views()
        # central views
        self.cube_table = QtTableView()
        self.central_view.layout.addWidget(self.cube_table.view)

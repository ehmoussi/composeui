from composeui.mainview.qt.qtmainmenu import QtMainMenu
from composeui.mainview.qt.qtmaintoolbar import QtMainToolBar
from composeui.mainview.qt.qtmainview import QtMainView
from composeui.mainview.views.mainmenu import MainMenu
from composeui.mainview.views.maintoolbar import MainToolBar
from examples.taskview.msgspec.app import ExampleMainView
from examples.taskview.msgspec.qttaskview import QtTaskView

from dataclasses import dataclass, field


@dataclass(eq=False)
class QtExampleMainMenu(QtMainMenu, MainMenu): ...


@dataclass(eq=False)
class QtExampleMainToolBar(QtMainToolBar, MainToolBar): ...


@dataclass(eq=False)
class QtExampleMainView(QtMainView, ExampleMainView):
    menu: QtExampleMainMenu = field(init=False, repr=False)
    toolbar: QtExampleMainToolBar = field(init=False, repr=False)
    task: QtTaskView = field(init=False, repr=False)

    def __post_init__(self, with_app: bool) -> None:
        super().__post_init__(with_app)
        self.menu = QtExampleMainMenu(self.view)
        self.toolbar = QtExampleMainToolBar(self.view)
        self.task = QtTaskView()
        self.central_layout.addWidget(self.task.view)

from composeui.mainview.interfaces.imainmenu import IMainMenu
from composeui.mainview.interfaces.imaintoolbar import IMainToolBar
from composeui.mainview.qt.qtmainmenu import QtMainMenu
from composeui.mainview.qt.qtmaintoolbar import QtMainToolBar
from composeui.mainview.qt.qtmainview import QtMainView
from examples.taskview.pydantic.app import IExampleMainView
from examples.taskview.pydantic.taskview import TaskView

from dataclasses import dataclass, field


@dataclass(eq=False)
class QtExampleMainMenu(QtMainMenu, IMainMenu): ...


@dataclass(eq=False)
class QtExampleMainToolBar(QtMainToolBar, IMainToolBar): ...


@dataclass(eq=False)
class QtExampleMainView(QtMainView, IExampleMainView):
    menu: QtExampleMainMenu = field(init=False)
    toolbar: QtExampleMainToolBar = field(init=False)
    task: TaskView = field(init=False)

    def __post_init__(self, with_app: bool) -> None:
        super().__post_init__(with_app)
        self.menu = QtExampleMainMenu(self.view)
        self.toolbar = QtExampleMainToolBar(self.view)
        self.task = TaskView()
        self.central_layout.addWidget(self.task.view)

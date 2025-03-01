from composeui.mainview.qt.qtmainmenu import QtMainMenu
from composeui.mainview.qt.qtmaintoolbar import QtMainToolBar
from composeui.mainview.qt.qtmainview import QtMainView
from composeui.mainview.views.mainmenu import MainMenu
from examples.formview.example import ExampleMainToolBar, ExampleMainView
from examples.formview.qtpipeview import QtPipeApplyFormView, QtPipeFormView

from dataclasses import dataclass, field


@dataclass(eq=False)
class QtExampleMainMenu(QtMainMenu, MainMenu): ...


@dataclass(eq=False)
class QtExampleMainToolBar(QtMainToolBar, ExampleMainToolBar): ...


@dataclass(eq=False)
class QtExampleMainView(QtMainView, ExampleMainView):
    menu: QtExampleMainMenu = field(init=False)
    toolbar: QtExampleMainToolBar = field(init=False)
    pipe_view: QtPipeFormView = field(init=False)
    apply_pipe_view: QtPipeApplyFormView = field(init=False)

    def __post_init__(self, with_app: bool) -> None:
        super().__post_init__(with_app)
        self.menu = QtExampleMainMenu(self.view)
        self.toolbar = QtExampleMainToolBar(self.view)
        self.pipe_view = QtPipeFormView()
        self.central_layout.addWidget(self.pipe_view.view)
        self.apply_pipe_view = QtPipeApplyFormView()
        self.central_layout.addWidget(self.apply_pipe_view.view)
        self.central_layout.addStretch()

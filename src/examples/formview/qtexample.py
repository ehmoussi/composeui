from composeui.mainview.interfaces.imainmenu import IMainMenu
from composeui.mainview.qt.qtmainmenu import QtMainMenu
from composeui.mainview.qt.qtmaintoolbar import QtMainToolBar
from composeui.mainview.qt.qtmainview import QtMainView
from examples.formview.example import IExampleMainToolBar, IExampleMainView
from examples.formview.pipeview import PipeApplyFormView, PipeFormView

from dataclasses import dataclass, field


@dataclass(eq=False)
class QtExampleMainMenu(QtMainMenu, IMainMenu): ...


@dataclass(eq=False)
class QtExampleMainToolBar(QtMainToolBar, IExampleMainToolBar): ...


@dataclass(eq=False)
class QtExampleMainView(QtMainView, IExampleMainView):
    menu: QtExampleMainMenu = field(init=False)
    toolbar: QtExampleMainToolBar = field(init=False)
    pipe_view: PipeFormView = field(init=False)
    apply_pipe_view: PipeApplyFormView = field(init=False)

    def __post_init__(self, with_app: bool) -> None:
        super().__post_init__(with_app)
        self.menu = QtExampleMainMenu(self.view)
        self.toolbar = QtExampleMainToolBar(self.view)
        self.pipe_view = PipeFormView()
        self.central_layout.addWidget(self.pipe_view.view)
        self.apply_pipe_view = PipeApplyFormView()
        self.central_layout.addWidget(self.apply_pipe_view.view)
        self.central_layout.addStretch()

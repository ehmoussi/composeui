from composeui.core.qt.groupview import GroupView
from composeui.core.qt.view import View
from composeui.form.formview import GroupBoxApplyFormView
from composeui.mainview.interfaces.imainmenu import IMainMenu
from composeui.mainview.interfaces.imaintoolbar import IMainToolBar
from composeui.mainview.qt.mainmenu import MainMenu
from composeui.mainview.qt.maintoolbar import MainToolBar
from composeui.mainview.qt.mainview import MainView
from composeui.vtk.qt.vtkview import VTKView
from examples.vtkview.example import (
    IExampleMainView,
    IVTKConfigView,
    IVTKExampleView,
    IVTKInfosView,
    VTKConfigFormItems,
)

from qtpy.QtCore import Qt
from qtpy.QtWidgets import QHBoxLayout, QSplitter, QTextEdit

from dataclasses import dataclass, field


@dataclass(eq=False)
class VTKMainMenu(MainMenu, IMainMenu): ...


@dataclass(eq=False)
class VTKMainToolBar(MainToolBar, IMainToolBar): ...


@dataclass(eq=False)
class VTKConfigView(GroupBoxApplyFormView[VTKConfigFormItems], IVTKConfigView): ...


@dataclass(eq=False)
class VTKInfosView(GroupView, IVTKInfosView):

    _text_edit: QTextEdit = field(init=False, default_factory=QTextEdit)

    def __post_init__(self) -> None:
        super().__post_init__()
        layout = QHBoxLayout()
        self.view.setLayout(layout)
        # text edit
        layout.addWidget(self._text_edit)

    @property  # type: ignore[misc]
    def text(self) -> str:
        return self._text_edit.toPlainText()

    @text.setter
    def text(self, text: str) -> None:
        self._text_edit.setMarkdown(text)


@dataclass(eq=False)
class VTKExampleView(View, IVTKExampleView):
    view: QSplitter = field(init=False, default_factory=lambda: QSplitter(Qt.Vertical))

    configuration: VTKConfigView = field(init=False, default_factory=VTKConfigView)
    vtk_view: VTKView = field(init=False, default_factory=VTKView)
    informations: VTKInfosView = field(init=False, default_factory=VTKInfosView)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.view.addWidget(self.configuration.view)
        # vtk view / informations
        splitter = QSplitter()
        splitter.addWidget(self.vtk_view.view)
        splitter.setStretchFactor(0, 2)
        splitter.addWidget(self.informations.view)
        self.view.addWidget(splitter)
        self.view.setStretchFactor(1, 3)


@dataclass(eq=False)
class ExampleMainView(MainView, IExampleMainView):
    menu: VTKMainMenu = field(init=False)
    toolbar: VTKMainToolBar = field(init=False)

    vtk_example: VTKExampleView = field(init=False)

    def __post_init__(self, with_app: bool) -> None:
        super().__post_init__(with_app)
        self.menu = VTKMainMenu(self.view)
        self.toolbar = VTKMainToolBar(self.view)
        # views
        self.vtk_example = VTKExampleView()
        self.central_layout.addWidget(self.vtk_example.view)

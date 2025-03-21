from composeui.core.qt.qtgroupview import QtGroupView
from composeui.core.qt.qtview import QtView
from composeui.form.qtformview import QtGroupBoxApplyFormView
from composeui.mainview.qt.qtmainmenu import QtMainMenu
from composeui.mainview.qt.qtmaintoolbar import QtMainToolBar
from composeui.mainview.qt.qtmainview import QtMainView
from composeui.mainview.views.mainmenu import MainMenu
from composeui.mainview.views.maintoolbar import MainToolBar
from composeui.vtk.qt.qtvtkview import QtVTKView
from examples.vtkview.example import (
    ExampleMainView,
    VTKConfigFormItems,
    VTKConfigView,
    VTKExampleView,
    VTKInfosView,
)

from qtpy.QtCore import Qt
from qtpy.QtWidgets import QHBoxLayout, QSplitter, QTextEdit

from dataclasses import dataclass, field


@dataclass(eq=False)
class QtVTKMainMenu(QtMainMenu, MainMenu): ...


@dataclass(eq=False)
class QtVTKMainToolBar(QtMainToolBar, MainToolBar): ...


@dataclass(eq=False)
class QtVTKConfigView(QtGroupBoxApplyFormView[VTKConfigFormItems], VTKConfigView): ...


@dataclass(eq=False)
class QtVTKInfosView(QtGroupView, VTKInfosView):

    _text_edit: QTextEdit = field(init=False, repr=False, default_factory=QTextEdit)

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
class QtVTKExampleView(QtView, VTKExampleView):
    view: QSplitter = field(
        init=False, repr=False, default_factory=lambda: QSplitter(Qt.Vertical)
    )

    configuration: QtVTKConfigView = field(
        init=False, repr=False, default_factory=QtVTKConfigView
    )
    vtk_view: QtVTKView = field(init=False, repr=False, default_factory=QtVTKView)
    informations: QtVTKInfosView = field(
        init=False, repr=False, default_factory=QtVTKInfosView
    )

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
class QtExampleMainView(QtMainView, ExampleMainView):
    menu: QtVTKMainMenu = field(init=False, repr=False)
    toolbar: QtVTKMainToolBar = field(init=False, repr=False)

    vtk_example: QtVTKExampleView = field(init=False, repr=False)

    def __post_init__(self, with_app: bool) -> None:
        super().__post_init__(with_app)
        self.menu = QtVTKMainMenu(self.view)
        self.toolbar = QtVTKMainToolBar(self.view)
        # views
        self.vtk_example = QtVTKExampleView()
        self.central_layout.addWidget(self.vtk_example.view)

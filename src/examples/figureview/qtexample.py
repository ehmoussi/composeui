from composeui.core.qt.qtview import QtView
from composeui.figure.qtfigureview import QtFigureView
from composeui.mainview.qt.qtmainmenu import QtMainMenu
from composeui.mainview.qt.qtmaintoolbar import QtMainToolBar
from composeui.mainview.qt.qtmainview import QtMainView
from composeui.mainview.views.mainmenu import MainMenu
from composeui.mainview.views.maintoolbar import MainToolBar
from examples.figureview.batman import BatmanView
from examples.figureview.example import ExampleMainView

from qtpy.QtCore import Qt
from qtpy.QtWidgets import QLabel, QVBoxLayout, QWidget

from dataclasses import dataclass, field


@dataclass(eq=False)
class QtBatmanView(QtView, BatmanView):
    view: QWidget = field(init=False)
    figure: QtFigureView = field(init=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.view = QWidget()
        self.layout = QVBoxLayout()
        # label text
        self.text_label = QLabel()
        self.text_label.setAlignment(Qt.AlignCenter)
        self.text_label.setStyleSheet("font-weight: bold; font-size: 16pt")
        self.layout.addWidget(self.text_label)
        # figure
        self.figure = QtFigureView()
        self.layout.addWidget(self.figure.view)
        self.view.setLayout(self.layout)

    @property  # type: ignore[misc]
    def message(self) -> str:
        return self.text_label.text()

    @message.setter
    def message(self, message: str) -> None:
        self.text_label.setText(message)


@dataclass(eq=False)
class QtExampleMainMenu(QtMainMenu, MainMenu): ...


@dataclass(eq=False)
class QtExampleMainToolBar(QtMainToolBar, MainToolBar): ...


@dataclass(eq=False)
class QtExampleMainView(QtMainView, ExampleMainView):

    menu: QtExampleMainMenu = field(init=False)
    toolbar: QtExampleMainToolBar = field(init=False)
    batman: QtBatmanView = field(init=False)

    def __post_init__(self, with_app: bool) -> None:
        super().__post_init__(with_app)
        self.menu = QtExampleMainMenu(self.view)
        self.toolbar = QtExampleMainToolBar(self.view)
        self.batman = QtBatmanView()
        self.central_layout.addWidget(self.batman.view)

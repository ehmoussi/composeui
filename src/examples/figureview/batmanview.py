from composeui.core.qt.view import View
from composeui.figure.figureview import FigureView
from examples.figureview.batman import IBatmanView

from qtpy.QtCore import Qt
from qtpy.QtWidgets import QLabel, QVBoxLayout, QWidget

from dataclasses import dataclass, field


@dataclass(eq=False)
class BatmanView(View, IBatmanView):
    view: QWidget = field(init=False)
    figure: FigureView = field(init=False)

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
        self.figure = FigureView()
        self.layout.addWidget(self.figure.view)
        self.view.setLayout(self.layout)

    @property  # type: ignore[misc]
    def message(self) -> str:
        return self.text_label.text()

    @message.setter
    def message(self, message: str) -> None:
        self.text_label.setText(message)

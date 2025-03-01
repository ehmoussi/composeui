from composeui.core.qt.qtview import QtView
from examples.multipleviews.component2.view2 import IRightView2, IView2

from qtpy.QtWidgets import QHBoxLayout, QLabel, QWidget

from dataclasses import dataclass, field


@dataclass(eq=False)
class View2(QtView, IView2):
    view: QWidget = field(init=False, default_factory=QWidget)
    text_2_label: QLabel = field(init=False, default_factory=QLabel)

    def __post_init__(self) -> None:
        super().__post_init__()
        layout = QHBoxLayout()
        self.view.setLayout(layout)
        # label
        font = self.text_2_label.font()
        font.setPointSize(24)
        self.text_2_label.setFont(font)
        layout.addStretch()
        layout.addWidget(self.text_2_label)
        layout.addStretch()

    @property  # type: ignore[misc]
    def text_2(self) -> str:
        return str(self.text_2_label.text())

    @text_2.setter
    def text_2(self, text: str) -> None:
        self.text_2_label.setText(text)


@dataclass(eq=False)
class RightView2(QtView, IRightView2):
    view: QWidget = field(init=False, default_factory=QWidget)
    text_2_label: QLabel = field(init=False, default_factory=QLabel)

    def __post_init__(self) -> None:
        super().__post_init__()
        layout = QHBoxLayout()
        self.view.setLayout(layout)
        # label
        font = self.text_2_label.font()
        font.setPointSize(24)
        self.text_2_label.setFont(font)
        layout.addStretch()
        layout.addWidget(self.text_2_label)
        layout.addStretch()

    @property  # type: ignore[misc]
    def right_text_2(self) -> str:
        return str(self.text_2_label.text())

    @right_text_2.setter
    def right_text_2(self, text: str) -> None:
        self.text_2_label.setText(text)

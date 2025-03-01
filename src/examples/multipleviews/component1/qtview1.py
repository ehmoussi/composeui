from composeui.core.qt.qtview import QtView
from examples.multipleviews.component1.view1 import LeftView1, View1

from qtpy.QtWidgets import QHBoxLayout, QLabel, QWidget

from dataclasses import dataclass, field


@dataclass(eq=False)
class QtView1(QtView, View1):
    view: QWidget = field(init=False, repr=False, default_factory=QWidget)
    text_1_label: QLabel = field(init=False, repr=False, default_factory=QLabel)

    def __post_init__(self) -> None:
        super().__post_init__()
        layout = QHBoxLayout()
        self.view.setLayout(layout)
        # label
        font = self.text_1_label.font()
        font.setPointSize(24)
        self.text_1_label.setFont(font)
        layout.addStretch()
        layout.addWidget(self.text_1_label)
        layout.addStretch()

    @property  # type: ignore[misc]
    def text_1(self) -> str:
        return self.text_1_label.text()

    @text_1.setter
    def text_1(self, text: str) -> None:
        self.text_1_label.setText(f"{text}")


@dataclass(eq=False)
class QtLeftView1(QtView, LeftView1):
    view: QWidget = field(init=False, repr=False, default_factory=QWidget)

    text_1_label: QLabel = field(init=False, repr=False, default_factory=QLabel)

    def __post_init__(self) -> None:
        super().__post_init__()
        layout = QHBoxLayout()
        self.view.setLayout(layout)
        # label
        font = self.text_1_label.font()
        font.setPointSize(24)
        self.text_1_label.setFont(font)
        layout.addStretch()
        layout.addWidget(self.text_1_label)
        layout.addStretch()

    @property  # type: ignore[misc]
    def left_text_1(self) -> str:
        return str(self.text_1_label.text())

    @left_text_1.setter
    def left_text_1(self, text: str) -> None:
        self.text_1_label.setText(f"{text}")

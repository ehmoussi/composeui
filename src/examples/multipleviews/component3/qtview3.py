from composeui.core.qt.qtview import QtView
from examples.multipleviews.component3.view3 import View3

from qtpy.QtWidgets import QHBoxLayout, QLabel, QWidget

from dataclasses import dataclass, field


@dataclass(eq=False)
class QtView3(QtView, View3):
    view: QWidget = field(init=False, repr=False, default_factory=QWidget)

    text_3_label: QLabel = field(init=False, repr=False, default_factory=QLabel)

    def __post_init__(self) -> None:
        super().__post_init__()
        layout = QHBoxLayout()
        self.view.setLayout(layout)
        # label
        font = self.text_3_label.font()
        font.setPointSize(24)
        self.text_3_label.setFont(font)
        layout.addStretch()
        layout.addWidget(self.text_3_label)
        layout.addStretch()

    @property  # type: ignore[misc]
    def text_3(self) -> str:
        return str(self.text_3_label.text())

    @text_3.setter
    def text_3(self, text: str) -> None:
        self.text_3_label.setText(text)

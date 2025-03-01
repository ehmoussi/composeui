"""Popup view to display a text."""

from composeui.core.qt.qtview import QtView
from composeui.core.views.ipopuptextview import DialogChoices, PopupTextView

from qtpy.QtCore import Qt
from qtpy.QtGui import QIcon
from qtpy.QtWidgets import QDialog, QHBoxLayout, QPushButton, QTextEdit, QVBoxLayout, QWidget

from dataclasses import InitVar, dataclass, field
from typing import Optional


@dataclass(eq=False)
class QtPopupTextView(QtView, PopupTextView):
    r"""View used to confirm/reject a proposition in a long text format."""

    view: QDialog = field(init=False)

    parent: InitVar[QWidget]

    text_view: QTextEdit = field(init=False, default_factory=QTextEdit)
    confirm_button: QPushButton = field(init=False, default_factory=QPushButton)
    cancel_button: QPushButton = field(
        init=False, default_factory=lambda: QPushButton("Cancel")
    )

    def __post_init__(self, parent: QWidget) -> None:
        super().__post_init__()
        self.view = QDialog(parent)
        self.view.setModal(True)
        self.view.setMinimumSize(200, 100)
        layout = QVBoxLayout()
        self.view.setLayout(layout)
        # text
        self.text_view.setWindowFlags(Qt.FramelessWindowHint)
        self.text_view.viewport().setAutoFillBackground(False)
        self.text_view.setReadOnly(True)
        # self.text_view.viewport().setStyleSheet("border-color:black;")
        layout.addWidget(self.text_view)
        # Replace and cancel button
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        self.confirm_button.setAutoDefault(False)
        self.confirm_button.setToolTip("")
        # self.replace_button.setIcon(QIcon(":/icons/replace.png"))
        button_layout.addWidget(self.confirm_button)
        self.cancel_button.setAutoDefault(False)
        self.cancel_button.setToolTip("Cancel")
        self.cancel_button.setIcon(QIcon(":/icons/exit.png"))
        button_layout.addWidget(self.cancel_button)
        layout.addLayout(button_layout)
        # internal signals
        self.confirm_button.clicked.connect(self.view.accept)
        self.cancel_button.clicked.connect(self.view.reject)
        self.view.finished.connect(self._update_choice)
        self.view.rejected.connect(self._update_choice)

    def run(self) -> None:
        r"""Run the view."""
        self.view.open()

    def _update_choice(self, result: Optional[int] = None) -> None:
        """Update the choice according after the dialog is closed."""
        if result is not None and result == QDialog.Accepted:
            self.choice = DialogChoices.accepted
        else:
            self.choice = DialogChoices.rejected

    @property  # type: ignore[misc]
    def title(self) -> str:
        return self.text_view.windowTitle()

    @title.setter
    def title(self, title: str) -> None:
        self.text_view.setWindowTitle(title)

    @property  # type: ignore[misc]
    def text(self) -> str:
        return self.text_view.toPlainText()

    @text.setter
    def text(self, text: str) -> None:
        self.text_view.setPlainText(text)

    @property  # type: ignore[misc]
    def confirm_button_text(self) -> str:
        return self.confirm_button.text()

    @confirm_button_text.setter
    def confirm_button_text(self, text: str) -> None:
        self.confirm_button.setText(text)
        self.confirm_button.setToolTip(text)

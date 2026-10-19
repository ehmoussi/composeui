from __future__ import annotations

from typing import TYPE_CHECKING, Any

from qtpy.QtCore import Signal as QtSignal
from qtpy.QtWidgets import QDialog, QDialogButtonBox, QLabel, QPushButton, QVBoxLayout, QWidget

if TYPE_CHECKING:
    from qtpy.QtGui import QCloseEvent


class QFormDialog(QDialog):
    """A modal dialog: its text, its form, then OK and Cancel.

    It reports the user's answer without closing (`answered_ok`, `answered_cancel`, and
    `dismissed` for its window closed): its view closes it, and stays open when its
    form refuses OK. Escape is Cancel, as in any dialog.
    """

    answered_ok = QtSignal()
    answered_cancel = QtSignal()
    dismissed = QtSignal()

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.setModal(True)
        self._layout = QVBoxLayout(self)
        self.text = QLabel()
        self.text.setWordWrap(True)
        self._layout.addWidget(self.text)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self._layout.addWidget(self.buttons)

    @property
    def ok_button(self) -> QPushButton:
        button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        assert button is not None
        return button

    @property
    def cancel_button(self) -> QPushButton:
        button = self.buttons.button(QDialogButtonBox.StandardButton.Cancel)
        assert button is not None
        return button

    def set_form(self, form: QWidget) -> None:
        """Show `form` between the text and the buttons."""
        self._layout.insertWidget(1, form)

    def accept(self) -> None:
        self.answered_ok.emit()

    def reject(self) -> None:
        self.answered_cancel.emit()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        event.ignore()  # closed by its view, once it hears the answer
        self.dismissed.emit()

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from qtpy.QtCore import QSize, Signal, Slot
from qtpy.QtWidgets import QPlainTextEdit, QSizePolicy
from typing_extensions import override

if TYPE_CHECKING:
    from qtpy.QtGui import QFocusEvent


class QTextArea(QPlainTextEdit):
    """A field for several lines of plain text, with the signals of a `QLineEdit`."""

    # Emitted with the whole text whenever it changes
    text_changed = Signal(str)
    # Emitted when the field loses the focus after a change, as `QLineEdit.editingFinished`
    editing_finished = Signal()

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # in a form, Tab goes to the next field rather than into the text
        self.setTabChangesFocus(True)
        # four lines, as on the other backends, rather than all the height left in a form
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._is_changed = False
        self.textChanged.connect(self._emit_text_changed)

    @override
    def sizeHint(self) -> QSize:
        margins = self.contentsMargins()
        height = 4 * self.fontMetrics().lineSpacing() + 2 * self.document().documentMargin()
        return QSize(super().sizeHint().width(), round(height) + margins.top() + margins.bottom())

    @override
    def focusOutEvent(self, event: QFocusEvent) -> None:
        super().focusOutEvent(event)
        if self._is_changed:
            self._is_changed = False
            self.editing_finished.emit()

    @Slot()
    def _emit_text_changed(self) -> None:
        self._is_changed = True
        self.text_changed.emit(self.toPlainText())

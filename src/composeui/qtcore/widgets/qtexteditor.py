"""A text editor: plain text in a fixed-width font, its lines numbered, never wrapped."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from qtpy.QtCore import QRect, Qt, Signal, Slot
from qtpy.QtGui import QPainter, QPalette
from qtpy.QtWidgets import QPlainTextEdit, QWidget
from typing_extensions import override

from composeui.qtcore.widgets.qconsole import QSearchBox, QSearchText
from composeui.qtcore.widgets.qplaintext import plain_label

if TYPE_CHECKING:
    from qtpy.QtGui import QFocusEvent, QKeyEvent, QPaintEvent, QResizeEvent

#: the spaces that Tab inserts
INDENT = "    "


class QTextEditor(QSearchText):
    """Plain text that the user edits, with the signals of a `QLineEdit`.

    Its lines' numbers run down its left. Tab inserts `INDENT`, and Escape moves the focus
    to the next widget, as Tab does elsewhere. `text_changed` emits the whole text whenever
    the user changes it; `editing_finished` when the editor loses the focus after a change.
    """

    text_changed = Signal(str)
    editing_finished = Signal()

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.document().setDocumentMargin(6)  # some room between the text and its frame
        self._numbers = _LineNumbers(self)
        self._is_changed = False
        #: the app sets the text: no signal reports it
        self._is_set = False
        self.blockCountChanged.connect(self._fit_numbers)
        self.updateRequest.connect(self._update_numbers)
        # the current line's number stands out
        self.cursorPositionChanged.connect(self._numbers.update)
        self.textChanged.connect(self._emit_text_changed)
        self._fit_numbers()

    def set_text(self, text: str) -> None:
        """Show `text` instead, from its start, without reporting a change."""
        self._is_set = True
        try:
            self.setPlainText(text)
        finally:
            self._is_set = False

    def numbers_width(self) -> int:
        """Get the width of the numbers' margin: the last line's number, a space each side."""
        digits = len(str(self.blockCount()))
        return self.fontMetrics().horizontalAdvance("9" * (digits + 2))

    @override
    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Tab and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            self.textCursor().insertText(INDENT)
        elif event.key() == Qt.Key.Key_Escape:
            # QPlainTextEdit's own refuses while Tab types in the text
            QWidget.focusNextPrevChild(self, True)  # noqa: FBT003 (Qt's positional flag)
        else:
            super().keyPressEvent(event)

    @override
    def focusOutEvent(self, event: QFocusEvent) -> None:
        super().focusOutEvent(event)
        if self._is_changed:
            self._is_changed = False
            self.editing_finished.emit()

    @override
    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._fit_numbers()

    def paint_numbers(self, event: QPaintEvent) -> None:
        """Paint the numbers of the lines shown, in the margin, as Qt's code editor example."""
        painter = QPainter(self._numbers)
        palette = self.palette()
        painter.fillRect(event.rect(), palette.color(QPalette.ColorRole.AlternateBase))
        faint = palette.color(QPalette.ColorRole.PlaceholderText)
        current = self.textCursor().blockNumber()
        block = self.firstVisibleBlock()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        height = self.fontMetrics().height()
        width = self._numbers.width() - self.fontMetrics().horizontalAdvance(" ")
        while block.isValid() and top <= event.rect().bottom():
            is_current = block.blockNumber() == current
            painter.setPen(palette.color(QPalette.ColorRole.Text) if is_current else faint)
            number = str(block.blockNumber() + 1)
            painter.drawText(0, top, width, height, Qt.AlignmentFlag.AlignRight, number)
            top += round(self.blockBoundingRect(block).height())
            block = block.next()
        painter.end()

    @Slot()
    def _fit_numbers(self) -> None:
        """Fit the margin to the width of the last line's number and to the height of the text."""
        width = self.numbers_width()
        self.setViewportMargins(width, 0, 0, 0)
        area = self.contentsRect()
        self._numbers.setGeometry(QRect(area.left(), area.top(), width, area.height()))

    @Slot(QRect, int)
    def _update_numbers(self, _rect: QRect, _dy: int) -> None:
        # the text scrolled or changed: the whole margin again, a column of short numbers
        self._numbers.update()

    @Slot()
    def _emit_text_changed(self) -> None:
        if self._query != "":  # the matches move with the text
            self._show_matches(is_moved=False)
        if not self._is_set:
            self._is_changed = True
            self.text_changed.emit(self.toPlainText())


class _LineNumbers(QWidget):
    """The margin of a `QTextEditor` that its lines' numbers are painted in."""

    def __init__(self, editor: QTextEditor) -> None:
        super().__init__(editor)
        self._editor = editor

    @override
    def paintEvent(self, event: QPaintEvent) -> None:
        self._editor.paint_numbers(event)


class QTextEditorBox(QSearchBox):
    """A `QTextEditor` under its file's `name`, a search, the caret's `position`, Copy and Save.

    `show_position` writes the caret's line and column, in the words of a text given.
    """

    text: QTextEditor

    def __init__(self) -> None:
        super().__init__(QTextEditor())
        self.name = plain_label()
        font = self.name.font()
        font.setBold(True)
        self.name.setFont(font)
        self.position = plain_label()
        self.position.setEnabled(False)  # secondary text, in the palette's dimmed color
        self.controls.insertWidget(0, self.name)
        self.controls.insertWidget(self.controls.indexOf(self.copy), self.position)
        self._position_text = ""
        self.text.cursorPositionChanged.connect(self._show_position)

    def show_position(self, text: str) -> None:
        """Write the caret's place in `text`'s words, e.g. "Line {line}, column {column}"."""
        self._position_text = text
        self._show_position()

    @Slot()
    def _show_position(self) -> None:
        cursor = self.text.textCursor()
        line, column = cursor.blockNumber() + 1, cursor.positionInBlock() + 1
        self.position.setText(self._position_text.format(line=line, column=column))

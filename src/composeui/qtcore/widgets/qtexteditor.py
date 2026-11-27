"""A text editor: plain text in a fixed-width font, its lines numbered, never wrapped."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from qtpy.QtCore import QEvent, QRect, Qt, Signal, Slot
from qtpy.QtGui import QColor, QPainter, QPalette, QSyntaxHighlighter, QTextCharFormat
from qtpy.QtWidgets import QPlainTextEdit, QWidget
from typing_extensions import override

from composeui.core._views.inputs import HIGHLIGHT_COLORS, highlight_lines
from composeui.qtcore.widgets.qconsole import QSearchBox, QSearchText
from composeui.qtcore.widgets.qplaintext import plain_label

if TYPE_CHECKING:
    from qtpy.QtGui import QFocusEvent, QKeyEvent, QPaintEvent, QResizeEvent

    from composeui.core._views.inputs import Lexer

#: the spaces that Tab inserts
INDENT = "    "
#: half of a color's lightness (0 to 255): a base under it is dark, its text colors light
_MID_LIGHTNESS = 128


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
        self._highlighter = _Highlighter(self)
        self._is_changed = False
        #: the app sets the text: no signal reports it
        self._is_set = False
        #: the text as last reported: coloring it again changes only its formats
        self._text = ""
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

    def set_language(self, language: str | Lexer | None) -> None:
        """Color the text's syntax in `language`, as `highlight_lines` splits it."""
        self._highlighter.set_language(language)

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
    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange:  # a light theme or a dark one: its colors
            self._highlighter.rehighlight()

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
        text = self.toPlainText()
        if text == self._text:  # its colors, not its text
            return
        self._text = text
        if self._query != "":  # the matches move with the text
            self._show_matches(is_moved=False)
        if not self._is_set:
            self._is_changed = True
            self.text_changed.emit(text)


class _Highlighter(QSyntaxHighlighter):
    """The colors of a `QTextEditor`'s syntax, by `HIGHLIGHT_COLORS`, for the palette's base.

    The whole text is split again after each change, once, before Qt colors the lines
    changed: a change can color the lines after it, as an opened string does. Those are
    colored again after Qt's own pass.
    """

    def __init__(self, editor: QTextEditor) -> None:
        super().__init__(editor)
        self._editor = editor
        self._language: str | Lexer | None = None
        #: each line's colored parts, for `_text`
        self._parts: list[list[tuple[int, int, str]]] = []
        self._text = ""
        #: the lines whose colors changed with the last split, to color again
        self._changed: list[int] = []
        self._split()
        document = editor.document()
        # the text split before Qt's own reaction to the change, which colors its lines...
        document.contentsChange.connect(self._split)
        self.setDocument(document)
        # ... then the other lines whose colors changed
        document.contentsChange.connect(self._color_changed)

    def set_language(self, language: str | Lexer | None) -> None:
        self._language = language
        self._parts = []  # split again, in the new language
        self._split()
        self.rehighlight()

    @override
    def highlightBlock(self, text: str) -> None:
        line = self.currentBlock().blockNumber()
        is_dark = self._editor.palette().color(QPalette.ColorRole.Base).lightness() < _MID_LIGHTNESS
        for start, end, kind in self._parts[line]:
            color = QTextCharFormat()
            color.setForeground(QColor(HIGHLIGHT_COLORS[kind][is_dark]))
            self.setFormat(start, end - start, color)

    @Slot()
    def _split(self) -> None:
        text = self._editor.toPlainText()
        if text == self._text and self._parts:  # its colors changed, not its text
            return
        self._text = text
        before = self._parts
        self._parts = highlight_lines(text, self._language)
        self._changed = [
            line
            for line, parts in enumerate(self._parts)
            if line >= len(before) or before[line] != parts
        ]

    @Slot()
    def _color_changed(self) -> None:
        changed, self._changed = self._changed, []
        document = self._editor.document()
        for line in changed:
            self.rehighlightBlock(document.findBlockByNumber(line))


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

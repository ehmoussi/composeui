"""A console: plain text that grows at its end, scrolled to it unless the user scrolled up."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from qtpy.QtCore import Qt, Signal
from qtpy.QtGui import QColor, QFontDatabase, QTextCursor
from qtpy.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QSizePolicy,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from composeui.core.view import find_in_lines, follow_match
from composeui.qtcore.widgets.qplaintext import plain_label

if TYPE_CHECKING:
    from qtpy.QtGui import QKeyEvent

#: the background of a match, then of the current one; black text, on a light or dark palette
_MATCH_COLOR = QColor("#fde68a")
_CURRENT_COLOR = QColor("#f59e0b")


class QConsole(QPlainTextEdit):
    """Read-only plain text in a fixed-width font, a block per line, the last being written.

    `set_max_lines` keeps that many lines, the line being written not counted: Qt drops
    the oldest blocks. The user selects and copies the text.

    `set_query` highlights the matches of a search (`find_in_lines`), and shows the first;
    `step` shows the next, or the previous, around the ends. New lines keep the current
    match, or the next one if it went with the oldest lines (`follow_match`).
    `matches_changed` emits the current match's number, from 1, and the count: 0 and 0
    without a match.
    """

    matches_changed = Signal(int, int)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.setReadOnly(True)
        self.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self._query = ""
        #: the index of the current match, in the matches
        self._current = 0
        #: the current match: its line's number, from the text's first line ever, its start
        self._current_match: tuple[int, int] | None = None
        #: the lines dropped since the text was set, the oldest ones
        self._dropped = 0

    def set_max_lines(self, count: int) -> None:
        before = self.blockCount()
        self.setMaximumBlockCount(count + 1)
        self._dropped += before - self.blockCount()

    def set_text(self, text: str) -> None:
        """Show `text` instead, from its end."""
        self.setPlainText(text)
        self._dropped = 0
        self._scroll_to_end()
        self._show_matches(is_moved=False)

    def add(self, lines: list[str], last_line: str) -> None:
        """End the line being written with `lines`, then write `last_line` in its place.

        The text keeps its place on the screen unless the end was shown.
        """
        bar = self.verticalScrollBar()
        is_at_end = bar.value() == bar.maximum()
        cursor = QTextCursor(self.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock, QTextCursor.MoveMode.KeepAnchor)
        before = self.blockCount()
        cursor.insertText("\n".join([*lines, last_line]))
        self._dropped += before + len(lines) - self.blockCount()
        if is_at_end:
            self._scroll_to_end()
        self._show_matches(is_moved=False)

    def set_query(self, query: str) -> None:
        """Highlight the matches of `query`, and show the first."""
        self._query = query
        self._current = 0
        self._current_match = None
        self._show_matches(is_moved=True)

    def step(self, *, is_backwards: bool = False) -> None:
        """Show the next match, or the previous one."""
        count = len(self._matches())
        if count > 0:
            self._current = (self._current + (-1 if is_backwards else 1)) % count
            self._current_match = None
            self._show_matches(is_moved=True)

    def _matches(self) -> list[tuple[int, int, int]]:
        document = self.document()
        lines = [document.findBlockByNumber(n).text() for n in range(document.blockCount())]
        return find_in_lines(lines, self._query)

    def _show_matches(self, *, is_moved: bool) -> None:
        """Highlight the matches, and show the current one if `is_moved`."""
        matches = self._matches()
        if self._current_match is not None:  # lines came or went
            self._current = follow_match(matches, self._dropped, self._current_match)
        self._current = min(self._current, max(len(matches) - 1, 0))
        if len(matches) > 0:
            line, start, _end = matches[self._current]
            self._current_match = (self._dropped + line, start)
        selections: list[QTextEdit.ExtraSelection] = []
        for index, (line, start, end) in enumerate(matches):
            position = self.document().findBlockByNumber(line).position()
            selection = QTextEdit.ExtraSelection()
            selection.cursor = QTextCursor(self.document())
            selection.cursor.setPosition(position + start)
            selection.cursor.setPosition(position + end, QTextCursor.MoveMode.KeepAnchor)
            is_current = index == self._current
            selection.format.setBackground(_CURRENT_COLOR if is_current else _MATCH_COLOR)
            selection.format.setForeground(QColor(Qt.GlobalColor.black))
            selections.append(selection)
        self.setExtraSelections(selections)
        if is_moved and len(matches) > 0:
            current = selections[self._current].cursor
            cursor = QTextCursor(current)
            cursor.setPosition(current.selectionStart())
            self.setTextCursor(cursor)
            self.ensureCursorVisible()
        self.matches_changed.emit(self._current + 1 if matches else 0, len(matches))

    def _scroll_to_end(self) -> None:
        bar = self.verticalScrollBar()
        bar.setValue(bar.maximum())


class QSearchField(QLineEdit):
    """A search's field: Enter emits `stepped`, with Shift for backwards; Escape clears it."""

    stepped = Signal(bool)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.stepped.emit(bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier))
        elif event.key() == Qt.Key.Key_Escape:
            self.clear()
        else:
            super().keyPressEvent(event)


class QConsoleBox(QWidget):
    """A `QConsole` under its controls: a search at the left, Copy and Save at the right.

    `search` and the count of its `matches` first; `copy` and `save` at the right, as a
    large table's export.
    """

    def __init__(self) -> None:
        super().__init__()
        self.text = QConsole()
        self.search = QSearchField()
        self.search.setClearButtonEnabled(True)
        self.matches = plain_label()
        self.copy = QToolButton()
        self.save = QToolButton()
        controls = QHBoxLayout()
        controls.addWidget(self.search)
        controls.addWidget(self.matches)
        controls.addStretch(1)
        for button in (self.copy, self.save):
            button.setAutoRaise(True)
            controls.addWidget(button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(controls)
        layout.addWidget(self.text, 1)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.search.textChanged.connect(self.text.set_query)
        self.search.stepped.connect(lambda is_backwards: self.text.step(is_backwards=is_backwards))

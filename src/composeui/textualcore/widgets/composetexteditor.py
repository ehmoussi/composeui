"""A text editor: plain text in a fixed-width font, its lines numbered, never wrapped."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from rich.style import Style
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Input, Label, TextArea
from textual_fspicker import FileSave
from typing_extensions import override

from composeui.core._views.content import follow_match
from composeui.core._views.inputs import HIGHLIGHT_COLORS, highlight_lines
from composeui.core.signal import Signal
from composeui.core.view import find_in_lines
from composeui.textualcore.widgets.composetextarea import ComposeTextArea

if TYPE_CHECKING:
    from pathlib import Path

    from rich.text import Text
    from textual import events
    from textual.app import ComposeResult

    from composeui.core._views.inputs import Lexer

#: a match of the search, then the current one: black on amber, as the console's
_MATCH_STYLE = Style(color="black", bgcolor="#fde68a")
_CURRENT_STYLE = Style(color="black", bgcolor="#f59e0b")


class ComposeTextEditor(ComposeTextArea):
    """A `ComposeTextArea` for a file's text: its lines numbered, never wrapped.

    Tab indents by four spaces, and Escape moves the focus out (Textual's `TextArea`).

    `set_query` highlights the matches of a search (`find_in_lines`), and shows the first;
    `step` shows the next, or the previous, around the ends. An edit keeps the current
    match, or the next one if it went (`follow_match`). `matches_changed` emits the current
    match's number, from 1, and the count: 0 and 0 without a match.
    """

    DEFAULT_CSS = """
    ComposeTextEditor {
        height: 1fr;
    }
    """

    def __init__(self) -> None:
        # no cursor's line drawn: it would paint over the matches on that line
        super().__init__(
            soft_wrap=False,
            tab_behavior="indent",
            show_line_numbers=True,
            highlight_cursor_line=False,
        )
        self.indent_width = 4
        self._query = ""
        #: the index of the current match, in the matches
        self._current = 0
        #: the current match: its line and its start
        self._current_match: tuple[int, int] | None = None
        self.matches_changed: Signal[int, int] = Signal()
        #: the language of its syntax's colors (`highlight_lines`); not `TextArea.language`,
        #: whose colors need tree-sitter
        self._syntax: str | Lexer | None = None
        #: each line's colored parts
        self._parts: list[list[tuple[int, int, str]]] = []

    def set_syntax(self, language: str | Lexer | None) -> None:
        """Color the text's syntax in `language`, as `highlight_lines` splits it."""
        self._syntax = language
        self.color_syntax()

    def color_syntax(self) -> None:
        """Split the text again, as it is now, for its colors."""
        self._parts = highlight_lines(self.text, self._syntax)
        self.notify_style_update()  # the lines drawn before, in the colors before
        self.refresh()

    @override
    def get_line(self, line_index: int) -> Text:
        line = super().get_line(line_index)
        is_dark = self.app.current_theme.dark
        # the text may have changed since its last split, which its `Changed` message runs
        parts = self._parts[line_index] if line_index < len(self._parts) else []
        for start, end, kind in parts:
            line.stylize(HIGHLIGHT_COLORS[kind][is_dark], start, end)
        for _, start, end in find_in_lines([line.plain], self._query):
            is_current = self._current_match == (line_index, start)
            line.stylize(_CURRENT_STYLE if is_current else _MATCH_STYLE, start, end)
        return line

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

    @override
    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if self._syntax is not None:
            self.color_syntax()
        if self._query != "":  # the matches move with the text
            self._show_matches(is_moved=False)
        super().on_text_area_changed(event)

    def _matches(self) -> list[tuple[int, int, int]]:
        return find_in_lines(self.document.lines, self._query)

    def _show_matches(self, *, is_moved: bool) -> None:
        """Highlight the matches, and show the current one if `is_moved`."""
        matches = self._matches()
        if self._current_match is not None:  # the text changed
            self._current = follow_match(matches, 0, self._current_match)
        self._current = min(self._current, max(len(matches) - 1, 0))
        current = matches[self._current] if matches else None
        self._current_match = None if current is None else current[:2]
        self.notify_style_update()  # the lines drawn before, with the matches before
        self.refresh()
        if is_moved and self._current_match is not None:
            self.move_cursor(self._current_match, center=True)
        self.matches_changed.emit(self._current + 1 if matches else 0, len(matches))


class ComposeTextEditorBox(Vertical):
    """A `ComposeTextEditor` under a row: its `file_name`, a search, the caret's place, Copy, Save.

    Ctrl+F goes to the search. In it, typing searches, Enter shows the next match, and
    Escape clears it and goes back to the text. `matches` shows their count. Save asks
    where to save the text, in textual-fspicker's save dialog, and `save_path_chosen`
    emits the path chosen. Copy copies the whole text to the clipboard, as the terminal
    lets an app (`App.copy_to_clipboard`).
    """

    DEFAULT_CSS = """
    ComposeTextEditorBox {
        height: 1fr;
        & > Horizontal {
            height: 1;
            margin-bottom: 1;
            & > Label { padding: 0 1; }
            & > #file-name { text-style: bold; padding-left: 0; }
            & > Input { width: 1fr; max-width: 40; margin-left: 2; }
            & > #matches { width: 1fr; }
            & > #position { color: $text-muted; }
            & > Button { margin-left: 1; }
        }
    }
    """
    BINDINGS: ClassVar[list[BindingType]] = [Binding("ctrl+f", "search", "Search")]

    def __init__(self) -> None:
        super().__init__()
        self.editor = ComposeTextEditor()
        self.file_name = Label(markup=False, id="file-name")
        self.search = Input(compact=True)
        self.matches = Label(markup=False, id="matches")
        self.position = Label(markup=False, id="position")
        self.copy = Button(compact=True)
        self.save = Button(compact=True)
        self._position_text = ""
        self.save_path_chosen: Signal[Path] = Signal()
        #: the name the save dialog offers
        self.export_filename = "text.txt"

    @override
    def compose(self) -> ComposeResult:
        with Horizontal():
            yield self.file_name
            yield self.search
            yield self.matches
            yield self.position
            yield self.copy
            yield self.save
        yield self.editor

    def show_position(self, text: str) -> None:
        """Write the caret's place in `text`'s words, e.g. "Line {line}, column {column}"."""
        self._position_text = text
        self._show_position()

    def on_text_area_selection_changed(self, event: TextArea.SelectionChanged) -> None:
        event.stop()
        self._show_position()

    def _show_position(self) -> None:
        line, column = self.editor.cursor_location
        self.position.update(self._position_text.format(line=line + 1, column=column + 1))

    def set_search_text(self, text: str) -> None:
        """Name the search, in its field and in the app's footer."""
        self.search.placeholder = text
        self._bindings.key_to_bindings.pop("ctrl+f", None)
        self._bindings.bind("ctrl+f", "search", text)
        self.refresh_bindings()

    def action_search(self) -> None:
        self.search.focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        event.stop()
        self.editor.set_query(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.editor.step()

    def on_key(self, event: events.Key) -> None:
        if event.key == "escape" and self.search.has_focus:
            event.stop()
            self.search.value = ""  # its highlights go
            self.editor.focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button is self.copy:
            self.app.copy_to_clipboard(self.editor.text)
        else:
            self.app.push_screen(FileSave(default_file=self.export_filename), self._save_chosen)

    def _save_chosen(self, path: Path | None) -> None:
        if path is not None:
            self.save_path_chosen.emit(path)

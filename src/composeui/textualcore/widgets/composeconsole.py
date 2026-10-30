from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from rich.cells import cell_len
from rich.highlighter import Highlighter
from rich.style import Style
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.geometry import Size
from textual.widgets import Input, Label, Log
from textual_fspicker import FileSave

from composeui.core.signal import Signal
from composeui.core.view import find_in_lines, follow_match

if TYPE_CHECKING:
    from pathlib import Path

    from rich.text import Text
    from textual.app import ComposeResult
    from textual.strip import Strip

#: the key asking where to save the text
SAVE_KEY = "s"
#: the key copying the whole text
COPY_KEY = "c"
#: a match of the search, then the current one: black on amber, as on Qt and the web
_MATCH_STYLE = Style(color="black", bgcolor="#fde68a")
_CURRENT_STYLE = Style(color="black", bgcolor="#f59e0b")


class _SearchHighlighter(Highlighter):
    """Highlight the matches of `query` in a console's line: `line`'s, its `current` one too."""

    def __init__(self) -> None:
        self.query = ""
        #: the line drawn, which a highlighter isn't told
        self.line = -1
        #: the current match: its line and its start
        self.current: tuple[int, int] | None = None

    def highlight(self, text: Text) -> None:
        for _, start, end in find_in_lines([text.plain], self.query):
            is_current = self.current == (self.line, start)
            text.stylize(_CURRENT_STYLE if is_current else _MATCH_STYLE, start, end)


class ComposeConsole(Log):
    """A `Log` whose last line is the one being written, which `add` replaces.

    `Log` only adds to its last line, and its `write_lines` drops empty lines. The console
    scrolls to its end as lines come only when the end was shown: `Log.write` scrolls
    whatever the user is reading. `set_max_lines` keeps that many lines, the line being
    written not counted. `SAVE_KEY` asks where to save the text, in textual-fspicker's
    save dialog, and `save_path_chosen` emits the path chosen. `COPY_KEY` copies the whole
    text to the clipboard, as the terminal lets an app (`App.copy_to_clipboard`).

    `set_query` highlights the matches of a search (`find_in_lines`, in the lines as
    shown), and shows the first; `step` shows the next, or the previous, around the ends.
    New lines keep the current match, or the next one if it went with the oldest lines
    (`follow_match`).
    `matches_changed` emits the current match's number, from 1, and the count: 0 and 0
    without a match.
    """

    def __init__(self) -> None:
        super().__init__(auto_scroll=False, highlight=True)
        self.highlighter = self._search = _SearchHighlighter()
        #: the index of the current match, in the matches
        self._current = 0
        #: the current match: its line's number, from the text's first line ever, its start
        self._current_match: tuple[int, int] | None = None
        #: the lines dropped since the text was set, the oldest ones
        self._dropped = 0
        self.matches_changed: Signal[int, int] = Signal()
        self.save_path_chosen: Signal[Path] = Signal()
        #: the name the save dialog offers
        self.export_filename = "output.txt"
        self.set_texts(save="Save output", copy="Copy all")

    def set_texts(self, *, save: str, copy: str) -> None:
        """Describe the keys saving and copying the text, e.g. in the app's footer."""
        for key, action, text in ((COPY_KEY, "copy_all", copy), (SAVE_KEY, "save", save)):
            self._bindings.key_to_bindings.pop(key, None)
            self._bindings.bind(key, action, text)
        self.refresh_bindings()

    def action_copy_all(self) -> None:
        # its lines are the text's, the line being written last
        self.app.copy_to_clipboard("\n".join(self._lines))

    def action_save(self) -> None:
        self.app.push_screen(FileSave(default_file=self.export_filename), self._save_path_chosen)

    def _save_path_chosen(self, path: Path | None) -> None:
        if path is not None:
            self.save_path_chosen.emit(path)

    def set_max_lines(self, count: int) -> None:
        before = len(self._lines)
        self.max_lines = count + 1
        self._prune_max_lines()
        self._dropped += before - len(self._lines)
        self.virtual_size = Size(self._width, len(self._lines))
        self.refresh()

    def set_text(self, text: str) -> None:
        """Show `text` instead, from its end."""
        self.clear()
        self._dropped = 0
        *lines, last_line = text.split("\n")
        self.add(lines, last_line)
        self.scroll_end(animate=False, immediate=True, x_axis=False)

    def add(self, lines: list[str], last_line: str) -> None:
        """End the line being written with `lines`, then write `last_line` in its place."""
        is_at_end = self.is_vertical_scroll_end
        new = [*lines, last_line]
        self._lines[max(len(self._lines) - 1, 0) :] = new
        shown = len(self._lines)
        self._prune_max_lines()
        self._dropped += shown - len(self._lines)
        width = max(cell_len(self._process_line(line)) for line in new)
        self._width = max(self._width, width)
        self.virtual_size = Size(self._width, len(self._lines))
        changed = min(len(new), len(self._lines))
        self.refresh_lines(len(self._lines) - changed, changed)
        if is_at_end:
            self.scroll_end(animate=False, immediate=True, x_axis=False)
        else:
            self.refresh()  # the oldest lines dropped move the others up
        self._show_matches(is_moved=False)

    def set_query(self, query: str) -> None:
        """Highlight the matches of `query`, and show the first."""
        self._search.query = query
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
        return find_in_lines([self._process_line(line) for line in self._lines], self._search.query)

    def _show_matches(self, *, is_moved: bool) -> None:
        """Highlight the matches, and show the current one if `is_moved`."""
        matches = self._matches()
        if self._current_match is not None:  # lines came or went
            self._current = follow_match(matches, self._dropped, self._current_match)
        self._current = min(self._current, max(len(matches) - 1, 0))
        current = matches[self._current] if matches else None
        if current is not None:
            self._current_match = (self._dropped + current[0], current[1])
        self._search.current = None if current is None else current[:2]
        self._render_line_cache.clear()
        self.refresh()
        if is_moved and current is not None:
            self.scroll_to(y=max(current[0] - self.size.height // 2, 0), animate=False)
        self.matches_changed.emit(self._current + 1 if matches else 0, len(matches))

    def _render_line_strip(self, y: int, rich_style: Style) -> Strip:
        self._search.line = y
        return super()._render_line_strip(y, rich_style)


class ComposeConsoleBox(Vertical):
    """A `ComposeConsole` under its search bar, which `/` shows and Escape hides.

    In the bar, typing searches and Enter shows the next match; `n` and `N` show the next
    and the previous one in the console too. `matches` shows their count.
    """

    DEFAULT_CSS = """
    ComposeConsoleBox {
        height: 1fr;
        & > Horizontal {
            height: auto;
            display: none;
            & > Input { width: 1fr; }
            & > Label { padding: 1 1 0 1; }
        }
        &.-searching > Horizontal { display: block; }
    }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("slash", "search", "Search"),
        Binding("escape", "close_search", show=False),
        Binding("n", "step", show=False),
        Binding("N", "step(True)", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.log_view = ComposeConsole()
        self.search = Input()
        self.matches = Label(markup=False)

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield self.search
            yield self.matches
        yield self.log_view

    def set_search_text(self, text: str) -> None:
        """Name the search, in its field and in the app's footer."""
        self.search.placeholder = text
        self._bindings.key_to_bindings.pop("slash", None)
        self._bindings.bind("slash", "search", text)
        self.refresh_bindings()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action in ("close_search", "step"):
            return self.has_class("-searching")
        return super().check_action(action, parameters)

    def action_search(self) -> None:
        self.add_class("-searching")
        self.search.focus()

    def action_close_search(self) -> None:
        self.remove_class("-searching")
        self.search.value = ""  # its highlights go
        self.log_view.focus()

    def action_step(self, is_backwards: bool = False) -> None:  # noqa: FBT002
        self.log_view.step(is_backwards=is_backwards)

    def on_input_changed(self, event: Input.Changed) -> None:
        event.stop()
        self.log_view.set_query(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.log_view.step()

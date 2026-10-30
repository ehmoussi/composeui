from __future__ import annotations

from typing import TYPE_CHECKING

from rich.cells import cell_len
from textual.geometry import Size
from textual.widgets import Log
from textual_fspicker import FileSave

from composeui.core.signal import Signal

if TYPE_CHECKING:
    from pathlib import Path

#: the key asking where to save the text
SAVE_KEY = "s"
#: the key copying the whole text
COPY_KEY = "c"


class ComposeConsole(Log):
    """A `Log` whose last line is the one being written, which `add` replaces.

    `Log` only adds to its last line, and its `write_lines` drops empty lines. The console
    scrolls to its end as lines come only when the end was shown: `Log.write` scrolls
    whatever the user is reading. `set_max_lines` keeps that many lines, the line being
    written not counted. `SAVE_KEY` asks where to save the text, in textual-fspicker's
    save dialog, and `save_path_chosen` emits the path chosen. `COPY_KEY` copies the whole
    text to the clipboard, as the terminal lets an app (`App.copy_to_clipboard`).
    """

    def __init__(self) -> None:
        super().__init__(auto_scroll=False)
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
        self.max_lines = count + 1
        self._prune_max_lines()
        self.virtual_size = Size(self._width, len(self._lines))
        self.refresh()

    def set_text(self, text: str) -> None:
        """Show `text` instead, from its end."""
        self.clear()
        *lines, last_line = text.split("\n")
        self.add(lines, last_line)
        self.scroll_end(animate=False, immediate=True, x_axis=False)

    def add(self, lines: list[str], last_line: str) -> None:
        """End the line being written with `lines`, then write `last_line` in its place."""
        is_at_end = self.is_vertical_scroll_end
        new = [*lines, last_line]
        self._lines[max(len(self._lines) - 1, 0) :] = new
        self._prune_max_lines()
        width = max(cell_len(self._process_line(line)) for line in new)
        self._width = max(self._width, width)
        self.virtual_size = Size(self._width, len(self._lines))
        changed = min(len(new), len(self._lines))
        self.refresh_lines(len(self._lines) - changed, changed)
        if is_at_end:
            self.scroll_end(animate=False, immediate=True, x_axis=False)
        else:
            self.refresh()  # the oldest lines dropped move the others up

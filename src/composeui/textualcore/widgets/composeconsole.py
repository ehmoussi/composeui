from __future__ import annotations

from rich.cells import cell_len
from textual.geometry import Size
from textual.widgets import Log


class ComposeConsole(Log):
    """A `Log` whose last line is the one being written, which `add` replaces.

    `Log` only adds to its last line, and its `write_lines` drops empty lines. The console
    scrolls to its end as lines come only when the end was shown: `Log.write` scrolls
    whatever the user is reading. `set_max_lines` keeps that many lines, the line being
    written not counted.
    """

    def __init__(self) -> None:
        super().__init__(auto_scroll=False)

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

"""textual-fspicker's file picker, with marks: several files of one folder at once."""

from __future__ import annotations

import weakref
from typing import TYPE_CHECKING, ClassVar

from rich.table import Table
from textual import events, on
from textual.binding import Binding
from textual.widgets import Button, Input
from textual_fspicker import FileOpen
from textual_fspicker.parts import DirectoryNavigation
from textual_fspicker.parts.directory_navigation import DirectoryEntry

if TYPE_CHECKING:
    from pathlib import Path

    from textual.binding import BindingType
    from textual.visual import VisualType


def _replace_prompt(navigation: DirectoryNavigation, index: int, prompt: VisualType) -> None:
    """Show `prompt` as the row of the entry at `index`, measuring that row only.

    The public `replace_option_prompt_at_index` clears the list's caches, so the next frame
    measures every row again: seconds for a folder of thousands of files, at each mark.
    """
    option = navigation.get_option_at_index(index)
    try:
        # (one row's redraw: Textual has no public call for it)
        cache = navigation._option_render_cache  # noqa: SLF001
        option._set_prompt(prompt)  # noqa: SLF001
        # a marked row keeps the height of its own: one line, its columns cut, not wrapped
        for key in [key for key in cache.keys() if key[0] is option]:  # noqa: SIM118 (an LRUCache)
            cache.discard(key)
    except AttributeError:  # pragma: no cover (a Textual without them: slower, still right)
        navigation.replace_option_prompt_at_index(index, prompt)
        return
    navigation.refresh()


class ComposeFilesOpen(FileOpen):
    """A file picker that also gives several files of one folder.

    Space, or Ctrl+click, marks the file under the cursor, or unmarks it: a ✓ shows before it,
    and the name field lists the marked files. Open then gives them, in the order marked, in a
    tuple. Without marks, it gives the file named in the field, as `FileOpen` does. Going to
    another folder, or typing a name, drops the marks; a filter, or hidden files hidden again,
    drop those of the files they hide.
    """

    BINDINGS: ClassVar[list[BindingType]] = [Binding("space", "toggle_mark", "Mark")]

    def __init__(self, location: Path, title: str, **kwargs: object) -> None:
        super().__init__(location, title, **kwargs)  # type: ignore[arg-type]
        #: the marked files, in the order marked, all in the folder shown
        self._marked: list[Path] = []
        #: each entry's own row, before a mark replaced it
        self._plain: weakref.WeakKeyDictionary[DirectoryEntry, VisualType] = (
            weakref.WeakKeyDictionary()
        )
        #: whether the last press of the mouse held Ctrl: a click then marks, not picks
        self._is_ctrl_down = False

    @on(events.Mount)
    def _watch_lists(self) -> None:
        navigation = self.query_one(DirectoryNavigation)
        # each repopulates the list, with the entries that it shows
        self.watch(navigation, "file_filter", self._keep_shown_marks, init=False)
        self.watch(navigation, "show_hidden", self._keep_shown_marks, init=False)

    def action_toggle_mark(self) -> None:
        """Mark the file under the cursor, or unmark it; nothing on a folder, or a file gone."""
        navigation = self.query_one(DirectoryNavigation)
        index = navigation.highlighted
        if not navigation.has_focus or index is None:
            return
        entry = navigation.get_option_at_index(index)
        assert isinstance(entry, DirectoryEntry)  # the list holds only these
        if entry.location in self._marked:
            # even a file gone since: its mark would keep Open refusing the choice
            self._marked.remove(entry.location)
        elif entry.location.is_file():
            self._marked.append(entry.location)
        else:
            return
        self._show_row(index, entry)
        self._show_names()

    def _show_row(self, index: int, entry: DirectoryEntry) -> None:
        plain = self._plain.setdefault(entry, entry.prompt)
        if entry.location in self._marked:
            prompt = Table.grid(expand=True)
            prompt.add_column(width=2, no_wrap=True)
            prompt.add_column(ratio=1)
            prompt.add_row("✓", plain)  # type: ignore[arg-type]
            _replace_prompt(self.query_one(DirectoryNavigation), index, prompt)
        elif entry.prompt is not plain:
            _replace_prompt(self.query_one(DirectoryNavigation), index, plain)

    def _show_marks(self) -> None:
        """Show each row as marked or not, changing only those that differ."""
        navigation = self.query_one(DirectoryNavigation)
        for index in range(navigation.option_count):
            entry = navigation.get_option_at_index(index)
            assert isinstance(entry, DirectoryEntry)  # the list holds only these
            if entry.location in self._marked or entry in self._plain:
                self._show_row(index, entry)

    def _show_names(self) -> None:
        file_name = self.query_one(Input)
        with file_name.prevent(Input.Changed):
            file_name.value = " ".join(f'"{path.name}"' for path in self._marked)

    def on_mouse_down(self, event: events.MouseDown) -> None:
        self._is_ctrl_down = event.ctrl

    def on_key(self, _event: events.Key) -> None:
        self._is_ctrl_down = False

    @on(DirectoryNavigation.Selected)
    def _mark_clicked(self, event: DirectoryNavigation.Selected) -> None:
        if self._is_ctrl_down:
            self._is_ctrl_down = False
            # the base's handler would put this file alone in the name field
            event.prevent_default()
            self.action_toggle_mark()

    @on(Input.Changed)
    def _forget_marks(self) -> None:
        # a name typed, or a file picked alone: it's the choice
        self._marked.clear()
        self._show_marks()

    @on(DirectoryNavigation.Changed)
    def _drop_marks(self) -> None:
        # one folder per choice: the list is made again of new entries
        if self._marked:
            self._marked.clear()
            self._show_names()

    def _keep_shown_marks(self) -> None:
        navigation = self.query_one(DirectoryNavigation)
        shown = [path for path in self._marked if not navigation.hide(path)]
        if shown != self._marked:
            self._marked = shown
            self._show_names()
        self._show_marks()

    @on(Input.Submitted)
    @on(Button.Pressed, "#select")
    def _open_marked(self, event: Input.Submitted | Button.Pressed) -> None:
        if not self._marked:
            return  # the base's handler opens the file named in the field
        event.prevent_default()
        event.stop()
        if not all(path.is_file() for path in self._marked):
            self._set_error(self.ERROR_A_FILE_MUST_EXIST)
            return
        self.dismiss(tuple(self._marked))  # type: ignore[arg-type]

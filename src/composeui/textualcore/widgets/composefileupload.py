from __future__ import annotations

from typing import TYPE_CHECKING

from textual.containers import Horizontal
from textual.widgets import Button, Label

from composeui.core.signal import Signal
from composeui.textualcore.widgets.composefilepathinput import file_picker, files_picker

if TYPE_CHECKING:
    from pathlib import Path


class ComposeFileUpload(Horizontal):
    """A button picking a file with textual-fspicker's picker, then the file's name.

    With `multiple`, the picker marks several files of one folder (`ComposeFilesOpen`).
    """

    DEFAULT_CSS = """
    ComposeFileUpload {
        height: auto;
        & > Label {
            padding: 1;
        }
    }
    """

    def __init__(self) -> None:
        self.button = Button()
        self.name_label = Label(markup=False)
        super().__init__(self.button, self.name_label)
        #: the file types the picker offers, by name, as the view's `extensions`
        self.extensions: dict[str, tuple[str, ...]] = {}
        #: whether the picker gives several files, as the view's `multiple`
        self.multiple = False
        #: the files picked, in the order given: one without `multiple`
        self.files_picked: Signal[tuple[Path, ...]] = Signal()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        title = str(self.button.label)
        if self.multiple:
            self.app.push_screen(files_picker(self.extensions, title), self._pick)
        else:
            self.app.push_screen(file_picker("", self.extensions, title), self._pick)

    def _pick(self, picked: Path | tuple[Path, ...] | None) -> None:
        if picked is not None:
            self.files_picked.emit(picked if isinstance(picked, tuple) else (picked,))
        self.button.focus()

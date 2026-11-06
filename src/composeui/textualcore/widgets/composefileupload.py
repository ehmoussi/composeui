from __future__ import annotations

from typing import TYPE_CHECKING

from textual.containers import Horizontal
from textual.widgets import Button, Label

from composeui.core.signal import Signal
from composeui.textualcore.widgets.composefilepathinput import file_picker

if TYPE_CHECKING:
    from pathlib import Path


class ComposeFileUpload(Horizontal):
    """A button picking a file with textual-fspicker's picker, then the file's name."""

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
        self.file_picked: Signal[Path] = Signal()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.app.push_screen(file_picker("", self.extensions, str(self.button.label)), self._pick)

    def _pick(self, path: Path | None) -> None:
        if path is not None:
            self.file_picked.emit(path)
        self.button.focus()

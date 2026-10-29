from __future__ import annotations

import functools
from pathlib import Path

from textual.containers import Horizontal
from textual.widgets import Button
from textual_fspicker import FileOpen
from textual_fspicker.path_filters import Filter, Filters

from composeui.core.signal import Signal, SignalNoArgs
from composeui.textualcore.widgets.composeinput import ComposeInput


def _has_any_extension(path: Path, extensions: tuple[str, ...]) -> bool:
    return any(path.name.endswith(extension) for extension in extensions)


def file_picker(
    text: str, extensions: dict[str, tuple[str, ...]], title: str, start: Path | None = None
) -> FileOpen:
    """Get a picker of the files of `extensions`, opening in the directory of `text`'s path.

    In `start` if `text` is empty, else in the current directory, as for no directory's
    path.
    """
    text = text.strip()
    location = Path(text).parent if text != "" else (start or Path())
    if not location.is_dir():  # e.g. a path typed halfway
        location = Path()
    filters = Filters(
        *(
            Filter(name, functools.partial(_has_any_extension, extensions=name_extensions))
            for name, name_extensions in extensions.items()
        )
    )
    return FileOpen(location, title or "Open", filters=filters)


class ComposeFilePathInput(Horizontal):
    """A field typing a file's path, then a "…" button picking one, and a reload button.

    The picker is textual-fspicker's, a screen of its own, opening in the directory of
    the field's path, if any, else in `start_folder`; `path_picked` reports the file
    picked, once the field shows it. The reload button only reports its presses, and shows
    with `has_reload`.
    """

    DEFAULT_CSS = """
    ComposeFilePathInput {
        height: auto;
        & > ComposeInput {
            width: 1fr;
        }
        & > Button {
            min-width: 5;
            width: 5;
        }
        &.-row-invalid > ComposeInput {
            border: tall $error 60%;
            &:focus {
                border: tall $error;
            }
        }
    }
    """

    def __init__(self) -> None:
        self.input = ComposeInput()
        self.browse_button = Button("…")
        self.reload_button = Button("↻")
        self.reload_button.display = False
        super().__init__(self.input, self.browse_button, self.reload_button)
        #: the file types the picker offers, by name, as the view's `extensions`
        self.extensions: dict[str, tuple[str, ...]] = {}
        #: the picker's title, the view's `browse_text`
        self.picker_title = ""
        #: where the picker opens while the field is empty, the view's first server root
        self.start_folder: Path | None = None
        self.path_picked: Signal[Path] = Signal()
        self.reload_pressed = SignalNoArgs()

    def open_picker(self) -> None:
        """Show the file picker in the directory of the field's path, else `start_folder`."""
        picker = file_picker(
            self.input.value, self.extensions, self.picker_title, self.start_folder
        )
        self.app.push_screen(picker, self._pick)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button is self.browse_button:
            self.open_picker()
        else:
            self.reload_pressed.emit()

    def _pick(self, path: Path | None) -> None:
        if path is not None:
            self.input.value = str(path)
            self.path_picked.emit(path)
        self.input.focus()

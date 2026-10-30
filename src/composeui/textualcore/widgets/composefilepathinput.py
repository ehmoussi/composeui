from __future__ import annotations

import functools
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Literal

from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label
from textual_fspicker import FileOpen, FileSave, SelectDirectory
from textual_fspicker.parts import DirectoryNavigation
from textual_fspicker.path_filters import Filter, Filters

from composeui.core.signal import Signal, SignalNoArgs
from composeui.core.view import with_extension
from composeui.textualcore.widgets.composeinput import ComposeInput

if TYPE_CHECKING:
    from textual.app import ComposeResult
    from textual.binding import BindingType
    from textual_fspicker.parts.directory_navigation import DirectoryEntryStyling

#: what the picker picks: a file to open, a folder, or a file to save
PickerKind = Literal["file", "folder", "save"]

#: how textual-fspicker's folder list reads the styles of its entries
_read_entry_styles = vars(DirectoryNavigation)["_styles"].fget


def _entry_styles(navigation: DirectoryNavigation) -> DirectoryEntryStyling:
    """Read the styles of a folder list's entries on the app's thread.

    textual-fspicker's `_load` worker reads them from its own thread, while the app's may be
    applying the list's styles again, a theme changed or a test's parallel load: Textual
    empties a widget's component styles, then fills them anew. Read in between, a style is
    missing (a `KeyError`). The worker waits for the app's thread, as it does already to
    show the entries it read (`call_from_thread`).
    """
    try:
        styles: DirectoryEntryStyling = navigation.app.call_from_thread(
            _read_entry_styles, navigation
        )
    except RuntimeError:  # on the app's thread already, or the app has stopped
        return _read_entry_styles(navigation)
    return styles


# no hook in textual-fspicker 0.6.0 for this: its `_styles` property, replaced
setattr(DirectoryNavigation, "_styles", property(_entry_styles))  # noqa: B010


def _has_any_extension(path: Path, extensions: tuple[str, ...]) -> bool:
    return any(path.name.endswith(extension) for extension in extensions)


def _filters(extensions: dict[str, tuple[str, ...]]) -> Filters:
    return Filters(
        *(
            Filter(name, functools.partial(_has_any_extension, extensions=name_extensions))
            for name, name_extensions in extensions.items()
        )
    )


def _parent_folder(text: str, start: Path | None) -> Path:
    """Get the directory of `text`'s path, else `start`; else the current directory."""
    location = Path(text).parent if text != "" else (start or Path())
    return location if location.is_dir() else Path()  # e.g. a path typed halfway


def file_picker(
    text: str, extensions: dict[str, tuple[str, ...]], title: str, start: Path | None = None
) -> FileOpen:
    """Get a picker of the files of `extensions`, opening in the directory of `text`'s path.

    In `start` if `text` is empty, else in the current directory, as for no directory's
    path.
    """
    location = _parent_folder(text.strip(), start)
    return FileOpen(location, title or "Open", filters=_filters(extensions))


def save_picker(
    text: str, extensions: dict[str, tuple[str, ...]], title: str, start: Path | None = None
) -> FileSave:
    """Get a picker of a file to save, opening on `text`'s path, as `file_picker` does.

    It replaces a file without asking: `ComposeFilePathInput` asks.
    """
    text = text.strip()
    return FileSave(
        _parent_folder(text, start),
        title or "Save as",
        filters=_filters(extensions),
        default_file=Path(text).name if text != "" else None,
    )


def folder_picker(text: str, title: str, start: Path | None = None) -> SelectDirectory:
    """Get a picker of a folder, opening in `text`'s folder, else in `start`.

    In the current directory if neither is a folder.
    """
    text = text.strip()
    location = Path(text) if text != "" else (start or Path())
    if not location.is_dir():  # e.g. a path typed halfway
        location = Path()
    return SelectDirectory(location, title or "Select")


class ReplaceFileScreen(ModalScreen[bool]):
    """Ask whether to replace a file that exists: True for its replace button."""

    DEFAULT_CSS = """
    ReplaceFileScreen {
        align: center middle;
        & > Vertical {
            width: auto;
            height: auto;
            padding: 1 2;
            border: thick $primary 50%;
            background: $surface;
        }
        & Horizontal {
            width: auto;
            height: auto;
            margin-top: 1;
        }
    }
    """
    BINDINGS: ClassVar[list[BindingType]] = [Binding("escape", "keep", show=False)]

    def __init__(self, question: str, replace_text: str, cancel_text: str) -> None:
        super().__init__()
        self.question = Label(question)
        self.cancel_button = Button(cancel_text)
        self.replace_button = Button(replace_text, variant="warning")

    def compose(self) -> ComposeResult:
        with Vertical():
            yield self.question
            with Horizontal():
                yield self.cancel_button
                yield self.replace_button

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(event.button is self.replace_button)

    def action_keep(self) -> None:
        self.dismiss(result=False)


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

    def __init__(self, *, kind: PickerKind = "file") -> None:
        #: what the picker picks (textual-fspicker's `FileOpen`, `SelectDirectory`, `FileSave`)
        self.kind = kind
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
        #: for a file to save: whether to ask before replacing one, and the question's texts
        self.confirms_overwrite = True
        self.replace_question = "{name}"
        self.replace_text = ""
        self.cancel_text = ""
        self.path_picked: Signal[Path] = Signal()
        self.reload_pressed = SignalNoArgs()

    def open_picker(self) -> None:
        """Show the picker in the directory of the field's path, else `start_folder`."""
        picker: FileOpen | SelectDirectory | FileSave
        text, title, start = self.input.value, self.picker_title, self.start_folder
        if self.kind == "folder":
            picker = folder_picker(text, title, start)
        elif self.kind == "save":
            picker = save_picker(text, self.extensions, title, start)
        else:
            picker = file_picker(text, self.extensions, title, start)
        self.app.push_screen(picker, self._pick)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button is self.browse_button:
            self.open_picker()
        else:
            self.reload_pressed.emit()

    def _pick(self, path: Path | None) -> None:
        if path is not None and self.kind == "save":
            path = with_extension(path, self.extensions)
            if self.confirms_overwrite and path.exists():
                question = ReplaceFileScreen(
                    self.replace_question.format(name=path.name),
                    self.replace_text,
                    self.cancel_text,
                )
                self.app.push_screen(question, functools.partial(self._replace, path))
                return
        self._take(path)

    def _replace(self, path: Path, is_replaced: bool | None) -> None:
        self._take(path if is_replaced else None)

    def _take(self, path: Path | None) -> None:
        if path is not None:
            self.input.value = str(path)
            self.path_picked.emit(path)
        self.input.focus()

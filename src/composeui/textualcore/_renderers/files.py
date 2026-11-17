"""Textual file, folder and upload fields."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, TypeVar

from textual.content import Content
from typing_extensions import Protocol

from composeui.core.renderer import ViewLike
from composeui.core.view import UploadedFile
from composeui.textualcore._renderers.inputs import InputViewLike
from composeui.textualcore.textualrenderer import TextualWidgetRenderer
from composeui.textualcore.widgets.composefilepathinput import ComposeFilePathInput, PickerKind
from composeui.textualcore.widgets.composefileupload import ComposeFileUpload

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from composeui.core.signal import Signal, SignalNoArgs


def _has_any_extension(filepath: Path, extensions: tuple[str, ...]) -> bool:
    return any(filepath.name.endswith(extension) for extension in extensions)


#: the texts of the web's list of the server's files, which Textual doesn't show
_SERVER_LIST_TEXTS = (
    "parent_folder_text",
    "cancel_text",
    "unreadable_folder_text",
    "partial_folder_text",
)


class PathInputViewLike(InputViewLike, Protocol):
    server_roots: tuple[Path, ...]
    base_folder: Path | None
    browse_text: str
    path_picked: Signal[Path]

    def path_text(self, path: Path) -> str: ...


class FilePathInputViewLike(PathInputViewLike, Protocol):
    extensions: dict[str, tuple[str, ...]]
    has_reload: bool
    reload_text: str
    reload_clicked: SignalNoArgs


TPathView = TypeVar("TPathView", bound=PathInputViewLike)


def _start_folder(base_folder: Path | None, roots: tuple[Path, ...]) -> Path | None:
    """Get where a picker opens while its field is empty (see `PathInputMixin.start_folder`)."""
    return base_folder.expanduser() if base_folder is not None else (roots[0] if roots else None)


class _TextualPathInputRenderer(TextualWidgetRenderer[TPathView, ComposeFilePathInput]):
    """A field typing a path, then a "…" button opening textual-fspicker's picker."""

    _marks_invalid = True
    #: what its picker picks
    _kind: ClassVar[PickerKind] = "file"

    def __init__(self, view: TPathView) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "text": self._refresh_text,
                "placeholder": self._refresh_placeholder,
                "browse_text": self._refresh_browse_text,
                "server_roots": self._refresh_server_roots,
                "base_folder": self._refresh_base_folder,
                # the web's list of the server's files only
                **dict.fromkeys(_SERVER_LIST_TEXTS, lambda _view, _widget, _value: None),
            }
        )

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = ComposeFilePathInput(kind=self._kind)
            self._rendered_object.input.value_changed.connect(self._update_text)
            self._rendered_object.input.value_submitted.connect(self._view.editing_finished.emit)
            self._rendered_object.path_picked.connect(self._pick)

    @staticmethod
    def _refresh_text(_view: TPathView, rendered_object: ComposeFilePathInput, value: str) -> None:
        rendered_object.input.value = value

    @staticmethod
    def _refresh_placeholder(
        _view: TPathView, rendered_object: ComposeFilePathInput, value: str
    ) -> None:
        rendered_object.input.placeholder = value

    @staticmethod
    def _refresh_browse_text(
        _view: TPathView, rendered_object: ComposeFilePathInput, value: str
    ) -> None:
        rendered_object.browse_button.tooltip = Content(value)
        rendered_object.picker_title = value

    # each called before the view holds `value`: its `start_folder` would read the old one
    @staticmethod
    def _refresh_server_roots(
        view: TPathView, rendered_object: ComposeFilePathInput, value: tuple[Path, ...]
    ) -> None:
        rendered_object.start_folder = _start_folder(view.base_folder, value)

    @staticmethod
    def _refresh_base_folder(
        view: TPathView, rendered_object: ComposeFilePathInput, value: Path | None
    ) -> None:
        rendered_object.base_folder = value
        rendered_object.start_folder = _start_folder(value, view.server_roots)

    def _update_text(self, text: str) -> None:
        with self.stop_refresh():
            self._view.text = text
        self._view.text_changed.emit(text)
        self._view.text_edited.emit(text)

    def _pick(self, path: Path) -> None:
        # the field's change arrives later, as a message: the view has the path first
        with self.stop_refresh():
            self._view.text = self._view.path_text(path)
        self._view.path_picked.emit(path)


class TextualFilePathInputRenderer(_TextualPathInputRenderer[FilePathInputViewLike]):
    """A field typing a file's path, then a "…" button opening textual-fspicker's picker."""

    def __init__(self, view: FilePathInputViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "extensions": self._refresh_extensions,
                "has_reload": self._refresh_has_reload,
                "reload_text": self._refresh_reload_text,
            }
        )

    def render(self) -> None:
        is_new = self._rendered_object is None
        super().render()
        if is_new:
            assert self._rendered_object is not None
            self._rendered_object.reload_pressed.connect(self._view.reload_clicked.emit)

    @staticmethod
    def _refresh_extensions(
        _view: FilePathInputViewLike,
        rendered_object: ComposeFilePathInput,
        value: dict[str, tuple[str, ...]],
    ) -> None:
        rendered_object.extensions = dict(value)

    @staticmethod
    def _refresh_has_reload(
        _view: FilePathInputViewLike, rendered_object: ComposeFilePathInput, value: bool
    ) -> None:
        rendered_object.reload_button.display = value

    @staticmethod
    def _refresh_reload_text(
        _view: FilePathInputViewLike, rendered_object: ComposeFilePathInput, value: str
    ) -> None:
        rendered_object.reload_button.tooltip = Content(value)


class FileUploadViewLike(ViewLike, Protocol):
    extensions: dict[str, tuple[str, ...]]
    browse_text: str
    empty_text: str
    file: UploadedFile | None

    def take_file(self, file: UploadedFile) -> None: ...


class TextualFileUploadRenderer(TextualWidgetRenderer[FileUploadViewLike, ComposeFileUpload]):
    """A button opening textual-fspicker's picker, then the file's name: never a copy."""

    def __init__(self, view: FileUploadViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "browse_text": self._refresh_browse_text,
                "empty_text": self._refresh_empty_text,
                "file": self._refresh_file,
                "extensions": self._refresh_extensions,
                # the web's only: here, the file needs no upload
                "uploading_text": lambda _view, _widget, _value: None,
            }
        )

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = ComposeFileUpload()
            self._rendered_object.file_picked.connect(self._take_path)

    def _take_path(self, path: Path) -> None:
        self._view.take_file(UploadedFile.of_path(path))

    @staticmethod
    def _refresh_browse_text(
        _view: FileUploadViewLike, rendered_object: ComposeFileUpload, value: str
    ) -> None:
        rendered_object.button.label = value

    @staticmethod
    def _refresh_file(
        view: FileUploadViewLike, rendered_object: ComposeFileUpload, value: UploadedFile | None
    ) -> None:
        # called before the view holds the value
        rendered_object.name_label.update(view.empty_text if value is None else value.name)

    @staticmethod
    def _refresh_empty_text(
        view: FileUploadViewLike, rendered_object: ComposeFileUpload, value: str
    ) -> None:
        if view.file is None:
            rendered_object.name_label.update(value)

    @staticmethod
    def _refresh_extensions(
        _view: FileUploadViewLike,
        rendered_object: ComposeFileUpload,
        value: dict[str, tuple[str, ...]],
    ) -> None:
        rendered_object.extensions = dict(value)


class SavePathInputViewLike(PathInputViewLike, Protocol):
    extensions: dict[str, tuple[str, ...]]
    confirms_overwrite: bool
    replace_question_text: str
    replace_text: str
    cancel_text: str

    def remember_pick(self, path: Path) -> None: ...


class TextualSavePathInputRenderer(_TextualPathInputRenderer[SavePathInputViewLike]):
    """A field typing a path to save a file to, then a "…" button opening a save picker.

    textual-fspicker's, asking before replacing a file (see `ComposeFilePathInput`). The
    view remembers a file the user agreed to replace (`remember_pick`).
    """

    _kind = "save"

    def __init__(self, view: SavePathInputViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "extensions": self._refresh_extensions,
                "confirms_overwrite": self._refresh_widget("confirms_overwrite"),
                "replace_question_text": self._refresh_widget("replace_question"),
                "replace_text": self._refresh_widget("replace_text"),
                "cancel_text": self._refresh_widget("cancel_text"),
                # the web's list only
                **dict.fromkeys(
                    ("file_name_text", "save_text"), lambda _view, _widget, _value: None
                ),
            }
        )

    def _pick(self, path: Path) -> None:
        # the widget asked about a file that exists, unless `confirms_overwrite` is off
        self._view.remember_pick(path)
        super()._pick(path)

    @staticmethod
    def _refresh_widget(
        name: str,
    ) -> Callable[[SavePathInputViewLike, ComposeFilePathInput, Any], None]:
        """Get a handler giving the widget's attribute `name` the view's value."""
        return lambda _view, widget, value: setattr(widget, name, value)

    @staticmethod
    def _refresh_extensions(
        _view: SavePathInputViewLike,
        rendered_object: ComposeFilePathInput,
        value: dict[str, tuple[str, ...]],
    ) -> None:
        rendered_object.extensions = dict(value)


class TextualFolderPathInputRenderer(_TextualPathInputRenderer[PathInputViewLike]):
    """A field typing a folder's path, then a "…" button opening textual-fspicker's picker."""

    _kind = "folder"

    def __init__(self, view: PathInputViewLike) -> None:
        super().__init__(view)
        # the web's list of the server's folders only
        self._refresh_dispatcher["choose_folder_text"] = lambda _view, _widget, _value: None

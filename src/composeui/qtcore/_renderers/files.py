"""Qt renderers for paths and uploads, with their file-dialog helpers."""

from __future__ import annotations

import functools
from abc import abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar

from qtpy.QtCore import QSignalBlocker
from qtpy.QtWidgets import QFileDialog, QMessageBox, QWidget
from typing_extensions import Protocol, override

from composeui.core._views.files import upload_summary, with_extension
from composeui.core.renderer import ViewLike
from composeui.core.view import UploadedFile
from composeui.qtcore._renderers.inputs import InputViewLike
from composeui.qtcore.qtrenderer import QtWidgetRenderer
from composeui.qtcore.widgets.qfilepathfield import QFilePathField
from composeui.qtcore.widgets.qfileupload import QFileUpload
from composeui.qtcore.widgets.qplaintext import plain_tool_tip

if TYPE_CHECKING:
    from collections.abc import Iterable

    from composeui.core.signal import Signal, SignalNoArgs


def _file_filters(extensions: dict[str, tuple[str, ...]]) -> str:
    """Get a file dialog's filters, e.g. "CSV (*.csv);;Text (*.txt *.text)"."""
    return ";;".join(
        f"{name} ({' '.join(f'*{e}' for e in name_extensions)})"
        for name, name_extensions in extensions.items()
    )


def _ask_file(
    parent: QWidget, title: str, start: Path | None, extensions: dict[str, tuple[str, ...]]
) -> str:
    """Get the file the user picks in Qt's file dialog, "" if cancelled."""
    picked, _selected_filter = QFileDialog.getOpenFileName(
        parent, title, "" if start is None else str(start), _file_filters(extensions)
    )
    return picked


def _ask_files(parent: QWidget, title: str, extensions: dict[str, tuple[str, ...]]) -> list[str]:
    """Get the files the user picks in Qt's file dialog, all of one folder; none if cancelled."""
    picked, _selected_filter = QFileDialog.getOpenFileNames(
        parent, title, "", _file_filters(extensions)
    )
    return picked


def _ask_folder(parent: QWidget, title: str, start: Path | None) -> str:
    """Get the folder the user picks in Qt's folder dialog, "" if cancelled."""
    return QFileDialog.getExistingDirectory(parent, title, "" if start is None else str(start))


def _ask_save(  # noqa: PLR0913
    parent: QWidget,
    title: str,
    start: Path | None,
    extensions: dict[str, tuple[str, ...]],
    *,
    confirms_overwrite: bool,
    replace_question: str,
) -> str:
    """Get the path the user picks in Qt's save dialog, the first extension added.

    "" if cancelled, or if the user keeps a file that exists. Nothing is written.
    """
    options = QFileDialog.Option(0)
    if not confirms_overwrite:
        options = QFileDialog.Option.DontConfirmOverwrite
    picked, _selected_filter = QFileDialog.getSaveFileName(
        parent,
        title,
        "" if start is None else str(start),
        _file_filters(extensions),
        options=options,
    )
    if picked == "":
        return ""
    path = with_extension(Path(picked), extensions)
    # Qt asked about the name as typed: the extension may name a file it didn't ask about
    if path != Path(picked) and path.exists() and confirms_overwrite:
        answer = QMessageBox.question(parent, title, replace_question.format(name=path.name))
        if answer != QMessageBox.StandardButton.Yes:
            return ""
    return str(path)


class PathInputViewLike(InputViewLike, Protocol):
    server_roots: tuple[Path, ...]
    base_folder: Path | None
    browse_text: str
    path_picked: Signal[Path]

    @property
    def path(self) -> Path | None: ...

    def path_text(self, path: Path) -> str: ...

    def start_folder(self) -> Path | None: ...


class FilePathInputViewLike(PathInputViewLike, Protocol):
    extensions: dict[str, tuple[str, ...]]
    has_reload: bool
    reload_text: str
    reload_clicked: SignalNoArgs


TPathView = TypeVar("TPathView", bound=PathInputViewLike)


#: the texts of the web's list of the server's files, which Qt doesn't show
_SERVER_LIST_TEXTS = (
    "parent_folder_text",
    "cancel_text",
    "unreadable_folder_text",
    "partial_folder_text",
)


class _QtPathInputRenderer(QtWidgetRenderer[TPathView, QFilePathField]):
    """A field typing a path, then a "…" button opening one of Qt's dialogs (`ask`)."""

    _invalid_style = "QLineEdit { border: 1px solid red; }"

    def __init__(self, view: TPathView) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "text": self._refresh_text,
                "placeholder": self._refresh_placeholder,
                "browse_text": self._refresh_browse_text,
                # read by the dialog each time it opens
                "server_roots": lambda _view, _rendered_object, _value: None,
                "base_folder": lambda _view, _rendered_object, _value: None,
                # the web's list of the server's files only
                **dict.fromkeys(_SERVER_LIST_TEXTS, lambda _view, _rendered_object, _value: None),
            }
        )

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QFilePathField()
            line_edit = self._rendered_object.line_edit
            self._connect(
                line_edit.textChanged, self._update_text, self._view.text_changed.call_callbacks
            )
            # Qt reports an edit before the change: the view has the text first
            self._connect(
                line_edit.textEdited, self._update_text, self._view.text_edited.call_callbacks
            )
            self._relay(self._view.editing_finished, line_edit.editingFinished)
            self._connect(self._rendered_object.browse_button.clicked, self.browse)
            self._rendered_object.reload_button.setVisible(False)
            self.refresh()

    def browse(self) -> None:
        """Pick a path in Qt's dialog, then the field's; nothing if cancelled."""
        assert self._rendered_object is not None
        picked = self.ask(self._rendered_object)
        if picked == "":
            return
        path = Path(picked)
        # its `textChanged` gives the view the text, and reports it
        self._rendered_object.line_edit.setText(self._view.path_text(path))
        self._view.path_picked.emit(path)

    @abstractmethod
    def ask(self, parent: QWidget) -> str:
        """Get the path the user picks in Qt's dialog, "" if cancelled."""

    @staticmethod
    def _refresh_text(_view: TPathView, rendered_object: QFilePathField, value: str) -> None:
        # the field's own signals: set in code, the text isn't reported, as a QLineEdit's
        with QSignalBlocker(rendered_object.line_edit):
            rendered_object.line_edit.setText(value)

    @staticmethod
    def _refresh_placeholder(_view: TPathView, rendered_object: QFilePathField, value: str) -> None:
        rendered_object.line_edit.setPlaceholderText(value)

    @staticmethod
    def _refresh_browse_text(_view: TPathView, rendered_object: QFilePathField, value: str) -> None:
        rendered_object.browse_button.setToolTip(plain_tool_tip(value))
        rendered_object.browse_button.setAccessibleName(value)

    def _update_text(self, text: str) -> None:
        with self.stop_refresh():
            self._view.text = text


class QtFilePathInputRenderer(_QtPathInputRenderer[FilePathInputViewLike]):
    """A field typing a file's path, then a "…" button opening Qt's file dialog.

    The dialog opens in the directory of the field's path, if any, else in the view's
    `start_folder`.
    """

    def __init__(self, view: FilePathInputViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "has_reload": self._refresh_has_reload,
                "reload_text": self._refresh_reload_text,
                # read by the dialog each time it opens
                "extensions": lambda _view, _rendered_object, _value: None,
            }
        )

    @override
    def render(self) -> None:
        is_new = self._rendered_object is None
        super().render()
        if is_new:
            assert self._rendered_object is not None
            self._relay(self._view.reload_clicked, self._rendered_object.reload_button.clicked)

    @override
    def ask(self, parent: QWidget) -> str:
        path = self._view.path
        start = path.parent if path is not None else self._view.start_folder()
        return _ask_file(parent, self._view.browse_text, start, self._view.extensions)

    @staticmethod
    def _refresh_has_reload(
        _view: FilePathInputViewLike, rendered_object: QFilePathField, value: bool
    ) -> None:
        rendered_object.reload_button.setVisible(value)

    @staticmethod
    def _refresh_reload_text(
        _view: FilePathInputViewLike, rendered_object: QFilePathField, value: str
    ) -> None:
        rendered_object.reload_button.setToolTip(plain_tool_tip(value))
        rendered_object.reload_button.setAccessibleName(value)


class FileUploadViewLike(ViewLike, Protocol):
    extensions: dict[str, tuple[str, ...]]
    multiple: bool
    browse_text: str
    empty_text: str
    files_text: str
    files: tuple[UploadedFile, ...]

    def take_files(self, files: Iterable[UploadedFile]) -> None: ...


class QtFileUploadRenderer(QtWidgetRenderer[FileUploadViewLike, QFileUpload]):
    """A button opening Qt's file dialog, then the name of the file picked: never a copy."""

    def __init__(self, view: FileUploadViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "browse_text": self._refresh_browse_text,
                "empty_text": functools.partial(self._refresh_name, "empty_text"),
                "files_text": functools.partial(self._refresh_name, "files_text"),
                "files": functools.partial(self._refresh_name, "files"),
                # read by the dialog each time it opens
                "extensions": lambda _view, _rendered_object, _value: None,
                "multiple": lambda _view, _rendered_object, _value: None,
                # the web's only: here, the file needs no upload
                "uploading_text": lambda _view, _rendered_object, _value: None,
            }
        )

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QFileUpload()
            self._connect(self._rendered_object.button.clicked, self.browse)
            self.refresh()

    def browse(self) -> None:
        """Hand the files the user picks in Qt's dialog to the view; nothing if cancelled."""
        assert self._rendered_object is not None
        view = self._view
        if view.multiple:
            picked = _ask_files(self._rendered_object, view.browse_text, view.extensions)
        else:
            one = _ask_file(self._rendered_object, view.browse_text, None, view.extensions)
            picked = [one] if one != "" else []
        if picked:
            view.take_files(UploadedFile.of_path(Path(path)) for path in picked)

    @staticmethod
    def _refresh_browse_text(
        _view: FileUploadViewLike, rendered_object: QFileUpload, value: str
    ) -> None:
        rendered_object.button.setText(value)

    @staticmethod
    def _refresh_name(
        name: str, view: FileUploadViewLike, rendered_object: QFileUpload, value: object
    ) -> None:
        # called before the view holds the value
        rendered_object.name.setText(upload_summary(view, name, value))


class SavePathInputViewLike(PathInputViewLike, Protocol):
    extensions: dict[str, tuple[str, ...]]
    confirms_overwrite: bool
    replace_question_text: str

    def remember_pick(self, path: Path) -> None: ...


#: the texts of the web's list for saving, which Qt doesn't show
_SAVE_LIST_TEXTS = ("file_name_text", "save_text", "replace_text")


class QtSavePathInputRenderer(_QtPathInputRenderer[SavePathInputViewLike]):
    """A field typing a path to save a file to, then a "…" button opening Qt's save dialog.

    The dialog opens on the field's path, if any, else in the view's `start_folder`, and
    asks before replacing a file, unless `confirms_overwrite` is off.
    The path picked gets the first of `extensions` if it has none of them. The view
    remembers a file the user agreed to replace (`remember_pick`).
    """

    def __init__(self, view: SavePathInputViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            # read by the dialog each time it opens; the web's list only
            dict.fromkeys(
                ("extensions", "confirms_overwrite", "replace_question_text", *_SAVE_LIST_TEXTS),
                lambda _view, _rendered_object, _value: None,
            )
        )

    @override
    def ask(self, parent: QWidget) -> str:
        path = self._view.path
        start = path if path is not None else self._view.start_folder()
        picked = _ask_save(
            parent,
            self._view.browse_text,
            start,
            self._view.extensions,
            confirms_overwrite=self._view.confirms_overwrite,
            replace_question=self._view.replace_question_text,
        )
        if picked != "":
            # Qt asked about a file that exists, or `_ask_save` did
            self._view.remember_pick(Path(picked))
        return picked


class QtFolderPathInputRenderer(_QtPathInputRenderer[PathInputViewLike]):
    """A field typing a folder's path, then a "…" button opening Qt's folder dialog.

    The dialog opens in the field's folder, if any, else in the view's `start_folder`.
    """

    def __init__(self, view: PathInputViewLike) -> None:
        super().__init__(view)
        # the web's list of the server's folders only
        self._refresh_dispatcher["choose_folder_text"] = lambda _view, _object, _value: None

    @override
    def ask(self, parent: QWidget) -> str:
        path = self._view.path
        start = path if path is not None else self._view.start_folder()
        return _ask_folder(parent, self._view.browse_text, start)

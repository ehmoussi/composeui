"""The web renderers of files: path fields, uploads, and the server's files they list."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Final, Literal, NamedTuple, TypeVar

from markupsafe import Markup
from typing_extensions import Protocol, override

from composeui.core._views.files import is_within_roots, with_extension
from composeui.core.renderer import ViewLike
from composeui.core.view import CellKind
from composeui.webcore._renderers.inputs import InputViewLike, _WebTextFieldRenderer
from composeui.webcore.serverfiles import (
    has_extension,
    is_item_name,
    is_within,
    item_path,
    list_folder,
    resolve_roots,
)
from composeui.webcore.webrenderer import UnsupportedEventError, WebRenderer, _file_types, _icon

if TYPE_CHECKING:
    from collections.abc import Mapping

    from composeui.core.signal import Signal, SignalNoArgs
    from composeui.core.view import UploadedFile


class _FilesTexts(NamedTuple):
    """The texts of a list of the server's files: its title, its items and its messages."""

    title: str
    parent_folder: str
    cancel: str
    unreadable_folder: str
    partial_folder: str
    #: the button picking the folder shown, for a list of folders
    choose_folder: str = ""
    #: for a file to save: the box of its name, the button saving it, and the question
    #: before replacing a file, ``{name}`` the file's, and its answer
    file_name: str = ""
    save: str = ""
    replace_question: str = ""
    replace: str = ""


#: what a list of the server's files picks: a file to open, a folder, or a file to save
_FilesKind = Literal["file", "folder", "save"]

#: the kind of a path cell, by what its list of the server's files picks
_PATH_KINDS: Final[dict[_FilesKind, CellKind]] = {
    "file": CellKind.FILE_PATH,
    "folder": CellKind.FOLDER_PATH,
    "save": CellKind.SAVE_PATH,
}

#: the events picking a path, by what the list picks
_PICK_EVENTS: Final[dict[str, tuple[str, ...]]] = {
    "file": ("browse-file",),
    "folder": ("browse-choose",),
    "save": ("browse-name", "browse-save", "browse-replace", "browse-keep"),
}


class _ServerFiles:
    """The `<dialog>` that a "…" button opens on the files of a folder of the server.

    It lists a folder's subfolders, then its files of the picker's types, within the roots
    (see `serverfiles.py`): a folder's item shows its files, a file's is picked. Only the
    server knows the folder shown: the page names an item by its name in it. Opened or
    closed, only the dialog swaps (`dialog_html`), and moving between folders only its
    list (`list_html`): the dialog open, and the button that opened it, stay the same
    elements. So closing it gives that button the focus. The first item of a new list
    takes the focus, the one clicked being gone with the old list.

    For a folder (`kind`), it lists only folders, and "Choose this folder" picks the one
    shown ("browse-choose"). For a file to save, a file's item puts its name in a box
    ("browse-name"), and "Save" picks the folder shown with the name typed
    ("browse-save"), the first extension added. A file that exists is picked once the
    user agrees to replace it ("browse-replace"), with `confirms_overwrite`.
    """

    #: the events it takes, each but "browse" only while open
    EVENTS = ("browse", "browse-close", "browse-root", "browse-parent", "browse-folder")

    def __init__(self, dialog_id: str, widget_id: str, *, kind: _FilesKind = "file") -> None:
        self.dialog_id = dialog_id
        self.kind = kind
        #: for a file to save: whether to ask before replacing one
        self.confirms_overwrite = True
        #: the renderer its events post to
        self._widget_id = widget_id
        #: whether it shows
        self.is_open = False
        #: the folder it lists, resolved; None for the list of the roots
        self._folder: Path | None = None
        #: for a file to save: the name in its box, whether it was refused, and the name
        #: of the file that exists, until the user answers whether to replace it
        self._name = ""
        self._is_name_refused = False
        self._replacing: str | None = None

    def takes(self, event: str) -> bool:
        """Whether `event` moves it, or picks a path of it, as it now is."""
        is_its = event in self.EVENTS or event in _PICK_EVENTS[self.kind]
        return is_its and (self.is_open or event == "browse")

    def move(
        self,
        event: str,
        name: str,
        roots: list[Path],
        extensions: tuple[str, ...],
        *,
        start: Path | None = None,
    ) -> Path | None:
        """Open, move or close it on `event`; get the path picked, a file's or a folder's.

        On "browse", it opens in the folder of `name`, a path, if inside the roots, else
        in the folder `start` if inside them, else in the only root. For a list of
        folders, in that folder itself. An item that is no longer there, or never was,
        moves nothing.
        """
        if self._folder is not None and not is_within(self._folder, roots):
            self._folder = None  # the roots changed since
        self._is_name_refused = False
        if event not in ("browse-replace", "browse-keep"):
            self._replacing = None
        if event == "browse":
            self.is_open = True
            self._folder = self._start_folder(name, roots, start)
            self._name = "" if self.kind != "save" or name.strip() == "" else Path(name).name
            return None
        if event == "browse-close":
            self.is_open = False
            return None
        moves = {
            "browse-root": self._show_root,
            "browse-parent": self._show_parent,
            "browse-folder": self._show_folder,
            "browse-file": self._pick_file,
            "browse-choose": self._pick_folder,
            "browse-name": self._take_name,
            "browse-save": self._save,
            "browse-replace": self._replace,
            "browse-keep": self._keep,
        }
        picked = moves[event](name, roots, extensions)
        if picked is not None:
            self.is_open = False
        return picked

    def _show_root(self, name: str, roots: list[Path], _extensions: tuple[str, ...]) -> None:
        if name.isdigit() and int(name) < len(roots):
            self._folder = roots[int(name)]

    def _show_parent(self, _name: str, roots: list[Path], _extensions: tuple[str, ...]) -> None:
        folder = self._folder
        if folder is not None and folder not in roots:
            self._folder = folder.parent
        elif len(roots) > 1:
            self._folder = None  # the list of the roots

    def _show_folder(self, name: str, roots: list[Path], _extensions: tuple[str, ...]) -> None:
        path = None if self._folder is None else item_path(self._folder, name, roots)
        if path is not None and path.is_dir():
            self._folder = path

    def _pick_file(self, name: str, roots: list[Path], extensions: tuple[str, ...]) -> Path | None:
        folder = self._folder
        path = None if folder is None else item_path(folder, name, roots)
        if path is None or not path.is_file() or not has_extension(name, extensions):
            return None
        assert folder is not None
        return folder / name

    def _pick_folder(
        self, _name: str, _roots: list[Path], _extensions: tuple[str, ...]
    ) -> Path | None:
        return self._folder

    def _take_name(self, name: str, _roots: list[Path], _extensions: tuple[str, ...]) -> None:
        if is_item_name(name):
            self._name = name

    def _save(self, name: str, roots: list[Path], extensions: tuple[str, ...]) -> Path | None:
        """Get the file the name typed names in the folder shown, the first extension added.

        Refused for a name that isn't a file's, or for a folder; a file that exists is
        picked once the user agrees to replace it.
        """
        folder = self._folder
        self._name = name.strip()
        if folder is None or not is_item_name(self._name):
            self._is_name_refused = True
            return None
        file_name = with_extension(Path(self._name), {"": extensions}).name
        path = folder / file_name
        if not path.exists() and not path.is_symlink():
            return path
        if item_path(folder, file_name, roots) is None or path.is_dir():
            self._is_name_refused = True  # a folder, or a link out of the roots
            return None
        if self.confirms_overwrite:
            self._replacing = file_name
            return None
        return path

    def _replace(self, _name: str, roots: list[Path], _extensions: tuple[str, ...]) -> Path | None:
        folder, file_name, self._replacing = self._folder, self._replacing, None
        if folder is None or file_name is None or item_path(folder, file_name, roots) is None:
            return None
        return folder / file_name

    def _keep(self, _name: str, _roots: list[Path], _extensions: tuple[str, ...]) -> None:
        self._replacing = None

    def _start_folder(self, name: str, roots: list[Path], folder: Path | None) -> Path | None:
        start = roots[0] if len(roots) == 1 else None
        if folder is not None and is_within_roots(folder, roots) and folder.expanduser().is_dir():
            start = folder.expanduser().resolve()
        if name.strip() == "":
            return start
        path = Path(name.strip())
        if self.kind == "save":  # a file that may not exist yet: its folder
            folder = item_path(path.parent.parent, path.parent.name, roots)
            return folder if folder is not None and folder.is_dir() else start
        item = item_path(path.parent, path.name, roots)
        if item is None:
            return start
        return item if self.kind == "folder" and item.is_dir() else item.parent

    def dialog_html(
        self,
        texts: _FilesTexts,
        roots: list[Path],
        extensions: tuple[str, ...],
        *,
        is_enabled: bool,
        oob: bool,
    ) -> Markup:
        """Get the dialog, hidden while closed or disabled."""
        is_open = self.is_open and is_enabled
        title_id = f"{self.dialog_id}-title"
        return Markup(
            '<dialog id="{dialog_id}" class="modal" data-dialog{hidden}{swap}'
            ' aria-labelledby="{title_id}" hx-trigger="cancel"{close}>'
            '<div class="modal-box flex flex-col gap-3">'
            '<h2 id="{title_id}" class="text-lg font-bold">{title}</h2>{items}'
            '<div class="modal-action"><button type="button" class="btn"{close}'
            " data-close-dialog>{cancel}</button>{action}</div></div></dialog>"
        ).format(
            action=self._action_html(texts, oob=False),
            dialog_id=self.dialog_id,
            hidden="" if is_open else " hidden",
            swap=Markup(' hx-swap-oob="true"') if oob else "",
            title_id=title_id,
            close=self._post({"event": "browse-close"}),
            title=texts.title,
            items=self.list_html(texts, roots, extensions, oob=False) if is_open else Markup(),
            cancel=texts.cancel,
        )

    def list_html(
        self, texts: _FilesTexts, roots: list[Path], extensions: tuple[str, ...], *, oob: bool
    ) -> Markup:
        """Get the dialog's list: the roots, or a folder's path, its folders and its files."""
        folder = self._folder
        message = ""
        items: list[Markup] = []
        if folder is None:
            items = [
                self._item_html("browse-root", str(index), str(root), "folder", is_first=index == 0)
                for index, root in enumerate(roots)
            ]
        else:
            if folder not in roots or len(roots) > 1:
                items.append(
                    self._item_html(
                        "browse-parent", "", texts.parent_folder, "parent", is_first=True
                    )
                )
            has_parent = len(items) > 0
            try:
                listing = list_folder(folder, roots, extensions, has_files=self.kind != "folder")
            except OSError:
                message = texts.unreadable_folder
            else:
                file_event = "browse-name" if self.kind == "save" else "browse-file"
                items.extend(
                    self._item_html(
                        "browse-folder" if item.is_folder else file_event,
                        item.name,
                        item.name,
                        "folder" if item.is_folder else "file",
                        is_first=index == 0 and not has_parent,
                    )
                    for index, item in enumerate(listing.items)
                )
                if listing.is_partial:
                    message = texts.partial_folder
        # swapped with the list: the folder it picks is the one the list shows
        action = self._action_html(texts, oob=True) if oob else ""
        return Markup(
            '<div id="{dialog_id}-list" class="flex flex-col gap-3"{swap}>'
            '<p class="break-all font-mono text-sm">{folder}</p>{message}'
            '<ul class="menu max-h-96 w-full flex-nowrap overflow-y-auto">{items}</ul>'
            "{name}</div>{action}"
        ).format(
            action=action,
            dialog_id=self.dialog_id,
            swap=Markup(' hx-swap-oob="true"') if oob else "",
            folder="" if folder is None else str(folder),
            message=(
                Markup('<p role="status" class="text-sm text-warning">{}</p>').format(message)
                if message
                else ""
            ),
            items=Markup("").join(items),
            name=self._name_html(texts) if self.kind == "save" else "",
        )

    def _name_html(self, texts: _FilesTexts) -> Markup:
        """Get the box of the file's name, Enter saving it, or the question to replace it."""
        name_id = f"{self.dialog_id}-name"
        if self._replacing is not None:
            return Markup(
                '<div role="alert" class="flex flex-col gap-2"><p>{question}</p>'
                '<div class="flex justify-end gap-2"><button type="button" class="btn"'
                "{keep} autofocus>{cancel}</button>"
                '<button type="button" class="btn btn-warning"{replace}'
                " data-close-dialog>{replace_text}</button></div></div>"
            ).format(
                question=texts.replace_question.format(name=self._replacing),
                keep=self._post({"event": "browse-keep"}),
                cancel=texts.cancel,
                replace=self._post({"event": "browse-replace"}),
                replace_text=texts.replace,
            )
        return Markup(
            '<label class="flex flex-col gap-1" for="{name_id}">{label}'
            '<input id="{name_id}" class="input w-full" type="text" name="name" value="{name}"'
            ' autocomplete="off"{invalid}{post} hx-trigger="enter-key"></label>'
        ).format(
            name_id=name_id,
            label=texts.file_name,
            name=self._name,
            invalid=Markup(' aria-invalid="true"') if self._is_name_refused else "",
            post=self._post({"event": "browse-save"}),
        )

    def _action_html(self, texts: _FilesTexts, *, oob: bool) -> Markup:
        """Get the button picking the folder shown, disabled on the list of the roots.

        For a folder, "Choose this folder"; for a file to save, "Save", with the name typed.
        """
        if self.kind == "file":
            return Markup()
        is_folder = self.kind == "folder"
        return Markup(
            '<button id="{dialog_id}-action" type="button" class="btn btn-primary"{swap}'
            "{post}{include}{closes}{disabled}>{text}</button>"
        ).format(
            dialog_id=self.dialog_id,
            swap=Markup(' hx-swap-oob="true"') if oob else "",
            post=self._post({"event": "browse-choose" if is_folder else "browse-save"}),
            # a folder is picked at once; a file to save may be refused, or exist
            include=(
                Markup("") if is_folder else Markup(' hx-include="#{}-name"').format(self.dialog_id)
            ),
            closes=" data-close-dialog" if is_folder else "",
            disabled=" disabled" if self._folder is None or self._replacing else "",
            text=texts.choose_folder if is_folder else texts.save,
        )

    def _item_html(self, event: str, name: str, text: str, icon: str, *, is_first: bool) -> Markup:
        # a file's closes the dialog first, as a dialog's answer does
        closes = " data-close-dialog" if event == "browse-file" else ""
        return Markup(
            '<li><button type="button"{post}{closes}{autofocus}>{icon}'
            '<span class="break-all">{text}</span></button></li>'
        ).format(
            post=self._post({"event": event, "name": name}),
            closes=closes,
            autofocus=" autofocus" if is_first else "",
            icon=_icon(icon),
            text=text,
        )

    def _post(self, values: Mapping[str, str]) -> Markup:
        return Markup(""" hx-post="/widget/{}" hx-vals='{}' hx-swap="none\"""").format(
            self._widget_id, json.dumps(values)
        )


class PathInputViewLike(InputViewLike, Protocol):
    server_roots: tuple[Path, ...]
    base_folder: Path | None
    browse_text: str
    parent_folder_text: str
    cancel_text: str
    unreadable_folder_text: str
    partial_folder_text: str
    path_picked: Signal[Path]
    _keeps_to_roots: bool

    @property
    def path(self) -> Path | None: ...

    def path_text(self, path: Path) -> str: ...


class FilePathInputViewLike(PathInputViewLike, Protocol):
    extensions: dict[str, tuple[str, ...]]
    has_reload: bool
    reload_text: str
    reload_clicked: SignalNoArgs


class FolderPathInputViewLike(PathInputViewLike, Protocol):
    choose_folder_text: str


class SavePathInputViewLike(PathInputViewLike, Protocol):
    extensions: dict[str, tuple[str, ...]]
    confirms_overwrite: bool
    file_name_text: str
    save_text: str
    replace_question_text: str
    replace_text: str

    def remember_pick(self, path: Path) -> None: ...


TPathView = TypeVar("TPathView", bound=PathInputViewLike)

#: the fields of a path field that change its HTML, a file's or a folder's
_PATH_FIELDS = (
    "text",
    "placeholder",
    "server_roots",
    "browse_text",
    "parent_folder_text",
    "cancel_text",
    "unreadable_folder_text",
    "partial_folder_text",
)


class _WebPathInputRenderer(_WebTextFieldRenderer[TPathView]):
    """A text field typing a path, then a "…" button, and what a subclass adds after it.

    The field posts as a text input's (see `_WebTextFieldRenderer`). The root is a
    `<div>` holding them, so a row's label names the field with `aria-labelledby`. With
    `server_roots`, the button opens the list of the server's files (see `_ServerFiles`),
    a path of which it puts in the field.
    """

    is_labelable = False
    #: what the list of the server's files picks
    _kind: ClassVar[_FilesKind] = "file"
    #: the view's fields that change the field's HTML
    _shown_fields: ClassVar[tuple[str, ...]] = _PATH_FIELDS

    def __init__(self, view: TPathView) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(dict.fromkeys(self._shown_fields, self._mark_dirty))
        # read as the list opens, and by `path`: the text shown stays the same
        self._refresh_dispatcher["base_folder"] = lambda _view, _rendered_object, _value: None
        # the user can type any path of the server: `path` then keeps to the roots too
        view._keeps_to_roots = True  # noqa: SLF001
        self._server_files: _ServerFiles | None = None
        #: what changed since last sent: "field" (all of it), "dialog" or "list"
        self._swaps: set[str] = set()
        #: whether the "…" button takes the focus as the field swaps: the list closed by
        #: the server, not the browser, which would have given it back
        self._focuses_browse = False

    @property
    def _files(self) -> _ServerFiles:
        # once rendered, with its id
        if self._server_files is None:
            self._server_files = _ServerFiles(
                f"{self.widget_id}-files", self.widget_id, kind=self._kind
            )
        return self._server_files

    @override
    def _mark_dirty(self, view: TPathView, rendered_object: str, value: Any) -> None:
        self._mark_part("field")

    def _mark_part(self, part: str) -> None:
        self._swaps.add(part)
        super()._mark_dirty(self._view, "", None)

    @override
    def to_html(self, *, oob: bool = False) -> Markup:
        swaps, self._swaps = self._swaps, set()
        if oob and swaps and "field" not in swaps:
            return self._files_html(oob=True) if "dialog" in swaps else self._list_html(oob=True)
        disabled = "" if self.is_enabled else " disabled"
        if self._view.server_roots:
            focuses, self._focuses_browse = self._focuses_browse, False
            browse = Markup(
                '<button id="{widget_id}-browse" type="button" class="btn btn-square"'
                ' aria-label="{text}" title="{text}" hx-post="/widget/{widget_id}"'
                """ hx-vals='{{"event": "browse"}}' hx-swap="none"{autofocus}{disabled}>"""
                "…</button>"
            ).format(
                widget_id=self.widget_id,
                text=self._view.browse_text,
                autofocus=" autofocus" if focuses else "",
                disabled=disabled,
            )
            picker = browse + self._files_html(oob=False)
        else:
            picker = self._picker_html(disabled)
        return Markup(
            '<div {root_attributes} class="flex gap-1" data-file-path>'
            '<input id="{widget_id}-field"{row_attributes}'
            ' class="input w-full" type="text" name="value"'
            ' value="{text}" placeholder="{placeholder}"'
            ' hx-post="/widget/{widget_id}" hx-trigger="input changed delay:300ms, change"'
            ' data-post-event hx-swap="none" hx-sync="this:queue all"'
            ' autocomplete="off"{disabled}>'
            "{picker}{after}</div>"
        ).format(
            root_attributes=self._root_attributes(oob=oob),
            widget_id=self.widget_id,
            row_attributes=self._row_attributes(),
            text=self._text(),
            placeholder=self._view.placeholder,
            disabled=disabled,
            picker=picker,
            after=self._after_html(disabled),
        )

    def _picker_html(self, _disabled: str) -> Markup:
        """Get what picks a path without `server_roots`: nothing, the path typed."""
        return Markup()

    def _after_html(self, _disabled: str) -> Markup:
        """Get what follows the "…" button, e.g. a reload button."""
        return Markup()

    def _files_texts(self) -> _FilesTexts:
        view = self._view
        return _FilesTexts(
            view.browse_text,
            view.parent_folder_text,
            view.cancel_text,
            view.unreadable_folder_text,
            view.partial_folder_text,
            self._choose_folder_text(),
            *self._save_texts(),
        )

    def _choose_folder_text(self) -> str:
        return ""

    def _save_texts(self) -> tuple[str, str, str, str]:
        """Get the texts of a list for saving: its name's box, its button, its question."""
        return ("", "", "", "")

    def _files_html(self, *, oob: bool) -> Markup:
        return self._files.dialog_html(
            self._files_texts(),
            resolve_roots(self._view.server_roots),
            tuple(self.file_types),
            is_enabled=self.is_enabled,
            oob=oob,
        )

    def _list_html(self, *, oob: bool) -> Markup:
        return self._files.list_html(
            self._files_texts(),
            resolve_roots(self._view.server_roots),
            tuple(self.file_types),
            oob=oob,
        )

    @property
    def file_types(self) -> list[str]:
        """Get the file types the picker offers, e.g. [".csv"]; empty for any."""
        return []

    @override
    def dispatch(self, event: str, form: Mapping[str, str]) -> None:
        if event.startswith("browse"):
            self._browse(event, form.get("name", ""))
        else:
            super().dispatch(event, form)

    def _browse(self, event: str, name: str) -> None:
        """Open, move or close the list of the server's files, or pick a path of it."""
        if not self._files.takes(event) or not self.is_enabled or not self._view.server_roots:
            raise UnsupportedEventError(self, event)
        was_open = self._files.is_open
        if event == "browse":
            path = self._view.path
            name = "" if path is None else str(path)
        self._files.confirms_overwrite = self._confirms_overwrite()
        picked = self._files.move(
            event,
            name,
            resolve_roots(self._view.server_roots),
            tuple(self.file_types),
            start=self._view.base_folder,
        )
        # opened or closed: the dialog; else only its list, the dialog left open
        self._mark_part("list" if was_open == self._files.is_open else "dialog")
        if picked is not None:
            self._focuses_browse = True
            self._show_path(picked)

    def _confirms_overwrite(self) -> bool:
        return True

    def _show_path(self, path: Path) -> None:
        text = self._view.path_text(path)
        # swapped back: the field shows the path, though its picker sent the request
        self._view.text = text
        self._view.text_changed.emit(text)
        self._view.path_picked.emit(path)

    @override
    def _text(self) -> str:
        return self._view.text

    @override
    def _posted_text(self) -> str:
        return self._view.text

    @override
    def _apply_text(self, text: str) -> None:
        with self.stop_refresh():
            self._view.text = text


class WebFilePathInputRenderer(_WebPathInputRenderer[FilePathInputViewLike]):
    """A text field typing a file's path, then a "…" button uploading one, and a reload button.

    The browser can't hand a page its files' paths. The button opens the browser's
    picker, a hidden file input beside it (see `page.js`) uploading the file picked
    (`/widget/{id}/file`), and the session keeps a copy (see `WebSession.pick_file`),
    whose path the field then shows. With `server_roots`, the button instead opens the
    list of the server's files, a file of which puts its path in the field.
    """

    _role = "file_path_input"
    _shown_fields = (*_PATH_FIELDS, "extensions", "has_reload", "reload_text")

    @override
    def _picker_html(self, disabled: str) -> Markup:
        types = ",".join(self.file_types)
        return Markup(
            '<button id="{widget_id}-browse" type="button" class="btn btn-square"'
            ' aria-label="{browse}" title="{browse}" data-file-browse{disabled}>…</button>'
            # emptied once sent: picking the same file again is a change too
            '<input type="file" name="file"{accept} class="hidden" tabindex="-1"'
            ' aria-hidden="true" hx-post="/widget/{widget_id}/file"'
            ' hx-encoding="multipart/form-data" hx-trigger="change" hx-swap="none"'
            ' data-clear-after-post autocomplete="off"{disabled}>'
        ).format(
            widget_id=self.widget_id,
            browse=self._view.browse_text,
            disabled=disabled,
            accept=Markup(' accept="{}"').format(types) if types else "",
        )

    @override
    def _after_html(self, disabled: str) -> Markup:
        if not self._view.has_reload:
            return Markup()
        reload = self._view.reload_text
        return Markup(
            '<button id="{widget_id}-reload" type="button" class="btn btn-square"'
            ' aria-label="{reload}" title="{reload}" hx-post="/widget/{widget_id}"'
            """ hx-vals='{{"event": "reload"}}' hx-swap="none"{disabled}>"""
            "{reload_icon}</button>"
        ).format(
            widget_id=self.widget_id,
            reload=reload,
            disabled=disabled,
            reload_icon=_icon("reload"),
        )

    @override
    def dispatch(self, event: str, form: Mapping[str, str]) -> None:
        if event != "reload":
            super().dispatch(event, form)
        elif not self.is_enabled or not self._view.has_reload:
            raise UnsupportedEventError(self, event)
        else:
            self._view.reload_clicked.emit()

    @property
    @override
    def file_types(self) -> list[str]:
        return _file_types(self._view.extensions)

    def pick_file(self, path: Path) -> None:
        """Show the path of the file the picker uploaded, and hand it to `path_picked`.

        Raises `UnsupportedEventError` while the field is disabled.
        """
        if not self.is_enabled:
            raise UnsupportedEventError(self, "file")
        self._show_path(path)


class WebSavePathInputRenderer(_WebPathInputRenderer[SavePathInputViewLike]):
    """A text field typing a path to save a file to, then a "…" button with `server_roots`.

    The browser can't hand a page a path: without `server_roots`, the path is typed, and
    the field has no button. With them, the button opens the list of the server's folders
    and their files of `extensions`, whose "Save" puts the folder shown, with the name
    typed, in the field, once the user agrees to replace a file that exists, which the
    view remembers (`remember_pick`).
    """

    _role = "save_path_input"
    _kind = "save"
    _shown_fields = (
        *_PATH_FIELDS,
        "extensions",
        "confirms_overwrite",
        "file_name_text",
        "save_text",
        "replace_question_text",
        "replace_text",
    )

    @property
    @override
    def file_types(self) -> list[str]:
        return _file_types(self._view.extensions)

    @override
    def _confirms_overwrite(self) -> bool:
        return self._view.confirms_overwrite

    @override
    def _save_texts(self) -> tuple[str, str, str, str]:
        view = self._view
        return (view.file_name_text, view.save_text, view.replace_question_text, view.replace_text)

    @override
    def _show_path(self, path: Path) -> None:
        # the list asked about a file that exists, unless `confirms_overwrite` is off
        self._view.remember_pick(path)
        super()._show_path(path)


class WebFolderPathInputRenderer(_WebPathInputRenderer[FolderPathInputViewLike]):
    """A text field typing a folder's path, then a "…" button with `server_roots`.

    The browser can't hand a page a folder's path: without `server_roots`, the path is
    typed, and the field has no button. With them, the button opens the list of the
    server's folders, whose "Choose this folder" puts the folder shown in the field.
    """

    _role = "folder_path_input"
    _kind = "folder"
    _shown_fields = (*_PATH_FIELDS, "choose_folder_text")

    @override
    def _choose_folder_text(self) -> str:
        return self._view.choose_folder_text


class FileUploadViewLike(ViewLike, Protocol):
    extensions: dict[str, tuple[str, ...]]
    browse_text: str
    empty_text: str
    uploading_text: str
    file: UploadedFile | None

    def take_file(self, file: UploadedFile) -> None: ...


class WebFileUploadRenderer(WebRenderer[FileUploadViewLike]):
    """A button opening the browser's picker, then the name of the file it uploaded.

    The hidden file input beside the button uploads the file (`/widget/{id}/file`), and the
    session keeps a copy (see `WebSession.pick_file`). An upload swaps only the name, so
    the button keeps the focus.
    """

    _role = "file_upload"
    is_labelable = False

    def __init__(self, view: FileUploadViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "extensions": self._mark_dirty,
                "browse_text": self._mark_dirty,
                "uploading_text": self._mark_dirty,
                "empty_text": self._mark_name_dirty,
                "file": self._mark_name_dirty,
            }
        )
        #: whether only the name changed since last sent
        self._swaps_name = False
        self._swaps_whole = False

    @property
    def file_types(self) -> list[str]:
        return _file_types(self._view.extensions)

    @override
    def _mark_dirty(self, view: FileUploadViewLike, rendered_object: str, value: Any) -> None:
        self._swaps_whole = True
        super()._mark_dirty(view, rendered_object, value)

    def _mark_name_dirty(self, view: FileUploadViewLike, rendered_object: str, value: Any) -> None:
        self._swaps_name = True
        super()._mark_dirty(view, rendered_object, value)

    def _name_html(self, *, oob: bool = False) -> Markup:
        file = self._view.file
        return Markup('<span id="{}-name" aria-live="polite"{}>{}</span>').format(
            self.widget_id,
            Markup(' hx-swap-oob="true"') if oob else Markup(),
            self._view.empty_text if file is None else file.name,
        )

    @override
    def to_html(self, *, oob: bool = False) -> Markup:
        only_name = self._swaps_name and not self._swaps_whole
        self._swaps_name = self._swaps_whole = False
        if oob and only_name:
            return self._name_html(oob=True)
        disabled = "" if self.is_enabled else " disabled"
        types = ",".join(self.file_types)
        return Markup(
            '<div {root_attributes}{row_attributes} role="group"'
            ' class="flex items-center gap-2">'
            '<button type="button" class="btn" data-file-browse{disabled}>{browse}</button>'
            # emptied once sent: picking the same file again is a change too
            '<input type="file" name="file"{accept} class="hidden" tabindex="-1"'
            ' aria-hidden="true" hx-post="/widget/{widget_id}/file"'
            ' hx-encoding="multipart/form-data" hx-trigger="change" hx-swap="none"'
            ' data-clear-after-post data-uploading-text="{uploading}" autocomplete="off"{disabled}>'
            "{name}</div>"
        ).format(
            root_attributes=self._root_attributes(oob=oob),
            row_attributes=self._row_attributes(),
            disabled=disabled,
            browse=self._view.browse_text,
            accept=Markup(' accept="{}"').format(types) if types else "",
            widget_id=self.widget_id,
            uploading=self._view.uploading_text,
            name=self._name_html(),
        )

    def holds_file_in(self, directory: Path) -> bool:
        """Tell whether the view's file is the upload in `directory`."""
        file = self._view.file
        return file is not None and file.path.parent == directory

    def pick_file(self, file: UploadedFile) -> None:
        """Hand the view the file the picker uploaded, whose copy the session keeps."""
        self._view.take_file(file)

"""The views that take paths and files, and what a download writes."""

from __future__ import annotations

import io
import mimetypes
import shutil
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    BinaryIO,
    Optional,
    Union,
    cast,
)

import attrs
from typing_extensions import override

from composeui.core._views.base import OMIT, UI_TEXT, View, define_view
from composeui.core._views.inputs import InputMixin
from composeui.core.signal import Signal, SignalNoArgs
from composeui.core.translation import (
    T,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from typing_extensions import Buffer

    from composeui.core._views.main import MainView
    from composeui.core.jobs import Job


def is_within_roots(path: Path, roots: Iterable[Path]) -> bool:
    """Whether `path` is one of `roots`, or inside one, once resolved (``~``, ``..``, links)."""
    try:
        try:
            # strict: a loop of links, or a NUL character, raises on every Python and OS
            resolved = path.expanduser().resolve(strict=True)
        except FileNotFoundError:  # a file still to come: the links above it followed
            resolved = path.expanduser().resolve()
        resolved_roots = [root.expanduser().resolve() for root in roots]
    # a loop of links raises RuntimeError before 3.13, a NUL character ValueError
    except (OSError, RuntimeError, ValueError):
        return False
    return any(resolved == root or root in resolved.parents for root in resolved_roots)


def path_of_text(text: str, base_folder: Optional[Path]) -> Path:
    """Get the path `text` names: a relative one from `base_folder`, ``~`` expanded, if any."""
    path = Path(text)
    if base_folder is None:
        return path
    path = path.expanduser()
    return path if path.is_absolute() else base_folder.expanduser() / path


def text_of_path(path: Path, base_folder: Optional[Path]) -> str:
    """Get the text naming `path`: relative to `base_folder` when inside it, else as is.

    Inside it as written, or once both are resolved: a dialog may give the path with the
    links of `base_folder` followed.
    """
    if base_folder is None:
        return str(path)
    base = base_folder.expanduser()
    for folder, inside in ((base, path), (base.resolve(), path.resolve())):
        if inside == folder or folder in inside.parents:
            return str(inside.relative_to(folder))
    return str(path)


@define_view
class PathInputMixin(InputMixin):
    """A path typed in the field or picked with the "…" button beside it.

    What `FilePathInputMixin` and `FolderPathInputMixin` share: `text` holds the path as
    typed, and `path` reads it as a path. With `server_roots`, the web's button lists the
    server's folders in them, and the field holds the path picked there. With
    `base_folder`, a relative text names a path in that folder, and a path picked in it
    shows relative to it.
    """

    #: the folders of the server that the web's "…" lists, and nothing outside them. On
    #: Qt and Textual, the dialog opens in the first one while the field is empty, and the
    #: user can leave it.
    server_roots: tuple[Path, ...] = attrs.field(default=(), metadata={OMIT: True})
    #: the folder of a relative path, e.g. a study's, rather than the process's working
    #: folder: `path` and the check of `server_roots` read the text from it, and the
    #: dialog opens in it while the field is empty. Changed, the text stays, and `path`
    #: reads it from the new folder.
    base_folder: Optional[Path] = attrs.field(default=None, metadata={OMIT: True})
    #: the texts of the web's list of the server's files in `server_roots`
    parent_folder_text: str = attrs.field(default=T("Parent folder"), metadata={UI_TEXT: True})
    cancel_text: str = attrs.field(default=T("Cancel"), metadata={UI_TEXT: True})
    unreadable_folder_text: str = attrs.field(
        default=T("This folder can't be read."), metadata={UI_TEXT: True}
    )
    #: the user picked a path with the "…" button, now in the field (relative to
    #: `base_folder` when inside it, but emitted whole); a typed path is reported as any
    #: text is (`text_edited`, `editing_finished`)
    path_picked: Signal[Path] = attrs.Factory(Signal[Path])
    #: whether `path` keeps to `server_roots`: set by the web, which lists only their files
    _keeps_to_roots: bool = attrs.field(
        default=False, init=False, repr=False, eq=False, metadata={OMIT: True}
    )

    @property
    def path(self) -> Optional[Path]:
        """Get the path the field holds, from `base_folder` if relative; None while empty.

        On the web, with `server_roots`, None too for a path typed outside them, symbolic
        links and ``..`` followed: the user can type any path of the server.
        """
        text = self.text.strip()
        if text == "":
            return None
        path = path_of_text(text, self.base_folder)
        if (
            self._keeps_to_roots
            and self.server_roots
            and not is_within_roots(path, self.server_roots)
        ):
            return None
        return path

    def path_text(self, path: Path) -> str:
        """Get the text the field shows for `path`: relative to `base_folder` when inside it."""
        return text_of_path(path, self.base_folder)

    def start_folder(self) -> Optional[Path]:
        """Get the folder a dialog opens in while the field is empty, if any.

        `base_folder`, else the first of `server_roots`.
        """
        if self.base_folder is not None:
            return self.base_folder.expanduser()
        return self.server_roots[0] if self.server_roots else None


@define_view
class FilePathInputMixin(PathInputMixin):
    """A file's path, typed in the field or picked with the "…" button beside it.

    `text` holds the path as typed, and `path` reads it as a path. On Qt and Textual, the
    button opens the toolkit's file dialog. On the web, the browser's picker uploads the
    file. The field then holds the path of the session's copy, kept until the session
    ends. With `server_roots`, the web's button instead lists the files on the server in
    those folders, and the field holds the path of the file picked there, not a copy.
    With `has_reload`, a reload button beside them emits `reload_clicked`, e.g. to read
    the file again once it changed.
    """

    #: the file types the dialog offers, by name: ``{"CSV": (".csv",)}``; on the web, a
    #: file of another type is refused
    extensions: dict[str, tuple[str, ...]] = attrs.field(
        factory=dict[str, tuple[str, ...]], metadata={OMIT: True}
    )
    has_reload: bool = attrs.field(default=False)
    #: the names of the "…" and reload buttons, as a tooltip and a screen reader show them
    browse_text: str = attrs.field(default=T("Choose a file"), metadata={UI_TEXT: True})
    reload_text: str = attrs.field(default=T("Reload"), metadata={UI_TEXT: True})
    partial_folder_text: str = attrs.field(
        default=T("This folder holds too many items to list them all: type the file's path."),
        metadata={UI_TEXT: True},
    )
    reload_clicked: SignalNoArgs = attrs.Factory(SignalNoArgs)


@attrs.frozen
class DownloadedFile:
    """A file that the app gives its user (`MainView.download`): its name, content and type."""

    #: the name offered for the file, without a folder
    filename: str
    #: the file's bytes, the path of a file that the app wrote, or what writes it
    content: Union[bytes, Path, StreamContent]
    #: what it holds, such as ``text/csv``
    media_type: str


@attrs.frozen
class StreamContent:
    """A file that the app writes as the user receives it: one too large to make first.

    `write` writes the file to the binary file it gets, in order: it can't seek. It runs
    later, on a thread of its own, once the user saves the file, and at most once: a
    second fetch of the file on the web fails. So it must not read or change a view or the
    model. Read what it needs where `StreamContent` is made, e.g. in a `DownloadView`'s
    `content`, and give it only those values. A write raises once the user no longer
    wants the file, e.g. the browser's download canceled: let the error through.
    """

    #: writes the file, e.g. with ``pyarrow.csv.CSVWriter(sink, schema)``
    write: Callable[[BinaryIO], object]


#: bytes a `DownloadSink` hands over at once: small writes are gathered, large ones cut
DOWNLOAD_CHUNK_SIZE = 256 * 1024


class DownloadCanceledError(Exception):
    """The file that a `StreamContent` writes is no longer wanted."""


class DownloadSink(io.RawIOBase):
    """The file that a `StreamContent` writes to, which hands its bytes over in pieces.

    `put` gets each piece, of `DOWNLOAD_CHUNK_SIZE` bytes but the last, as a copy: the
    writer may reuse its buffer. It raises `DownloadCanceledError` once the file is no
    longer wanted, so the writer stops at its next write. `close`, once the writer is
    done, hands over the last piece; `discard`, after it failed, drops it.
    """

    def __init__(self, put: Callable[[bytes], None]) -> None:
        super().__init__()
        self._put = put
        self._pending = bytearray()

    @override
    def writable(self) -> bool:
        return True

    @override
    def write(self, data: Buffer, /) -> int:
        view = memoryview(data).cast("B")
        self._pending += view
        while len(self._pending) >= DOWNLOAD_CHUNK_SIZE:
            piece = bytes(self._pending[:DOWNLOAD_CHUNK_SIZE])
            # cheap at the front: a bytearray moves its start
            del self._pending[:DOWNLOAD_CHUNK_SIZE]
            self._put(piece)
        return len(view)

    @override
    def close(self) -> None:
        """Hand over the last piece, then close; the writer may close it itself."""
        if not self.closed:
            piece = bytes(self._pending)
            self._pending.clear()
            self._put(piece)
        super().close()

    def discard(self) -> None:
        """Drop what wasn't handed over, and close: the file is incomplete."""
        self._pending.clear()
        super().close()


@attrs.frozen
class UploadedFile:
    """A file that the user gave to a `FileUploadView`, and where to read it."""

    #: the user's name for the file, as sent: to show, not to build a path with
    name: str
    #: its size in bytes
    size: int
    #: its type, such as ``text/csv``: what the browser says, not a check of the content;
    #: empty when unknown
    media_type: str
    #: the file to read
    path: Path
    #: whether `path` is a copy that the app's session owns, on the web, rather than the
    #: user's own file, on Qt and Textual
    is_temporary: bool = False

    @classmethod
    def of_path(cls, path: Path) -> UploadedFile:
        """Get the file that `path` names on this computer, without a copy."""
        return cls(path.name, path.stat().st_size, mimetypes.guess_type(path.name)[0] or "", path)


@define_view
class FileUploadMixin:
    """The fields of a file upload: the file the user gave, and `uploaded`.

    The web's copy of the file stays until the view's next upload or `clear`, and then until
    the main view's jobs are over, so a job can still read it. The end of the session removes
    it in any case. The file is not part of a study.
    """

    #: the file types the picker offers, by name: ``{"CSV": (".csv",)}``; on the web, a
    #: file of another type is refused
    extensions: dict[str, tuple[str, ...]] = attrs.field(
        factory=dict[str, tuple[str, ...]], metadata={OMIT: True}
    )
    #: the button's text
    browse_text: str = attrs.field(default=T("Choose a file"), metadata={UI_TEXT: True})
    #: shown beside the button while the view holds no file
    empty_text: str = attrs.field(default=T("No file chosen"), metadata={UI_TEXT: True})
    #: shown beside the button while the web uploads the file, when the button takes no click
    uploading_text: str = attrs.field(default=T("Uploading..."), metadata={UI_TEXT: True})
    #: the file the user gave last; None before the first, and after `clear`
    file: Optional[UploadedFile] = attrs.field(default=None, init=False, metadata={OMIT: True})
    #: the user gave a file, now in `file`
    uploaded: Signal[UploadedFile] = attrs.Factory(Signal[UploadedFile])

    def take_file(self, file: UploadedFile) -> None:
        """Hold `file` as the user's own choice, and emit `uploaded`."""
        self.file = file
        self.uploaded.emit(file)

    def clear(self) -> None:
        """Hold no file; on the web, the session deletes its copy once the jobs are over."""
        self.file = None


@define_view
class FolderPathInputMixin(PathInputMixin):
    """A folder's path, typed in the field or picked with the "…" button beside it.

    `text` holds the path as typed, and `path` reads it as a path. On Qt and Textual, the
    button opens the toolkit's folder dialog. The browser can't give the page a folder's
    path: on the web, the user types it, and the field has no button. With
    `server_roots`, the web's button lists the server's folders in them: a folder's item
    shows its folders, and "Choose this folder" puts the folder shown in the field.
    """

    #: the name of the "…" button, as a tooltip and a screen reader show it
    browse_text: str = attrs.field(default=T("Choose a folder"), metadata={UI_TEXT: True})
    #: the button of the web's list that picks the folder it shows
    choose_folder_text: str = attrs.field(default=T("Choose this folder"), metadata={UI_TEXT: True})
    partial_folder_text: str = attrs.field(
        default=T("This folder holds too many items to list them all: type the folder's path."),
        metadata={UI_TEXT: True},
    )


def with_extension(path: Path, extensions: Mapping[str, tuple[str, ...]]) -> Path:
    """Get `path` with the first of `extensions` added, unless it has one of them (any case)."""
    suffixes = [suffix for group in extensions.values() for suffix in group]
    if not suffixes or path.name.lower().endswith(tuple(s.lower() for s in suffixes)):
        return path
    return path.with_name(path.name + suffixes[0])


@define_view
class SavePathInputMixin(PathInputMixin):
    """A path to save a file to, typed in the field or picked with the "…" button beside it.

    `text` holds the path as typed, and `path` reads it as a path, with the first of
    `extensions` added if the name has none of them. On Qt and Textual, the button opens
    the toolkit's save dialog. The browser can't give the page a path: on the web, the
    user types it, and the field has no button. With `server_roots`, the web's button
    lists the server's folders in them and their files of `extensions`. A file's item
    takes its name, and "Save" picks the folder shown with the name typed. With
    `confirms_overwrite`, a file that exists is picked only once the user agrees to
    replace it, and `is_replace_agreed` remembers it, for `MainView.write_file` not to ask
    again at save time.
    """

    #: the file types the dialog offers, by name: ``{"PDF": (".pdf",)}``; the first one is
    #: added to a name that has none of them
    extensions: dict[str, tuple[str, ...]] = attrs.field(
        factory=dict[str, tuple[str, ...]], metadata={OMIT: True}
    )
    #: whether the user agrees to replace a file that exists, before it's picked
    confirms_overwrite: bool = attrs.field(default=True, metadata={OMIT: True})
    #: the name of the "…" button, as a tooltip and a screen reader show it
    browse_text: str = attrs.field(default=T("Save as"), metadata={UI_TEXT: True})
    partial_folder_text: str = attrs.field(
        default=T("This folder holds too many items to list them all: type the file's path."),
        metadata={UI_TEXT: True},
    )
    #: the texts of the web's list: the box of the file's name, and the button saving it
    file_name_text: str = attrs.field(default=T("File name"), metadata={UI_TEXT: True})
    save_text: str = attrs.field(default=T("Save"), metadata={UI_TEXT: True})
    #: the question before replacing a file, its ``{name}`` the file's, and its answer
    replace_question_text: str = attrs.field(
        default=T("{name} already exists. Replace it?"), metadata={UI_TEXT: True}
    )
    replace_text: str = attrs.field(default=T("Replace"), metadata={UI_TEXT: True})
    #: the file that exists which the user agreed to replace in the picker, if any
    _agreed_path: Optional[Path] = attrs.field(
        default=None, init=False, repr=False, eq=False, metadata={OMIT: True}
    )

    @property
    @override
    def path(self) -> Optional[Path]:
        """Get the path the field holds, the first extension added; None while it's empty.

        On the web, with `server_roots`, None too for a path typed outside them.
        """
        path = super().path
        return None if path is None else with_extension(path, self.extensions)

    @property
    def is_replace_agreed(self) -> bool:
        """Tell whether the user agreed in the picker to replace the file `path` names.

        False once the field holds another path, e.g. typed since.
        """
        path, agreed = self.path, self._agreed_path
        return path is not None and agreed is not None and path.resolve() == agreed.resolve()

    def remember_pick(self, path: Path) -> None:
        """Remember the path picked in the picker: a file that exists, the user agreed to replace.

        The renderers call it as the picker picks `path`, before the field shows it.
        """
        self._agreed_path = path if self.confirms_overwrite and path.exists() else None


@define_view
class SavePathInputView(SavePathInputMixin, View):
    """A path to save a file to, e.g. a report: typed, or picked from a save dialog."""

    _renderer_key = "save_path_input"


@define_view
class FolderPathInputView(FolderPathInputMixin, View):
    """A folder's path, e.g. where to write results: typed, or picked from a folder dialog."""

    _renderer_key = "folder_path_input"


@define_view
class FilePathInputView(FilePathInputMixin, View):
    """A file's path, e.g. a data file to read: typed, or picked from a file dialog."""

    _renderer_key = "file_path_input"


@define_view
class FileUploadView(FileUploadMixin, View):
    """A button with which the user gives the app a file, then the file's name."""

    _renderer_key = "file_upload"


def _partial_path(path: Path) -> Path:
    """Get a name beside `path`, its own, to write a file before it replaces `path`."""
    return path.with_name(f".{path.name}.{uuid.uuid4().hex}.partial")


def _publish(partial: Path, path: Path) -> None:
    """Replace `path` with the whole file `partial`, as one step, keeping `path`'s mode."""
    if path.exists():
        shutil.copymode(path, partial)
    partial.replace(path)


def save_download(
    main_view: MainView, path: Path, content: Union[bytes, Path, StreamContent]
) -> None:
    """Write a download's `content` to `path`, which the user chose; the status bar says how.

    For a backend that asks where to save a `MainView.download`. A failure leaves `path` as
    it was. A `StreamContent` writes in a job, the app staying responsive; New, Open and
    closing the app cancel it.
    """
    if isinstance(content, StreamContent):
        _save_stream(main_view, path, content)
        return
    target = path.resolve()
    partial = _partial_path(target)
    try:
        if isinstance(content, Path):
            shutil.copyfile(content, partial)
        else:
            partial.write_bytes(content)
        _publish(partial, target)
    except OSError as error:
        failed = main_view.tr("Can't save to {name}: {error}.")
        main_view.status_bar.show_message(failed.format(name=path.name, error=error))
        return
    finally:
        partial.unlink(missing_ok=True)
    main_view.status_bar.show_message(main_view.tr("Saved {name}.").format(name=path.name))


def _save_stream(main_view: MainView, path: Path, content: StreamContent) -> None:
    """Write a `StreamContent` to `path` in a job; the status bar says how it went."""
    job = main_view.jobs.start(_write_stream, content, path)
    # the texts of `save_download`, so that a translation says both
    saved = main_view.tr("Saved {name}.")
    failed = main_view.tr("Can't save to {name}: {error}.")
    show = main_view.status_bar.show_message

    def report(is_written: bool) -> None:
        if is_written:
            show(saved.format(name=path.name))

    job.finished.connect(report)
    job.failed.connect(lambda error: show(failed.format(name=path.name, error=error)))


def _write_stream(job: Job[bool], content: StreamContent, path: Path) -> bool:
    """Write a `StreamContent` to `path`, in a job; tell if it wrote it.

    A job canceled (New, Open, closing the app) stops at the writer's next write. Stopped,
    or failed, it leaves the file `path` as it was.
    """
    path = path.resolve()
    partial = _partial_path(path)
    try:
        with partial.open("wb") as file:

            def put(piece: bytes) -> None:
                if job.is_canceled:
                    raise DownloadCanceledError
                file.write(piece)

            sink = DownloadSink(put)
            try:
                content.write(cast("BinaryIO", sink))
                sink.close()
            except Exception:
                sink.discard()
                # the writer may have raised its own error for ours, e.g. Arrow's
                if job.is_canceled:
                    return False
                raise
        _publish(partial, path)
    finally:
        partial.unlink(missing_ok=True)
    return True


def _write_csv(job: Optional[Job[bool]], chunks: Iterator[str], path: Path) -> bool:
    """Write a large table's CSV, as `SourceTableView.csv_chunks` gives it, in a job or not.

    A job canceled (New, Open, closing the app) stops. Stopped, or failed (e.g. a cell the
    source can't read, a full disk), it leaves the file `path` as it was. Tell if it wrote it.
    """
    path = path.resolve()
    partial = _partial_path(path)
    try:
        with partial.open("w", encoding="utf-8", newline="") as file:
            for chunk in chunks:
                if job is not None and job.is_canceled:
                    return False
                file.write(chunk)
        _publish(partial, path)
    finally:
        partial.unlink(missing_ok=True)
    return True

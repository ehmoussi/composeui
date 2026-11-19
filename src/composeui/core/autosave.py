"""Autosave: a desktop app's unsaved work, saved to a folder of its own and opened after a crash.

On Qt and Textual, for a main view with `MainView.autosave`. Each running app holds a folder
of its own, locked while it runs, in the app's folder of the user's data directory. Every
`MainView.autosave_interval` seconds while the study has unsaved changes, the app saves a
snapshot there: the views' state and the model's data of the same moment, named by a record
swapped in last. A clean close deletes the folder. So a folder whose lock is free was left
by an app that ended without one, e.g. a crash: the next start opens its work.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

from composeui.core.jobs import starting_study
from composeui.core.model import InvalidStateError, Model
from composeui.core.study import has_data

if TYPE_CHECKING:
    from collections.abc import Iterator

    from composeui.core.model import PinnedData
    from composeui.core.view import MainView

__all__: list[str] = []

LOGGER = logging.getLogger("COMPOSEUI")

#: environment variable naming the folder of the apps' autosaves, instead of the user's
#: data directory: e.g. for tests
DIRECTORY_VARIABLE = "COMPOSEUI_AUTOSAVE_DIR"
#: the snapshot's record, which names its files
_RECORD_NAME = "record.json"
#: the file an instance's lock holds while it runs
_LOCK_NAME = "lock.sqlite"
#: the file a starting app locks while it looks for folders to recover and makes its own
_APP_LOCK_NAME = ".lock.sqlite"
#: seconds a starting app waits for another's look at the folders
_APP_LOCK_WAIT = 10.0
#: an instance's folder name; others, e.g. one moved aside, are never recovered
_INSTANCE_NAME = re.compile(r"[0-9a-f]{32}")
#: what an `app_id` may be: a folder's name on every platform
_APP_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
#: what a folder's name made from a class's can't hold
_NOT_IN_A_NAME = re.compile(r"[^A-Za-z0-9._-]")
#: the user's data directory by platform, under the home folder, unless a variable names it
_DATA_DIRECTORIES = {
    "win32": ("LOCALAPPDATA", ("AppData", "Local")),
    "darwin": (None, ("Library", "Application Support")),
}
_DEFAULT_DATA_DIRECTORY = ("XDG_DATA_HOME", (".local", "share"))


def data_directory() -> Path:
    """Get the folder of the apps' autosaves: `DIRECTORY_VARIABLE`'s, else ComposeUI's own.

    ComposeUI's in the user's data directory: its app folders never mix with another
    program's, whose folders a start would delete.
    """
    named = os.environ.get(DIRECTORY_VARIABLE, "")
    if named != "":
        return Path(named)
    variable, parts = _DATA_DIRECTORIES.get(sys.platform, _DEFAULT_DATA_DIRECTORY)
    value = "" if variable is None else os.environ.get(variable, "")
    return (Path(value) if value != "" else Path.home().joinpath(*parts)) / "composeui"


def app_folder_name(main_view_type: type[MainView]) -> str | None:
    """Get the name of the app's folder: its `MainView.app_id`, else its main view's class.

    A script's (``__main__``), whose class name another app may share, adds a digest of the
    script's path. None for a script without a file, e.g. ``python -c``. Raises `ValueError`
    for an `app_id` that can't name a folder.
    """
    app_id = main_view_type.app_id
    if app_id is None:
        module = main_view_type.__module__
        name = main_view_type.__qualname__
        if module == "__main__":
            file = getattr(sys.modules.get(module), "__file__", None)
            if file is None:
                return None
            digest = hashlib.blake2b(str(Path(file).resolve()).encode(), digest_size=4)
            name = f"{name}-{digest.hexdigest()}"
        else:
            name = f"{module}.{name}"
        # e.g. a class defined in a function: `<locals>`
        return _NOT_IN_A_NAME.sub("_", name)
    if _APP_ID.fullmatch(app_id) is None:
        msg = f"app_id {app_id!r} can't name a folder: use letters, digits, '.', '_' and '-'"
        raise ValueError(msg)
    return app_id


def _lock(path: Path, wait: float = 0.0) -> sqlite3.Connection | None:
    """Lock the file `path`, made if needed, waiting `wait` seconds; None if another holds it.

    A SQLite database's exclusive lock: the system releases it when the process ends, also
    in a crash, and another connection of the same process can't take it either. Raises
    `sqlite3.Error` for a file that can't be opened, e.g. a folder.
    """
    connection = sqlite3.connect(
        str(path), timeout=wait, isolation_level=None, check_same_thread=False
    )
    try:
        connection.execute("BEGIN EXCLUSIVE")
    # locked; or a file that can't be locked, e.g. not a database: not ours either
    except sqlite3.DatabaseError:
        connection.close()
        return None
    return connection


class _Record(NamedTuple):
    """A snapshot's files, in its folder, and the study file that was open."""

    views: str
    data: str | None
    study: str | None
    #: the study file's modification time as it was opened or saved (``st_mtime_ns``): Save
    #: asks before it writes over the file changed since; None if not known
    study_time: int | None = None

    @classmethod
    def read(cls, path: Path, *, needs_data: bool) -> _Record:
        """Read the record `path`; raise `InvalidStateError` for one that isn't a record.

        With `needs_data`, the snapshot must have the model's data.
        """
        try:
            content = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as error:
            msg = "its record isn't valid"
            raise InvalidStateError(msg) from error
        if not isinstance(content, dict):
            msg = "its record isn't valid"
            raise InvalidStateError(msg)
        views, data, study, study_time = (
            content.get(key) for key in ("views", "data", "study", "study_time")
        )
        names = [name for name in (views, data) if name is not None]
        if (
            not isinstance(views, str)
            or not all(isinstance(n, str) and Path(n).name == n != "" for n in names)
            or not (study is None or isinstance(study, str))
            or not (study_time is None or type(study_time) is int)
            or (needs_data and data is None)
        ):
            msg = "its record isn't valid"
            raise InvalidStateError(msg)
        return cls(views, data, study, study_time)


class _Snapshot(NamedTuple):
    """What a tick took on the main thread, for the autosave's thread to write."""

    generation: int
    #: the study's mark (`MainView._mark_saved`) at the tick, and the data's revision
    mark: tuple[str, int, int]
    file_data: dict[str, Any]
    record: _Record
    #: the model's data pinned at the tick, to copy into `record.data`; None when it was
    #: copied at the tick already, or is the previous snapshot's
    pinned: PinnedData | None
    #: the files this snapshot wrote, which a snapshot not swapped in deletes
    written: tuple[str, ...]


class _Folder:
    """An instance's folder, its lock and its record: what the autosave's thread reaches.

    It holds no view, so the thread never holds the last reference to a main view (see
    `tests/conftest.py`). Its lock (`_guard`) orders the thread's swap of the record with
    New, Open and Save on the main thread, or Textual's file worker, which forget it.
    """

    def __init__(
        self, path: Path, lock: sqlite3.Connection, *, left_at: float | None = None
    ) -> None:
        self.path = path
        #: whether an app ended uncleanly left it, with a snapshot to restore, saved at
        #: `left_at` (a modification time)
        self.is_left = left_at is not None
        self.left_at = 0.0 if left_at is None else left_at
        self._lock = lock
        self._guard = threading.Lock()
        #: raised by each `forget`: a snapshot of an older generation is never swapped in
        self.generation = 0
        #: the snapshot swapped in, and the study's mark it saved
        self.record: _Record | None = None
        self.mark: tuple[str, int, int] | None = None
        #: the last write's failure, not shown yet
        self.failure: Exception | None = None

    def forget(self) -> None:
        """Delete the snapshot: the study was saved, or replaced (New, Open)."""
        with self._guard:
            self.generation += 1
            record, self.record, self.mark = self.record, None, None
            if record is not None:
                (self.path / _RECORD_NAME).unlink(missing_ok=True)
                self._delete(record.views, record.data)

    def write(self, snapshot: _Snapshot) -> None:
        """Write a snapshot's files, then swap its record in: in the autosave's thread."""
        try:
            self._write_files(snapshot)
            with self._guard:
                if snapshot.generation != self.generation:  # forgotten meanwhile
                    self._delete(*snapshot.written)
                    return
                partial = self.path / f".{_RECORD_NAME}.partial"
                _write_synced(partial, json.dumps(snapshot.record._asdict()).encode())
                partial.replace(self.path / _RECORD_NAME)
                previous, self.record, self.mark = self.record, snapshot.record, snapshot.mark
                self.failure = None
                if previous is not None:
                    kept = {snapshot.record.views, snapshot.record.data}
                    self._delete(*(n for n in (previous.views, previous.data) if n not in kept))
            LOGGER.info(
                "Autosaved the unsaved work in %s%s",
                self.path,
                ", the model's data included" if snapshot.record.data in snapshot.written else "",
            )
        except (OSError, sqlite3.Error) as error:
            # e.g. a full disk: the previous snapshot stays, the next tick tries again
            LOGGER.warning("The unsaved work can't be autosaved: %s", error)
            with self._guard:
                self.failure = error
                self._delete(*snapshot.written)
        finally:
            if snapshot.pinned is not None:
                snapshot.pinned.release()

    def _write_files(self, snapshot: _Snapshot) -> None:
        _write_synced(
            self.path / snapshot.record.views, json.dumps(snapshot.file_data).encode("utf-8")
        )
        if snapshot.pinned is not None:
            assert snapshot.record.data is not None  # pinned for it
            data_path = self.path / snapshot.record.data
            snapshot.pinned.write(data_path)
            _sync(data_path)

    def _delete(self, *names: str | None) -> None:
        for name in filter(None, names):
            (self.path / name).unlink(missing_ok=True)

    def take_failure(self) -> Exception | None:
        with self._guard:
            failure, self.failure = self.failure, None
            return failure

    def leave(self, *, aside: bool) -> _Folder:
        """Leave the folder, its work kept for a later start; get a new one for this instance.

        `aside`, for work that doesn't open, renames it: kept, and not tried at each start.
        """
        app_folder = self.path.parent
        with _app_lock(app_folder):
            self.release()
            if aside:
                stamp = time.strftime("%Y%m%d%H%M%S")
                moved = self.path.replace(self.path.with_name(f"{self.path.name}.invalid-{stamp}"))
                LOGGER.warning("The unsaved work that can't open is kept in %s", moved)
            return _new_folder(app_folder)

    def clear(self) -> None:
        """Delete the work an app ended uncleanly left: the folder is this instance's own."""
        with self._guard:
            self.generation += 1
            self.record, self.mark, self.is_left = None, None, False
            for path in self.path.iterdir():
                if not path.name.startswith(_LOCK_NAME):
                    path.unlink(missing_ok=True)

    def release(self) -> None:
        """Release the lock, the folder kept: the next start recovers its snapshot, if any."""
        self._lock.close()

    def delete(self) -> None:
        """Delete the folder: a clean close.

        Its record first, while the lock is held: an app starting once the lock is released
        finds no snapshot to restore, and deletes the folder too.
        """
        (self.path / _RECORD_NAME).unlink(missing_ok=True)
        self.release()  # before the rest: Windows deletes no file open
        shutil.rmtree(self.path, ignore_errors=True)


def _data_revision(model: Model | None) -> int:
    """Get the model's count of every change of its data, read before the data is pinned."""
    return 0 if model is None else model._data_revision()  # noqa: SLF001


def _study_file_of(main_view: MainView) -> tuple[str | None, int | None]:
    """Get the study's file, and its time as opened or saved, if known, for a record."""
    study = main_view.state_filepath
    if study is None:
        return None, None
    known = main_view._study_file  # noqa: SLF001
    return str(study), known[1] if known is not None and known[0] == str(study) else None


def _write_synced(path: Path, content: bytes) -> None:
    with path.open("wb") as file:
        file.write(content)
        file.flush()
        os.fsync(file.fileno())


def _sync(path: Path) -> None:
    with path.open("rb+") as file:
        os.fsync(file.fileno())


def _claim_folder(app_folder: Path, *, restores: bool) -> _Folder:
    """Take this instance's folder: if it `restores`, the newest one left with a snapshot.

    Else, or without one, a new one. The others left with a snapshot are kept for the next
    starts; those left without one are deleted. Under the app's lock, so two apps starting
    together never take the same.
    """
    app_folder.mkdir(parents=True, exist_ok=True)
    with _app_lock(app_folder):
        left: list[tuple[float, Path, sqlite3.Connection]] = []
        for path in app_folder.iterdir():
            if not path.is_dir() or _INSTANCE_NAME.fullmatch(path.name) is None:
                continue
            lock = _lock(path / _LOCK_NAME)
            if lock is None:  # its app runs
                continue
            record_path = path / _RECORD_NAME
            if record_path.is_file():
                left.append((record_path.stat().st_mtime, path, lock))
            else:  # an app ended before its first snapshot
                lock.close()
                shutil.rmtree(path, ignore_errors=True)
        left.sort(key=lambda found: found[0], reverse=True)
        for _modified, _path, lock in left[1 if restores else 0 :]:
            lock.close()
        if restores and len(left) > 0:
            modified, path, lock = left[0]
            return _Folder(path, lock, left_at=modified)
        return _new_folder(app_folder)


@contextlib.contextmanager
def _app_lock(app_folder: Path) -> Iterator[None]:
    """Hold the app's lock: one app at a time looks for folders left, or makes its own."""
    lock = _lock(app_folder / _APP_LOCK_NAME, _APP_LOCK_WAIT)
    if lock is None:
        msg = f"another app holds {app_folder} too long"
        raise OSError(msg)
    try:
        yield
    finally:
        lock.close()


def _new_folder(app_folder: Path) -> _Folder:
    path = app_folder / uuid.uuid4().hex
    path.mkdir()
    lock = _lock(path / _LOCK_NAME)
    assert lock is not None  # a new folder, under the app's lock
    return _Folder(path, lock)


class Autosave:
    """A main view's autosave: its folder, the snapshot it saved, and the thread writing one.

    The backend calls `tick` every `MainView.autosave_interval` seconds on the main thread,
    and `close` once the app ends. `MainView._mark_saved` forgets the snapshot.
    """

    def __init__(self, main_view: MainView, model: Model | None, folder: _Folder) -> None:
        self._main_view = main_view
        self._model = model
        self._folder = folder
        self._thread: threading.Thread | None = None
        #: set when the folder can't be used: the app goes on without autosave
        self._is_stopped = False

    @classmethod
    def start(cls, main_view: MainView, model: Model | None, *, restores: bool) -> Autosave | None:
        """Take the app's folder; None if it can't, the app then runs without autosave.

        If it `restores`, the folder of an app ended uncleanly comes first, for `restore`.
        Raises `ValueError` for an `app_id` that can't name a folder (`app_folder_name`).
        """
        name = app_folder_name(type(main_view))
        if name is None:
            LOGGER.warning(
                "The app doesn't autosave: its script has no file to name its folder after;"
                " set its main view's app_id"
            )
            return None
        app_folder = data_directory() / name
        try:
            folder = _claim_folder(app_folder, restores=restores)
        except (OSError, sqlite3.Error) as error:
            LOGGER.warning("The app doesn't autosave: %s", error)
            return None
        return cls(main_view, model, folder)

    def ask_restore(self) -> None:
        """Ask the user whether to restore the work an app ended uncleanly left, if any.

        Through the main view's `restore_work` question; the backend calls it once it shows
        the main view. Nothing is written meanwhile.
        """
        if not self._folder.is_left:
            return
        self._main_view.restore_work.ask_restore(
            time.strftime("%Y-%m-%d %H:%M", time.localtime(self._folder.left_at)),
            restore=self._restore,
            discard=self._discard,
            later=self._later,
        )

    def _restore(self) -> None:
        """Open the work left: the study is marked unsaved, and keeps the name of its file.

        Work that doesn't open is moved aside, and the status bar says why.
        """
        main_view, model = self._main_view, self._model
        path = self._folder.path
        try:
            record = _Record.read(path / _RECORD_NAME, needs_data=has_data(model))
            state = json.loads((path / record.views).read_text(encoding="utf-8"))
            data = main_view.state_data_from_file(state)
            main_view.check_state_data(data)
            if has_data(model):
                assert model is not None  # has data
                assert record.data is not None  # read with `needs_data`
                main_view.jobs.drop()  # before the data is replaced, as `open_study` does
                model.open_data(path / record.data)
        except (InvalidStateError, OSError, ValueError) as error:
            LOGGER.warning("The unsaved work of %s can't open: %s", path, error)
            message = main_view.tr("Can't restore the unsaved work: {error}.")
            main_view.status_bar.show_message(message.format(error=error))
            self._leave(aside=True)
            return
        main_view.load_state_data(data)
        main_view.state_filepath = None if record.study is None else Path(record.study)
        main_view._study_file = (  # noqa: SLF001 (what Save compares the file with)
            None
            if record.study is None or record.study_time is None
            else (record.study, record.study_time)
        )
        with starting_study(main_view.jobs):
            if model is not None:
                model.loaded()
            main_view.loaded.emit()
        main_view._mark_unsaved()  # noqa: SLF001 (never saved by the user)
        # the snapshot is this instance's now: kept until the next one, or a clean close
        folder = self._folder
        folder.record, folder.is_left = record, False
        # what the snapshot holds
        folder.mark = (*main_view._study_mark(), _data_revision(model))  # noqa: SLF001
        LOGGER.info("Restored the unsaved work in %s", path)

    def _discard(self) -> None:
        self._folder.clear()
        LOGGER.info("Discarded the unsaved work in %s", self._folder.path)

    def _later(self) -> None:
        """Keep the work left for the next start: this app takes a new folder."""
        self._leave(aside=False)

    def _leave(self, *, aside: bool) -> None:
        try:
            self._folder = self._folder.leave(aside=aside)
        except (OSError, sqlite3.Error) as error:
            # its work is kept for the next start; this app saves none
            LOGGER.warning("The app doesn't autosave: %s", error)
            self._folder.release()
            self._is_stopped = True

    def forget(self) -> None:
        """Delete the snapshot, as the study was saved, or replaced (New, Open)."""
        self._folder.forget()

    def tick(self) -> None:
        """Start a snapshot if the study changed since the last one, unless one is written."""
        if (
            self._is_stopped
            # the folder holds the work left, until the user answers; then it's this app's
            or self._folder.is_left
            or (self._thread is not None and self._thread.is_alive())
        ):
            return
        main_view, model = self._main_view, self._model
        failure = self._folder.take_failure()
        if failure is not None:
            message = main_view.tr("Can't autosave the unsaved work: {error}.")
            main_view.status_bar.show_message(message.format(error=failure))
        file_data = main_view.file_data()
        study_mark = main_view._study_mark(file_data["views"])  # noqa: SLF001 (Save's own)
        # and every change of the data, the start's jobs' included, which a snapshot copies
        mark = (*study_mark, _data_revision(model))
        saved = main_view._saved_study  # noqa: SLF001
        folder = self._folder
        if saved is None or saved == study_mark:  # nothing to lose, e.g. a change undone
            if folder.record is not None:
                folder.forget()
            return
        previous = folder.record
        if mark == folder.mark:
            return
        name = uuid.uuid4().hex
        views = f"views-{name}.json"
        written = [views]
        data = None
        pinned = None
        if has_data(model):
            assert model is not None  # has data
            # the version read before the data is pinned: a write between them is copied
            # by the next tick, never skipped. A model that doesn't count its changes is
            # copied each time
            if (
                previous is not None
                and folder.mark is not None
                and folder.mark[2] == mark[2]
                and type(model).data_version is not Model.data_version
            ):
                data = previous.data
            else:
                data = f"data-{name}{Path(model.data_name or '').suffix}"
                written.append(data)
                try:
                    pinned = model._pin_data()  # noqa: SLF001
                    if pinned is None:  # copied now, on the main thread
                        model.save_data(folder.path / data)
                except (OSError, sqlite3.Error) as error:
                    LOGGER.warning("The unsaved work can't be autosaved: %s", error)
                    folder.failure = error
                    (folder.path / data).unlink(missing_ok=True)
                    return
        snapshot = _Snapshot(
            folder.generation,
            mark,
            file_data,
            _Record(views, data, *_study_file_of(main_view)),
            pinned,
            tuple(written),
        )
        # a daemon: a crash, or a kill, doesn't wait for it
        self._thread = threading.Thread(
            target=folder.write, args=(snapshot,), name="composeui-autosave", daemon=True
        )
        self._thread.start()

    def wait(self) -> None:
        """Wait for the snapshot being written, if any."""
        if self._thread is not None:
            self._thread.join()

    def close(self, *, clean: bool) -> None:
        """Stop, once the snapshot being written is; a `clean` close deletes the folder.

        Unclean, e.g. the app's loop raised, the folder is kept for the next start; so is the
        work left by another app, before the user answers whether to restore it.
        """
        self.wait()
        if self._is_stopped:
            return  # released already
        if clean and not self._folder.is_left:
            self._folder.delete()
        else:
            self._folder.release()

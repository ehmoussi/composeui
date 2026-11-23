"""A process's temporary and unfinished files, which the next start removes after a crash.

Each process keeps its temporary files in a folder of its own, in a folder of the user's in
the system's temporary folder. It holds a lock in its folder while it runs, which the
operating system releases when the process ends, however it ends. An app's start removes
the folders that no process holds, and the unfinished files beside the user's files that
they name.
"""

from __future__ import annotations

import atexit
import contextlib
import json
import logging
import os
import shutil
import sqlite3
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__: list[str] = []

LOGGER = logging.getLogger("COMPOSEUI")
_LOCK_NAME = "lock.sqlite"
_PARTIALS_NAME = "partials"
#: seconds that a folder no process holds is left alone: its process locks it once made
_GRACE_SECONDS = 60.0
#: an unfinished file's own, and those SQLite makes beside a database
_PARTIAL_SUFFIXES = ("", "-wal", "-shm", "-journal")


class _Scratch:
    """The process's own folders, one in each temporary folder that it used."""

    lock = threading.Lock()
    #: the process's folder in each user's folder (`_root`) that it used
    folders: dict[Path, Path] = {}  # noqa: RUF012 (the process's, never replaced)
    #: hold the locks of the process's folders, and of the other processes' folders that it
    #: uses, e.g. a reload's supervisor's
    connections: dict[Path, sqlite3.Connection] = {}  # noqa: RUF012 (as `folders`)
    #: the users' folders whose abandoned folders this process removed
    swept: set[Path] = set()  # noqa: RUF012 (as `folders`)
    #: the users' folders refused as not their own, which the process warned of once
    refused: set[Path] = set()  # noqa: RUF012 (as `folders`)


def _root() -> Path:
    # a shared temporary folder (POSIX) has one per user: another user can't remove its files
    name = f"composeui-scratch-{os.getuid()}" if os.name == "posix" else "composeui-scratch"
    return Path(tempfile.gettempdir()).resolve() / name


def _hold(path: Path) -> sqlite3.Connection:
    """Hold the shared lock of a folder's lock file, which an exclusive one then waits for."""
    connection = sqlite3.connect(str(path), timeout=0, check_same_thread=False)
    connection.execute("BEGIN")
    connection.execute("SELECT count(*) FROM sqlite_master").fetchone()
    return connection


def scratch_directory() -> Path:
    """Get this process's folder for its temporary files, made on the first call.

    The folder is in the system's temporary folder that `tempfile.gettempdir` gives now.
    """
    root = _root()
    with _Scratch.lock:
        folder = _Scratch.folders.get(root)
        if folder is None:
            if _sweep(root):
                folder = root / uuid.uuid4().hex
                folder.mkdir(mode=0o700)
            else:  # not the user's own: no start would remove what this process leaves
                folder = Path(tempfile.mkdtemp(prefix="composeui-"))
            _Scratch.connections[folder] = _hold(folder / _LOCK_NAME)
            _Scratch.folders[root] = folder
        return folder


def hold_scratch(folder: Path) -> None:
    """Hold `folder`, another process's (`scratch_directory`), until this process ends.

    E.g. a reload's child, which goes on using its supervisor's files if it's killed.
    """
    lock = folder / _LOCK_NAME
    with _Scratch.lock:
        # one that `scratch_directory` made has its lock: not e.g. a test's own folder
        if folder not in _Scratch.connections and lock.exists():
            _Scratch.connections[folder] = _hold(lock)


def cleanup_abandoned() -> None:
    """Remove the folders of the processes that ended, with the unfinished files they name."""
    # an app that needs no temporary file starts without them
    with contextlib.suppress(OSError):
        _sweep(_root())


def _sweep(root: Path) -> bool:
    """Remove the folders in `root` that no process holds, once per process.

    Tell whether `root` is the user's own folder: else another user could change what it holds,
    or put a file at its path to stop the app.
    """
    # a file or a broken link at its path: refused below, never an error that stops the app
    with contextlib.suppress(FileExistsError):
        root.mkdir(mode=0o700, exist_ok=True)
    if not root.is_dir() or _CAN_CHANGE(root):
        with _SWEEP_LOCK:  # once: the app's start and its first temporary file both check it
            is_new = root not in _Scratch.refused
            _Scratch.refused.add(root)
        if is_new:
            LOGGER.warning("%s isn't the user's own folder: a crash's files stay", root)
        return False
    with _SWEEP_LOCK:
        if root in _Scratch.swept:
            return True
        _Scratch.swept.add(root)
    now = time.time()
    for folder in root.iterdir():
        # e.g. one that another start's sweep removed meanwhile
        with contextlib.suppress(OSError):
            if now - folder.stat().st_mtime >= _GRACE_SECONDS and not _is_held(folder):
                _remove_partials(folder)
                shutil.rmtree(folder, ignore_errors=True)
    return True


_SWEEP_LOCK = threading.Lock()


def _others_can_change(root: Path) -> bool:  # posix only
    """Tell whether another user owns `root`, or may write in it."""
    info = root.lstat()
    return info.st_uid != os.getuid() or info.st_mode & 0o077 != 0


def _nobody_else_can_change(_root: Path) -> bool:  # windows only
    return False


# Windows gives each user a temporary folder of their own
_CAN_CHANGE = _others_can_change if os.name == "posix" else _nobody_else_can_change


def _is_held(folder: Path) -> bool:
    """Tell whether a process holds `folder`'s lock."""
    try:
        with contextlib.closing(sqlite3.connect(str(folder / _LOCK_NAME), timeout=0)) as lock:
            lock.execute("BEGIN EXCLUSIVE")
    except sqlite3.Error:
        return True
    # released before the folder is removed: Windows doesn't remove an open file
    return False


def _remove_partials(folder: Path) -> None:
    """Remove the unfinished files that `folder`'s records name, beside the user's files."""
    for record in (folder / _PARTIALS_NAME).glob("*.json"):
        with contextlib.suppress(OSError, ValueError, KeyError, TypeError):
            partial = json.loads(record.read_text(encoding="utf-8"))["path"]
            for suffix in _PARTIAL_SUFFIXES:
                Path(f"{partial}{suffix}").unlink(missing_ok=True)


@contextlib.contextmanager
def partial_path(path: Path) -> Iterator[Path]:
    """Get a path beside `path`, its own, for a file renamed to `path` once complete.

    Removed on the way out, unless renamed; after a crash, by the next start.
    """
    partial = path.with_name(f".{path.name}.{uuid.uuid4().hex}.partial")
    records = scratch_directory() / _PARTIALS_NAME
    records.mkdir(exist_ok=True)
    record = records / f"{uuid.uuid4().hex}.json"
    written = record.with_suffix(".tmp")
    written.write_text(json.dumps({"path": str(partial.absolute())}), encoding="utf-8")
    written.replace(record)  # whole or absent: a crash may come at any line
    try:
        yield partial
    finally:
        for suffix in _PARTIAL_SUFFIXES:
            Path(f"{partial}{suffix}").unlink(missing_ok=True)
        record.unlink(missing_ok=True)


@atexit.register
def _remove_at_exit() -> None:
    """Remove this process's folders as it exits, those with nothing left in them.

    Registered as the module is imported: before what closes the files in them, so it runs
    after. The next start removes the others.
    """
    for folder in _Scratch.folders.values():
        with contextlib.suppress(OSError):
            left = {child.name for child in folder.iterdir()} - {_LOCK_NAME, _PARTIALS_NAME}
            if len(left) == 0 and not any((folder / _PARTIALS_NAME).glob("*.json")):
                _Scratch.connections.pop(folder).close()  # Windows doesn't remove an open file
                shutil.rmtree(folder, ignore_errors=True)

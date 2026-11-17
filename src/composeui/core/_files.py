"""Owned scratch directories and unfinished files, reclaimed after their process ends."""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import stat
import tempfile
import threading
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Generator

__all__: list[str] = []

LOGGER = logging.getLogger("COMPOSEUI")
_NAME = re.compile(r"[0-9a-f]{32}")
_GUARD = threading.RLock()
_CLEANED: set[Path] = set()
_LOCK = "lock.sqlite"
_RECORD = "partial.json"


def _root() -> Path:
    # A shared temporary directory must not make one user's files another user's to delete.
    user = hashlib.sha256(os.fsencode(Path.home())).hexdigest()[:16]
    return Path(tempfile.gettempdir()) / f"composeui-scratch-{user}"


def _check_root(root: Path) -> None:
    info = root.lstat()
    if not stat.S_ISDIR(info.st_mode) or (
        os.name == "posix" and (info.st_uid != os.getuid() or info.st_mode & 0o077)
    ):
        msg = f"Scratch directory is not private: {root}"
        raise OSError(msg)


def _lock(path: Path, *, wait: float = 0.0) -> sqlite3.Connection | None:
    if path.is_symlink():
        msg = f"Scratch lock is a symbolic link: {path}"
        raise OSError(msg)
    connection = sqlite3.connect(str(path), timeout=wait, check_same_thread=False)
    try:
        connection.execute("BEGIN EXCLUSIVE")
    except sqlite3.DatabaseError:
        connection.close()
        return None
    return connection


@contextlib.contextmanager
def _starting(root: Path) -> Generator[None]:
    connection = _lock(root / ".lock.sqlite", wait=10.0)
    if connection is None:
        msg = f"Scratch directory is busy: {root}"
        raise OSError(msg)
    try:
        if root not in _CLEANED:
            _sweep(root)
            _CLEANED.add(root)
        yield
    finally:
        connection.close()


def cleanup_abandoned() -> None:
    """Remove scratch resources whose process no longer holds their lock."""
    try:
        with _GUARD:
            root = _root()
            if not root.exists() and not root.is_symlink():
                return
            _check_root(root)
            with _starting(root):
                pass
    except (OSError, sqlite3.Error) as error:
        # Cleanup must not prevent an app that needs no scratch files from starting.
        LOGGER.warning("Can't clean abandoned scratch files: %s", error)


def _sweep(root: Path) -> None:
    for directory in root.iterdir():
        if (
            _NAME.fullmatch(directory.name) is None
            or directory.is_symlink()
            or not directory.is_dir()
        ):
            continue
        connection = None
        try:
            connection = _lock(directory / _LOCK)
            if connection is None:  # another process still owns it
                continue
            if not _remove_partial(directory):
                LOGGER.warning("Kept an unrecognized scratch record in %s", directory)
                continue
            connection.close()  # Windows won't delete an open database
            connection = None
            shutil.rmtree(directory)
        except (OSError, sqlite3.Error) as error:
            LOGGER.warning("Can't remove abandoned scratch directory %s: %s", directory, error)
        finally:
            if connection is not None:
                connection.close()


def _recorded_parent(record: Path) -> tuple[Path, dict[str, Any]]:
    data = json.loads(record.read_text(encoding="utf-8"))
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("parent"), str)
        or type(data.get("device")) is not int
        or type(data.get("inode")) is not int
    ):
        msg = "Invalid scratch record"
        raise ValueError(msg)
    parent = Path(data["parent"])
    if not parent.is_absolute() or parent.resolve(strict=True) != parent:
        msg = "Scratch parent is not its recorded path"
        raise ValueError(msg)
    info = parent.stat()
    if (info.st_dev, info.st_ino) != (data["device"], data["inode"]):
        msg = "Scratch parent was replaced"
        raise ValueError(msg)
    return parent, data


def _remove_partial(directory: Path) -> bool:
    record = directory / _RECORD
    if record.is_symlink():
        return False
    if not record.exists():
        return True
    try:
        parent, data = _recorded_parent(record)
    except (ValueError, RuntimeError):  # Path.resolve raises RuntimeError for a link loop on 3.9
        return False
    except FileNotFoundError:
        return True  # the parent, and thus the unfinished save, are gone
    # No destination or arbitrary child path comes from the record.
    partial = parent / f".composeui-{directory.name}.partial"
    if partial.is_symlink() or (partial.exists() and not partial.is_dir()):
        return False
    return not partial.exists() or _remove_staging(partial, data)


def _remove_staging(partial: Path, data: dict[str, Any]) -> bool:
    if "staging" not in data:
        # Creation was interrupted before ownership was confirmed; no output started.
        partial.rmdir()
    else:
        info = partial.stat()
        if data["staging"] != [info.st_dev, info.st_ino]:
            return False
        shutil.rmtree(partial)
    return True


def _discard(directory: Path, connection: sqlite3.Connection) -> None:
    try:
        if not _remove_partial(directory):
            return
        # Order lock release and deletion with another process's startup sweep.
        with _GUARD, _starting(directory.parent):
            connection.close()
            shutil.rmtree(directory)
    finally:
        connection.close()


class ScratchDirectory:
    """A disposable directory locked until its last owner releases it.

    Only an explicit cleanup removes its files: a worker may still use them at exit.
    The operating system releases the lock at process death; the next start cleans up.
    """

    def __init__(self) -> None:
        with _GUARD:
            root = _root()
            root.mkdir(mode=0o700, exist_ok=True)
            _check_root(root)
            with _starting(root):
                self.path = root / uuid.uuid4().hex
                self.path.mkdir(mode=0o700)
                try:
                    connection = _lock(self.path / _LOCK)
                    assert connection is not None  # a new directory under the startup lock
                except BaseException:
                    shutil.rmtree(self.path)
                    raise
        self._connection: sqlite3.Connection | None = connection

    def cleanup(self) -> None:
        """Remove the directory once its files are no longer used."""
        connection, self._connection = self._connection, None
        if connection is not None:
            _discard(self.path, connection)

    def __enter__(self) -> Path:
        return self.path

    def __exit__(self, *_exc: object) -> None:
        self.cleanup()


@contextlib.contextmanager
def partial_file(path: Path) -> Generator[Path]:
    """Stage a file on its destination's filesystem, with an owner recorded before creation."""
    with ScratchDirectory() as directory:
        parent = path.parent.resolve(strict=True)
        info = parent.stat()
        data: dict[str, Any] = {
            "parent": str(parent),
            "device": info.st_dev,
            "inode": info.st_ino,
        }
        _write_record(directory, data)
        partial = parent / f".composeui-{directory.name}.partial"
        try:
            partial.mkdir(mode=0o700)
        except FileExistsError:
            # A pre-existing path isn't ours, even if its name happens to match.
            (directory / _RECORD).unlink()
            raise
        info = partial.stat()
        data["staging"] = [info.st_dev, info.st_ino]
        _write_record(directory, data)
        yield partial / path.name


def _write_record(directory: Path, data: dict[str, Any]) -> None:
    temporary = directory / f".{_RECORD}"
    with temporary.open("w", encoding="utf-8") as record:
        json.dump(data, record)
        record.flush()
        os.fsync(record.fileno())
    temporary.replace(directory / _RECORD)


def publish(partial: Path, path: Path) -> None:
    """Replace `path` with the whole file `partial`, keeping `path`'s mode."""
    if path.exists():
        shutil.copymode(path, partial)
    partial.replace(path)

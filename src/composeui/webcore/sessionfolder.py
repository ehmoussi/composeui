"""The folder where a web server keeps its sessions across restarts (`WebSettings`)."""

from __future__ import annotations

import math
import os
import secrets
import sys
from typing import IO, TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

#: the file of the key that signs the sessions' cookies, made once
KEY_NAME = "secret-key"
#: the key's file as it is written, before it takes its name
KEY_PARTIAL_NAME = f"{KEY_NAME}.partial"
#: the file that only the server serving the folder holds locked
LOCK_NAME = "lock"
#: the file of a session's save that holds when it was last used
SEEN_NAME = "last-seen"
#: the file of a session's save that names its user, absent without a login
USER_NAME = "user"
#: the folder of the sessions' uploads, each in a directory that one saved session names
UPLOADS_FOLDER_NAME = "uploads"


class FolderInUseError(RuntimeError):
    """Another server keeps its sessions in the folder."""


class FolderLock:
    """A lock on the folder that its server holds until it stops, or its process ends.

    The system releases it when the process ends, even killed: a crash leaves no lock.
    """

    def __init__(self, folder: Path) -> None:
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._file = (folder / LOCK_NAME).open("a+b")
        try:
            _lock(self._file)
        except OSError:
            self._file.close()
            msg = f"another server keeps its sessions in {folder}"
            raise FolderInUseError(msg) from None

    def release(self) -> None:
        """Let another server use the folder."""
        if sys.platform == "win32":  # windows only
            import msvcrt  # noqa: PLC0415 (Windows' module, which other systems lack)

            # at once: Windows releases a lock that a file closes with only later
            self._file.seek(0)
            msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
            self._file.close()
            return
        self._file.close()  # posix only: closing the file releases its lock


def _lock(file: IO[bytes]) -> None:
    """Lock `file` for this process alone, or raise `OSError` if another holds it."""
    if sys.platform == "win32":  # windows only
        import msvcrt  # noqa: PLC0415 (Windows' module, which other systems lack)

        # a lock on its first byte, which needn't exist
        file.seek(0)
        msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
        return
    import fcntl  # noqa: PLC0415 (Windows lacks the module)  # posix only

    fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)  # posix only


def folder_key(folder: Path) -> str:
    """Get the key in `folder`, made the first time: only its owner may read it.

    Under the folder's lock (`FolderLock`): no other server writes it at the same time.
    Written beside it, then put in its place: a crash leaves no key cut short.
    """
    path = folder / KEY_NAME
    if path.exists():
        key = path.read_text(encoding="ascii").strip()
        if key == "":
            # an empty key would sign cookies that anyone can forge
            msg = f"{path} holds no key: remove it, and the sessions' cookies change"
            raise ValueError(msg)
        return key
    key = secrets.token_urlsafe(32)
    partial = path.with_name(KEY_PARTIAL_NAME)
    # a new file, never one left there, which could be a link to another file
    partial.unlink(missing_ok=True)
    descriptor = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="ascii") as file:
        file.write(key)
    partial.replace(path)
    return key


def claim(folder: Path) -> None:
    """Refuse a folder that holds files of something else, which the server could remove.

    Its own folder holds the key once it served. Before, it may hold only what a server that
    stopped as it started left: its lock, or its key half written.
    """
    if (folder / KEY_NAME).exists():
        return
    others = sorted(
        path.name for path in folder.iterdir() if path.name not in {LOCK_NAME, KEY_PARTIAL_NAME}
    )
    if others:
        msg = (
            f"{folder} holds files of something else, such as {others[0]!r}: give the "
            "sessions a folder of their own"
        )
        raise ValueError(msg)


def write_seen(path: Path, seen: float) -> None:
    """Write when a session was last used, a clock time (`time.time`), at `path`."""
    path.write_text(repr(seen), encoding="ascii")


def read_seen(path: Path) -> float | None:
    """Read when a session was last used, a clock time; None if `path` doesn't say."""
    try:
        seen = float(path.read_text(encoding="ascii"))
    except (OSError, ValueError):
        return None
    return seen if math.isfinite(seen) else None


def write_user(path: Path, user: str | None) -> None:
    """Write the user of a session's save at `path`; nothing without one."""
    if user is not None:
        path.write_text(user, encoding="utf-8")


def read_user(path: Path) -> str | None:
    """Read the user of a session's save; None if `path` is absent.

    A damaged name names no user: no proxy sends the character that replaces a byte it
    can't read, and `UserHeaders` takes no empty id.
    """
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return None

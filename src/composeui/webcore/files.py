"""Temporary files owned by a server, or by its reload supervisor."""

from __future__ import annotations

import tempfile
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from composeui.core._files import ScratchDirectory

if TYPE_CHECKING:
    from collections.abc import Callable

    from composeui.core.jobs import Jobs

__all__: list[str] = []


class _Owner:
    def __init__(self, scratch: ScratchDirectory) -> None:
        self.scratch = scratch
        self._references = 1
        self._lock = threading.Lock()

    def hold(self) -> None:
        with self._lock:
            self._references += 1

    def release(self) -> None:
        with self._lock:
            self._references -= 1
            last = self._references == 0
        if last:
            self.scratch.cleanup()


class SessionFiles:
    """A server's files, kept until its sessions' workers and cleanup have ended.

    A reload supervisor owns `saved` across its child processes. A server without one
    takes a scratch directory of its own, only once it needs files.
    """

    def __init__(self, saved: Path | None = None) -> None:
        self._saved = saved
        held = None if saved is None else ScratchDirectory.borrow(saved)
        self._owner = None if held is None else _Owner(held)
        self._lock = threading.Lock()

    def directory(self) -> Path:
        with self._lock:
            if self._saved is not None:
                return self._saved
            if self._owner is None:
                self._owner = _Owner(ScratchDirectory())
            directory = self._owner.scratch.path / "sessions"
            directory.mkdir(exist_ok=True)
            return directory

    def upload_directory(self) -> Path:
        directory = self.directory() / ".uploads"
        directory.mkdir(exist_ok=True)
        return Path(tempfile.mkdtemp(prefix="composeui-", dir=directory))

    def after_workers(self, jobs: Jobs, cleanup: Callable[[], None]) -> None:
        with self._lock:
            owner = self._owner
            if owner is not None:
                owner.hold()

        def finish() -> None:
            try:
                cleanup()
            finally:
                if owner is not None:
                    owner.release()

        jobs.after_workers(finish)

    def close(self) -> None:
        with self._lock:
            owner, self._owner = self._owner, None
        if owner is not None:
            owner.release()

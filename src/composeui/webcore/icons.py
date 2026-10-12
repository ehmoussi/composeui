"""The image files the views name as icons, served at an address naming their content.

Only a file a renderer has asked an address for is served: the views name them, from
the app's code (`ActionView.icon` is never loaded from a study), so a request can't
name a file of its own. One registry for the process: every session runs the same code.
"""

from __future__ import annotations

import hashlib
import threading
from pathlib import Path
from typing import NamedTuple

#: the file types served, by suffix: images a browser shows in an `<img>` or a mask
_IMAGE_SUFFIXES = frozenset({".svg", ".png", ".gif", ".jpg", ".jpeg", ".webp", ".ico"})


class _IconFile(NamedTuple):
    mtime_ns: int
    #: its name in its address: its content's digest, then its suffix
    name: str


_lock = threading.Lock()
_by_path: dict[Path, _IconFile] = {}
_by_name: dict[str, Path] = {}


def icon_url(icon: str) -> str | None:
    """Get the address serving the image file at `icon`; None if it isn't one.

    A relative path is from the current directory, as Qt reads it. The address changes
    with the file's content, so a browser can keep it as long as it likes.
    """
    path = Path(icon).resolve()
    if path.suffix.lower() not in _IMAGE_SUFFIXES:
        return None
    try:
        mtime_ns = path.stat().st_mtime_ns
        with _lock:
            known = _by_path.get(path)
            if known is None or known.mtime_ns != mtime_ns:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
                if known is not None:
                    _by_name.pop(known.name, None)
                known = _IconFile(mtime_ns, f"{digest}{path.suffix.lower()}")
                _by_path[path] = known
                _by_name[known.name] = path
    except OSError:  # no such file: no icon, as on Qt
        return None
    return f"/icon/{known.name}"


def icon_path(name: str) -> Path | None:
    """Get the file served as `name` (see `icon_url`); None unless a view named it."""
    with _lock:
        return _by_name.get(name)

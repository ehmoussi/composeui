"""The files of the server that a file path field lists on the web, within its roots.

The browser names an item by its name in the folder listed, never by a path. Each item
is resolved, symbolic links and ``..`` included, and only one inside a root is listed or
picked: a link leading out of the roots shows nothing of where it leads.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

#: the most items of a folder read to list it: a larger folder costs the server too much,
#: and the user then types the file's path
MAX_ITEMS = 2000


class Item(NamedTuple):
    """A file or a folder of the folder listed."""

    name: str
    is_folder: bool


class Listing(NamedTuple):
    """The items of a folder, its folders first, and whether some were left out."""

    items: list[Item]
    is_partial: bool


def resolve_roots(roots: Iterable[Path]) -> list[Path]:
    """Get the folders of `roots` that exist, resolved, in order and once each."""
    resolved: list[Path] = []
    for root in roots:
        try:
            path = root.expanduser().resolve(strict=True)
        except (OSError, ValueError):  # ValueError: a NUL character
            continue
        if path.is_dir() and path not in resolved:
            resolved.append(path)
    return resolved


def is_within(path: Path, roots: list[Path]) -> bool:
    """Whether the resolved `path` is one of the resolved `roots`, or inside one."""
    return any(path == root or root in path.parents for root in roots)


def item_path(folder: Path, name: str, roots: list[Path]) -> Path | None:
    """Get the resolved path of `folder`'s item `name`, if it is inside `roots`.

    None for a name that isn't one item's (``..``, a separator), a hidden item's (starting
    with a dot), an item that doesn't exist, or one that a link leads out of the roots.
    """
    separators = [os.sep] if os.altsep is None else [os.sep, os.altsep]
    if name in ("", ".") or name.startswith(".") or any(sep in name for sep in separators):
        return None
    try:
        path = (folder / name).resolve(strict=True)
    # a loop of links raises RuntimeError before 3.13, a NUL character ValueError
    except (OSError, RuntimeError, ValueError):
        return None
    return path if is_within(path, roots) else None


def has_extension(name: str, extensions: tuple[str, ...]) -> bool:
    """Whether the file `name` ends with one of `extensions`, in any case; any if none."""
    return not extensions or name.lower().endswith(
        tuple(extension.lower() for extension in extensions)
    )


def list_folder(folder: Path, roots: list[Path], extensions: tuple[str, ...]) -> Listing:
    """List `folder`'s folders, then its files of `extensions` (all if none), by name.

    Hidden items and items outside `roots` are left out (see `item_path`). Raises
    `OSError` if the folder can't be read.
    """
    items: list[Item] = []
    is_partial = False
    with os.scandir(folder) as entries:
        for count, entry in enumerate(entries):
            if count == MAX_ITEMS:
                is_partial = True
                break
            path = item_path(folder, entry.name, roots)
            if path is None:
                continue
            if path.is_dir():
                items.append(Item(entry.name, is_folder=True))
            elif path.is_file() and has_extension(entry.name, extensions):
                items.append(Item(entry.name, is_folder=False))
    items.sort(key=lambda item: (not item.is_folder, item.name.lower(), item.name))
    return Listing(items, is_partial)

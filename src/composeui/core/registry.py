"""Map abstract renderer keys to each backend's concrete renderer classes.

Adding a backend means adding one `RendererType` member here, with its extra, one
``RENDERERS`` mapping in the backend's renderers module, and
``APPLICATION``/``MODEL_APPLICATION`` in its application module.

A package outside ComposeUI adds renderers with an entry point of the ``composeui.renderers``
group per backend: its name is the backend (``qt``, ``textual`` or ``web``) and its object
a mapping like ``RENDERERS``. Each key starts with the package's name, such as
``composeui_cad.geometry``: a backend loads a package's renderers only to look for a key of
that package that it doesn't have itself.
"""

from __future__ import annotations

import enum
import functools
import importlib
import importlib.metadata
import re
from typing import TYPE_CHECKING, Any, Callable, NamedTuple

if TYPE_CHECKING:
    from collections.abc import Mapping
    from importlib.metadata import EntryPoint

    from composeui.core.renderer import Renderer

__all__ = ["Backend", "RendererType", "create_renderer"]

#: the group of the entry points by which a package adds renderers to a backend
RENDERERS_GROUP = "composeui.renderers"


class Backend(NamedTuple):
    """A backend's modules, by dotted path: none is imported until the backend is used."""

    #: exposes the ``RENDERERS`` mapping
    renderers: str
    #: exposes ``APPLICATION`` and ``MODEL_APPLICATION``, the backend's application classes
    applications: str
    #: the package's extra that installs what the backend imports, e.g. ``"web"``
    extra: str
    #: the top-level modules the extra installs: `run` names those missing
    packages: tuple[str, ...]


class RendererType(enum.Enum):
    """A renderer backend, identified by its modules."""

    QT = Backend(
        "composeui.qtcore.renderers",
        "composeui.qtcore.qtapplication",
        "pyside6",
        ("PySide6", "pyqtgraph", "qtpy"),
    )
    TEXTUAL = Backend(
        "composeui.textualcore.renderers",
        "composeui.textualcore.textualapplication",
        "tui",
        ("textual", "textual_fspicker", "textual_plotext"),
    )
    WEB = Backend(
        "composeui.webcore.renderers",
        "composeui.webcore.webapplication",
        "web",
        ("itsdangerous", "markdown_it", "markupsafe", "python_multipart", "starlette", "uvicorn"),
    )


_Factory = Callable[[Any], "Renderer[Any, Any]"]


def _built_in(renderer_type: RendererType) -> Mapping[str, _Factory]:
    return importlib.import_module(renderer_type.value.renderers).RENDERERS  # type: ignore[no-any-return]


def _factory(renderer_type: RendererType, key: str) -> _Factory | None:
    """Get the renderer class of `key`: the backend's own, else the one its package adds."""
    factory = _built_in(renderer_type).get(key)
    if factory is None:
        factory = _package_renderers(renderer_type, key.partition(".")[0]).get(key)
    return factory


@functools.cache
def _entry_points(renderer_type: RendererType) -> dict[str, list[tuple[str, EntryPoint]]]:
    """Find, once, the entry points that add renderers to `renderer_type`'s backend.

    Each comes with its distribution's name, under the top-level module it names. None is
    loaded. A distribution also further on the path is hidden by the first, as on import.
    """
    backend = renderer_type.name.lower()
    found: dict[str, list[tuple[str, EntryPoint]]] = {}
    seen: set[str] = set()
    for distribution in importlib.metadata.distributions():
        entry_points = [
            entry_point
            for entry_point in distribution.entry_points
            if entry_point.group == RENDERERS_GROUP and entry_point.name == backend
        ]
        if not entry_points:
            continue
        metadata = distribution.metadata  # read only here: it opens a file
        if "Name" not in metadata:  # an install cut short, which pip doesn't list
            continue
        name = metadata["Name"]
        normalized = re.sub(r"[-_.]+", "-", name).lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        for entry_point in entry_points:
            found.setdefault(entry_point.module.partition(".")[0], []).append((name, entry_point))
    return found


def _package_renderers(renderer_type: RendererType, package: str) -> dict[str, _Factory]:
    """Get the renderers that `package` adds to `renderer_type`'s backend.

    Not kept: each call takes the package's modules as they are, imported again by a reload
    too. Raise `ValueError` for a key the backend has, a key outside the package's name, and
    a key two distributions add.
    """
    built_in = _built_in(renderer_type)
    added: dict[str, _Factory] = {}
    owners: dict[str, str] = {}
    prefix = f"{package}."
    for name, entry_point in _entry_points(renderer_type).get(package, []):
        renderers: Mapping[str, _Factory] = entry_point.load()
        for key, factory in renderers.items():
            if key in built_in:
                msg = f"{name} adds the renderer key {key!r}, which ComposeUI has"
                raise ValueError(msg)
            if not key.startswith(prefix):
                msg = f"{name} adds the renderer key {key!r}, which doesn't start with {prefix!r}"
                raise ValueError(msg)
            if key in owners:
                msg = f"{owners[key]} and {name} both add the renderer key {key!r}"
                raise ValueError(msg)
            owners[key] = name
            added[key] = factory
    return added


def has_renderer(renderer_type: RendererType, key: str) -> bool:
    """Tell whether `renderer_type`'s backend registers `key`, so it shows such views."""
    return _factory(renderer_type, key) is not None


def renders_on_demand(renderer_type: RendererType, key: str) -> bool:
    """Whether `renderer_type`'s renderer of `key` builds the pages or tabs not shown once shown."""
    return bool(getattr(_factory(renderer_type, key), "renders_on_demand", False))


def create_renderer(renderer_type: RendererType, key: str, view: Any) -> Renderer[Any, Any] | None:
    """Create the renderer registered under `key` by `renderer_type`'s backend.

    Returns None when the backend doesn't register `key`, meaning it doesn't
    support that widget: the view is then not rendered.
    """
    factory = _factory(renderer_type, key)
    if factory is None:
        return None
    return factory(view)

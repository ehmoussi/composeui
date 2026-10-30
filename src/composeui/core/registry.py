"""Map abstract renderer keys to each backend's concrete renderer classes.

Adding a backend means adding one `RendererType` member here, with its extra, one
``RENDERERS`` mapping in the backend's renderers module, and
``APPLICATION``/``MODEL_APPLICATION`` in its application module.
"""

from __future__ import annotations

import enum
import importlib
from typing import TYPE_CHECKING, Any, NamedTuple

if TYPE_CHECKING:
    from composeui.core.renderer import Renderer

__all__ = ["Backend", "RendererType", "create_renderer"]


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
        "composeui.qtcore.qtrenderer",
        "composeui.qtcore.qtapplication",
        "pyside6",
        ("PySide6", "pyqtgraph", "qtpy"),
    )
    TEXTUAL = Backend(
        "composeui.textualcore.textualrenderer",
        "composeui.textualcore.textualapplication",
        "tui",
        ("textual", "textual_fspicker", "textual_plotext"),
    )
    WEB = Backend(
        "composeui.webcore.webrenderer",
        "composeui.webcore.webapplication",
        "web",
        ("itsdangerous", "markdown_it", "markupsafe", "python_multipart", "starlette", "uvicorn"),
    )


def has_renderer(renderer_type: RendererType, key: str) -> bool:
    """Tell whether `renderer_type`'s backend registers `key`, so it shows such views."""
    return key in importlib.import_module(renderer_type.value.renderers).RENDERERS


def create_renderer(renderer_type: RendererType, key: str, view: Any) -> Renderer[Any, Any] | None:
    """Create the renderer registered under `key` by `renderer_type`'s backend.

    Returns None when the backend doesn't register `key`, meaning it doesn't
    support that widget: the view is then not rendered.
    """
    module = importlib.import_module(renderer_type.value.renderers)
    factory = module.RENDERERS.get(key)
    if factory is None:
        return None
    return factory(view)  # type: ignore[no-any-return]

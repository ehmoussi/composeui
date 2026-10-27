"""Map abstract renderer keys to each backend's concrete renderer classes.

Adding a backend means adding one `RendererType` member here, one ``RENDERERS`` mapping in
the backend's renderers module, and ``APPLICATION``/``MODEL_APPLICATION`` in its
application module.
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


class RendererType(enum.Enum):
    """A renderer backend, identified by its modules."""

    QT = Backend("composeui.qtcore.qtrenderer", "composeui.qtcore.qtapplication")
    TEXTUAL = Backend(
        "composeui.textualcore.textualrenderer", "composeui.textualcore.textualapplication"
    )
    WEB = Backend("composeui.webcore.webrenderer", "composeui.webcore.webapplication")


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

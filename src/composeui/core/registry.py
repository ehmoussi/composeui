"""Map abstract renderer keys to each backend's concrete renderer classes.

Adding a backend means adding one `RendererType` member here and one ``RENDERERS`` mapping
in the backend module.
"""

from __future__ import annotations

import enum
import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from composeui.core.renderer import Renderer


class RendererType(enum.Enum):
    """A renderer backend, identified by the module exposing its ``RENDERERS`` mapping."""

    QT = "composeui.qtcore.qtrenderer"
    TEXTUAL = "composeui.textualcore.textualrenderer"


def create_renderer(renderer_type: RendererType, key: str, view: Any) -> Renderer[Any, Any] | None:
    """Create the renderer registered under `key` by `renderer_type`'s backend.

    Returns None when the backend doesn't register `key`, meaning it doesn't
    support that widget: the view is then simply not rendered, matching how
    partial backends behaved before the registry existed.
    """
    module = importlib.import_module(renderer_type.value)
    factory = module.RENDERERS.get(key)
    if factory is None:
        return None
    return factory(view)  # type: ignore[no-any-return]

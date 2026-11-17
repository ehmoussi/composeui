"""The renderers whose view changed during a request, which its response re-renders."""

from __future__ import annotations

import contextlib
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Generator

    from composeui.webcore.webrenderer import WebRenderer

#: Renderers dirtied during the current request, keyed by fragment id (insertion order
#: kept, duplicates collapsed); None outside a request, where marking is a no-op.
_DIRTY: ContextVar[dict[str, WebRenderer[Any]] | None] = ContextVar(
    "composeui_web_dirty", default=None
)


@contextlib.contextmanager
def collect_dirty() -> Generator[dict[str, WebRenderer[Any]]]:
    """Collect the renderers whose view changed while the block runs."""
    dirty: dict[str, WebRenderer[Any]] = {}
    token = _DIRTY.set(dirty)
    try:
        yield dirty
    finally:
        _DIRTY.reset(token)

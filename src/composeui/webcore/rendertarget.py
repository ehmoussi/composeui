"""A session's view tree, which its renderers register into as they render."""

from __future__ import annotations

import contextlib
import threading
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any, Callable

from composeui.webcore.changes import collect_dirty

if TYPE_CHECKING:
    from collections.abc import Generator

    from composeui.webcore.webrenderer import WebRenderer

#: The session whose view tree is being rendered (see `rendering_into`).
_RENDER_TARGET: ContextVar[RenderTarget | None] = ContextVar(
    "composeui_web_render_target", default=None
)


class RenderTarget:
    """One session's view tree: its renderers by fragment id, and the lock guarding it.

    Renderers register here as they render (see `rendering_into`). So a widget id only
    resolves within the session that rendered it: ids derive from `id()` and are
    guessable, and must not reach another session's views.
    """

    def __init__(self) -> None:
        self.renderers: dict[str, WebRenderer[Any]] = {}
        #: serializes requests against the tree, and the `StatusBar` timer thread with
        #: them (see `WebRenderer.call_on_main_thread`)
        self.lock = threading.RLock()
        #: the renderers changed outside any request (`call_on_main_thread` from another
        #: thread), to send with the next response: no response was there to carry them
        self.pending: dict[str, WebRenderer[Any]] = {}
        #: the session closed: nothing runs in it anymore, a job's outcome included
        self.has_ended = False

    def take_pending(self) -> dict[str, WebRenderer[Any]]:
        """Get the renderers changed outside any request, sending them is then the caller's."""
        pending, self.pending = self.pending, {}
        return pending


def call_in_session(target: RenderTarget | None, callback: Callable[[], None]) -> None:
    """Run `callback` under `target`'s lock, keeping what it changes in its `pending`.

    The `call_on_main_thread` of every web renderer: a request alone touches a session's
    tree otherwise, and its response sends what it changed.
    """
    if target is None:
        callback()  # rendered outside any session: nothing else touches the tree
        return
    with target.lock, collect_dirty() as dirty:
        if target.has_ended:
            return
        callback()
        target.pending.update(dirty)


@contextlib.contextmanager
def rendering_into(target: RenderTarget) -> Generator[None]:
    """Register every renderer rendered while the block runs into `target`."""
    token = _RENDER_TARGET.set(target)
    try:
        yield
    finally:
        _RENDER_TARGET.reset(token)

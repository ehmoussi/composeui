"""One `MainView` per browser session, kept in memory.

A session is identified by a random id stored in Starlette's signed session cookie.
Every tab of a browser shares that cookie, so they share one session (and one app
state), the way two windows on the same document would; different browsers or users
get their own. State lives in this process only: a restart starts every session over.
"""

from __future__ import annotations

import secrets
import threading
import time
from typing import TYPE_CHECKING, Any, Callable

from composeui.core.registry import RendererType
from composeui.core.renderer import NoRenderedObjectError
from composeui.webcore.webrenderer import (
    RenderTarget,
    WebMainRenderer,
    handle_event,
    rendering_into,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from composeui.core.view import MainView


class WebSession(RenderTarget):
    """A session's view tree, rendered once and then driven by its browser's requests."""

    def __init__(self, main_view: MainView) -> None:
        super().__init__()
        self.main_view = main_view
        with self.lock, rendering_into(self):
            main_view.render(RendererType.WEB)

    def page_html(self) -> str:
        with self.lock:
            if not isinstance(self.main_view.renderer, WebMainRenderer):
                raise NoRenderedObjectError
            return self.main_view.renderer.page_html()

    def handle_event(self, widget_id: str, event: str, form: Mapping[str, str]) -> str | None:
        """Apply a browser event to one of this session's widgets; None if it isn't one."""
        with self.lock:
            renderer = self.renderers.get(widget_id)
            if renderer is None:
                return None
            return handle_event(renderer, event, form)

    def fragment(self, widget_id: str) -> str | None:
        """Render one of this session's widgets as it is now; None if it isn't one."""
        with self.lock:
            renderer = self.renderers.get(widget_id)
            return None if renderer is None else renderer.to_html()


class SessionStore:
    """The live sessions by id, each dropped once idle for longer than `ttl` seconds.

    Expiry is checked whenever the store is used, so an idle server keeps its sessions
    until the next request. A dropped session's `StatusBar` timer may still fire; it
    then clears a message on a tree nothing displays any more, which is harmless.
    """

    def __init__(self, build_main_view: Callable[[], MainView], *, ttl: float) -> None:
        self._build_main_view = build_main_view
        self._ttl = ttl
        self._sessions: dict[str, tuple[WebSession, float]] = {}
        self._lock = threading.Lock()

    def get(self, session_id: Any) -> WebSession | None:
        """Return the live session with this id (from a cookie, so of any type), or None."""
        with self._lock:
            self._drop_expired()
            entry = self._sessions.get(session_id) if isinstance(session_id, str) else None
            if entry is None:
                return None
            session = entry[0]
            self._sessions[session_id] = (session, time.monotonic())
            return session

    def create(self) -> tuple[str, WebSession]:
        # built outside the store's lock: building runs app code, which may be slow
        session = WebSession(self._build_main_view())
        session_id = secrets.token_urlsafe(32)
        with self._lock:
            self._sessions[session_id] = (session, time.monotonic())
        return session_id, session

    def _drop_expired(self) -> None:
        now = time.monotonic()
        expired = [
            session_id
            for session_id, (_, last_seen) in self._sessions.items()
            if now - last_seen >= self._ttl
        ]
        for session_id in expired:
            del self._sessions[session_id]

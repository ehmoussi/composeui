"""One `MainView` per browser session, kept in memory.

A session is identified by a random id stored in Starlette's signed session cookie.
Every tab of a browser shares that cookie, so they share one session (and one app
state), the way two windows on the same document would; different browsers or users
get their own. State lives in this process only: a restart starts every session over.
"""

from __future__ import annotations

import json
import re
import secrets
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

import cattrs

from composeui.core.registry import RendererType
from composeui.core.renderer import NoRenderedObjectError
from composeui.core.view import CONVERTER, _apply_state
from composeui.webcore.webrenderer import (
    RenderTarget,
    WebMainRenderer,
    collect_dirty,
    handle_event,
    render_dirty,
    rendering_into,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from composeui.core.view import MainView


#: largest state file accepted from an upload, in bytes
MAX_STATE_SIZE = 5 * 1024 * 1024
#: what applying a structurally wrong state file can raise (from cattrs or a field's
#: own conversion, e.g. `float("abc")`)
_BAD_STATE_ERRORS = (
    ValueError,
    TypeError,
    KeyError,
    AttributeError,
    cattrs.BaseValidationError,
    cattrs.StructureHandlerNotFoundError,
)


def safe_filename(name: str) -> str:
    """`name` reduced to letters, digits, `.`, `_` and `-`, safe in a response header."""
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-.") or "state"


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

    def save_state(self) -> tuple[str, str]:
        """Return a download name and the JSON of the session's state (`save_state`'s)."""
        with self.lock:
            main_view = self.main_view
            if main_view.state_filepath is not None:
                name = main_view.state_filepath.name
            else:
                name = f"{main_view.title.lower()}{main_view.extension}"
            return safe_filename(name), json.dumps(CONVERTER.unstructure(main_view))

    def load_state(self, filename: str, content: bytes) -> str | None:
        """Load an uploaded state file; on failure, return the status bar saying why.

        The file is applied to a scratch instance first: `_apply_state` sets fields one
        by one, so a file failing halfway would otherwise leave the session half loaded.
        """
        with self.lock, collect_dirty() as dirty:
            error = self._check_state(filename, content)
            if error is not None:
                self.main_view.status_bar.show_message(error)
                return render_dirty(dirty)
            _apply_state(self.main_view, json.loads(content))
            self.main_view.state_filepath = Path(Path(filename).name)
            return None

    def _check_state(self, filename: str, content: bytes) -> str | None:
        extension = self.main_view.extension
        if Path(filename).suffix != extension:
            return f"Can't open {filename!r}: expected a {extension} file."
        if len(content) > MAX_STATE_SIZE:
            return f"Can't open {filename!r}: the file is too large."
        try:
            data = json.loads(content)
        except ValueError:
            return f"Can't open {filename!r}: it isn't a valid {extension} file."
        if not isinstance(data, dict):
            return f"Can't open {filename!r}: it isn't a valid {extension} file."
        try:
            _apply_state(type(self.main_view)(), data)
        except _BAD_STATE_ERRORS:
            return f"Can't open {filename!r}: it doesn't match this application."
        return None

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

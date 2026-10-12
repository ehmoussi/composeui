"""One `MainView` per browser session, kept in memory.

A session is identified by a random id stored in Starlette's signed session cookie.
Every tab of a browser shares that cookie, so they share one session (and one app
state), the way two windows on the same document would; different browsers or users
get their own. State lives in this process only: a restart starts every session over.
"""

from __future__ import annotations

import re
import secrets
import tempfile
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from composeui.core.model import InvalidStateError
from composeui.core.registry import RendererType
from composeui.core.renderer import NoRenderedObjectError
from composeui.core.study import has_data, open_study, save_study
from composeui.webcore.page import page_marker
from composeui.webcore.webrenderer import (
    RenderTarget,
    WebActionRenderer,
    WebMainRenderer,
    collect_dirty,
    handle_event,
    page_path,
    render_dirty,
    rendering_into,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from composeui.core.model import Model
    from composeui.core.view import MainView, Router


#: largest state file accepted from an upload, in bytes
MAX_STATE_SIZE = 5 * 1024 * 1024
#: largest a study's archive may unpack to, in bytes (its database compresses well)
MAX_UNPACKED_SIZE = 20 * MAX_STATE_SIZE


def safe_filename(name: str) -> str:
    """`name` reduced to letters, digits, `.`, `_` and `-`, safe in a response header."""
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-.") or "state"


class WebSession(RenderTarget):
    """A session's view tree, rendered once and then driven by its browser's requests."""

    def __init__(self, main_view: MainView, model: Model | None = None) -> None:
        super().__init__()
        self.main_view = main_view
        # held here: the signals giving it to callbacks only keep a weak reference
        self.model = model
        with self.lock, rendering_into(self):
            main_view.render(RendererType.WEB)

    def close(self) -> None:
        """Release the session's model (e.g. its database file); the session is dropped."""
        with self.lock:
            if self.model is not None:
                self.model.close()

    @property
    def closed(self) -> bool:
        """Whether the app asked to close (`MainView.close()`, e.g. the Exit action)."""
        renderer = self.main_view.renderer
        return isinstance(renderer, WebMainRenderer) and renderer.is_closed

    def trigger_action(self, widget_id: str) -> None:
        """Fire the `triggered` of one of this session's actions; ignore any other id."""
        with self.lock:
            renderer = self.renderers.get(widget_id)
            if isinstance(renderer, WebActionRenderer):
                # its fragments are dropped: the caller answers with a download or a reload
                handle_event(renderer, "triggered", {})

    @property
    def _router(self) -> Router | None:
        renderer = self.main_view.renderer
        return renderer.router if isinstance(renderer, WebMainRenderer) else None

    def home_path(self) -> str | None:
        """Get the address of the first page; None for an app without pages."""
        router = self._router
        if router is None or len(router.pages) == 0:
            return None
        return page_path(router.pages[0].route)

    def open_route(self, route: str) -> bool:
        """Show the page on `route`, as its address asks; False if no page has it."""
        with self.lock, collect_dirty():  # the whole page is sent: drop the fragments
            router = self._router
            if router is None or router.page(route) is None:
                return False
            router.navigate(route)
            return True

    def page_html(self) -> str:
        with self.lock:
            if not isinstance(self.main_view.renderer, WebMainRenderer):
                raise NoRenderedObjectError
            return self.main_view.renderer.page_html()

    def handle_event(
        self, widget_id: str, event: str, form: Mapping[str, str]
    ) -> tuple[str, str | None] | None:
        """Apply a browser event to one of this session's widgets; None if it isn't one.

        Returns the fragments the event changed, and the address of the page it
        navigated to, if it did (e.g. a toolbar link, or an app's own `navigate`).
        """
        with self.lock:
            renderer = self.renderers.get(widget_id)
            if renderer is None:
                return None
            router = self._router
            route = None if router is None else router.current_route
            main_view = self.main_view
            language, title = main_view.language, main_view.title
            body = handle_event(renderer, event, form)
            if main_view.title != title and isinstance(main_view.renderer, WebMainRenderer):
                body += main_view.renderer.brand_html(oob=True)
            if (main_view.language, main_view.title) != (language, title):
                body += page_marker(main_view.language, main_view.title, oob=True)
            if router is None or router.current_route == route:
                return body, None
            return body, page_path(router.current_route)

    def save_state(self) -> tuple[str, bytes, str]:
        """Return a download name, the saved study (`save_study`'s) and its media type."""
        with self.lock, tempfile.TemporaryDirectory(prefix="composeui-") as directory:
            main_view = self.main_view
            if main_view.state_filepath is not None:
                name = main_view.state_filepath.name
            else:
                name = f"{main_view.title.lower()}{main_view.extension}"
            state_filepath = main_view.state_filepath
            path = Path(directory, "study")
            save_study(main_view, self.model, path)
            # the browser's file is wherever it saves the download, not this scratch one
            main_view.state_filepath = state_filepath
            media_type = "application/zip" if has_data(self.model) else "application/json"
            return safe_filename(name), path.read_bytes(), media_type

    def load_state(self, filename: str, content: bytes) -> str | None:
        """Load an uploaded state file; on failure, return the status bar saying why."""
        with self.lock, collect_dirty() as dirty:
            error = self._load_state(filename, content)
            if error is not None:
                self.main_view.status_bar.show_message(f"Can't open {filename!r}: {error}.")
                return render_dirty(dirty)
            self.main_view.state_filepath = Path(Path(filename).name)
            return None

    def _load_state(self, filename: str, content: bytes) -> str | None:
        extension = self.main_view.extension
        if Path(filename).suffix != extension:
            return f"expected a {extension} file"
        if len(content) > MAX_STATE_SIZE:
            return "the file is too large"
        with tempfile.TemporaryDirectory(prefix="composeui-") as directory:
            path = Path(directory, "study")
            path.write_bytes(content)
            try:
                open_study(self.main_view, self.model, path, max_size=MAX_UNPACKED_SIZE)
            except InvalidStateError as error:
                return str(error)
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

    def __init__(
        self, build_session: Callable[[], tuple[MainView, Model | None]], *, ttl: float
    ) -> None:
        self._build_session = build_session
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
        session = WebSession(*self._build_session())
        session_id = secrets.token_urlsafe(32)
        with self._lock:
            self._sessions[session_id] = (session, time.monotonic())
        return session_id, session

    def drop(self, session_id: Any) -> None:
        with self._lock:
            entry = self._sessions.pop(session_id, None)
        if entry is not None:
            entry[0].close()

    def _drop_expired(self) -> None:
        now = time.monotonic()
        expired = [
            session_id
            for session_id, (_, last_seen) in self._sessions.items()
            if now - last_seen >= self._ttl
        ]
        for session_id in expired:
            session, _ = self._sessions.pop(session_id)
            session.close()

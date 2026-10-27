"""One `MainView` per browser session, kept in memory.

A session is identified by a random id stored in Starlette's signed session cookie.
Every tab of a browser shares that cookie, so they share one session (and one app
state), the way two windows on the same document would; different browsers or users
get their own. State lives in this process only: a restart starts every session over,
except with ``--reload``, whose server keeps them across its restarts (`SessionStore`).
"""

from __future__ import annotations

import functools
import re
import secrets
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from composeui.core.model import InvalidStateError
from composeui.core.registry import RendererType
from composeui.core.reload import load_reloaded_state, save_reloaded_state
from composeui.core.study import has_data, open_study, save_study
from composeui.webcore.page import jobs_poller, page_marker
from composeui.webcore.webrenderer import (
    RenderTarget,
    WebActionRenderer,
    WebChartRenderer,
    WebFilePathInputRenderer,
    WebMainRenderer,
    WebSourceTableRenderer,
    collect_dirty,
    handle_event,
    page_path,
    render_dirty,
    rendering_into,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from composeui.core.model import Model
    from composeui.core.view import MainView, Router


#: largest state file accepted from an upload, in bytes
MAX_STATE_SIZE = 5 * 1024 * 1024
#: largest a study's archive may unpack to, in bytes (its database compresses well)
MAX_UNPACKED_SIZE = 20 * MAX_STATE_SIZE
#: largest file a `PickFileAction` or a file path field accepts from an upload, in bytes
MAX_FILE_SIZE = 5 * 1024 * 1024


def safe_filename(name: str) -> str:
    """Reduce `name` to letters, digits, `.`, `_` and `-`, safe in a response header."""
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-.") or "state"


class WebSession(RenderTarget):
    """A session's view tree, rendered once and then driven by its browser's requests."""

    def __init__(self, main_view: MainView, model: Model | None = None) -> None:
        super().__init__()
        self.main_view = main_view
        # held here: the signals giving it to callbacks only keep a weak reference
        self.model = model
        #: where the file path fields' uploads are kept, made by the first one
        self._uploads: Path | None = None
        with self.lock, rendering_into(self):
            main_view.render(RendererType.WEB)

    def close(self) -> None:
        """Release the session's model (e.g. its database file) and its uploads; it's dropped."""
        with self.lock:
            if self.model is not None:
                self.model.close()
            if self._uploads is not None:
                shutil.rmtree(self._uploads, ignore_errors=True)
                self._uploads = None

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

    def page_html(self, reload_instance: str | None = None) -> str:
        """Get the whole page; with `reload_instance`, it reloads once its server restarts."""
        with self.lock:
            assert isinstance(self.main_view.renderer, WebMainRenderer)  # rendered when built
            self.take_pending()  # the whole page shows them
            return self.main_view.renderer.page_html(reload_instance)

    def save_to(self, directory: Path) -> None:
        """Save the session's study, its file and language, for `open_saved` to open."""
        with self.lock:
            save_reloaded_state(self.main_view, self.model, directory)

    def open_saved(self, directory: Path) -> None:
        """Open what `save_to` saved, if it still fits the main view (else it's dropped)."""
        with self.lock, collect_dirty():  # the whole page is sent next: drop the fragments
            load_reloaded_state(self.main_view, self.model, directory)

    def handle_event(
        self, widget_id: str, event: str, form: Mapping[str, str]
    ) -> tuple[str, str | None] | None:
        """Apply a browser event to one of this session's widgets; None if it isn't one.

        Returns the fragments the event changed, with those changed outside any request
        since the last response, and the address of the page it navigated to, if it did
        (e.g. a toolbar link, or an app's own `navigate`).
        """
        with self.lock:
            renderer = self.renderers.get(widget_id)
            if renderer is None:
                return None
            return self._respond(functools.partial(renderer.dispatch, event, form))

    def pick_file(
        self, widget_id: str, filename: str, content: bytes
    ) -> tuple[str, str | None] | None:
        """Hand an uploaded file to one of this session's `PickFileAction`s or path fields.

        None if `widget_id` is neither. The file is a copy under its own name: for an
        action, gone once its callbacks have run; for a file path field, whose text keeps
        its path, kept until the session ends or the field's next upload. One of a type
        they don't offer, or too large, is refused in the status bar. Returns what
        `handle_event` does.
        """
        name = safe_filename(Path(filename).name)
        with self.lock:
            renderer = self.renderers.get(widget_id)
            if not isinstance(renderer, (WebActionRenderer, WebFilePathInputRenderer)):
                return None
            types = renderer.file_types
            error = None
            if len(content) > MAX_FILE_SIZE:
                error = "the file is too large"
            elif types and Path(name).suffix.lower() not in types:
                error = f"expected a {' or '.join(types)} file"
            if error is not None:
                message = f"Can't open {filename!r}: {error}."
                return self._respond(
                    functools.partial(self.main_view.status_bar.show_message, message)
                )
            if isinstance(renderer, WebFilePathInputRenderer):
                path = self._upload_directory(widget_id) / name
                path.write_bytes(content)
                return self._respond(functools.partial(renderer.pick_file, path))
            with tempfile.TemporaryDirectory(prefix="composeui-") as directory:
                path = Path(directory, name)
                path.write_bytes(content)
                return self._respond(functools.partial(renderer.pick_file, path))

    def _upload_directory(self, widget_id: str) -> Path:
        """Get an empty directory for a field's upload: the field's last one is removed."""
        if self._uploads is None:
            self._uploads = Path(tempfile.mkdtemp(prefix="composeui-"))
        directory = self._uploads / widget_id
        shutil.rmtree(directory, ignore_errors=True)
        directory.mkdir()
        return directory

    def _respond(self, apply: Callable[[], None]) -> tuple[str, str | None]:
        """Run `apply` against the tree and return what changed, as `handle_event` does."""
        with self.lock:
            router = self._router
            route = None if router is None else router.current_route
            main_view = self.main_view
            language, title = main_view.language, main_view.title
            jobs_running = main_view.jobs.is_running
            with collect_dirty() as dirty:
                apply()
                # after: the event may hand changes over with `call_on_main_thread` too
                body = render_dirty({**self.take_pending(), **dirty})
            if main_view.title != title and isinstance(main_view.renderer, WebMainRenderer):
                body += main_view.renderer.brand_html(oob=True)
            if (main_view.language, main_view.title) != (language, title):
                body += page_marker(main_view.language, main_view.title, oob=True)
            if main_view.jobs.is_running != jobs_running:
                body += jobs_poller(is_running=main_view.jobs.is_running, oob=True)
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
        """Render one of this session's widgets as it is now; None if it isn't one.

        The fragments changed outside any request come along too.
        """
        with self.lock:
            renderer = self.renderers.get(widget_id)
            if renderer is None:
                return None
            pending = self.take_pending()
            pending.pop(widget_id, None)  # swapped in already
            return renderer.to_html() + render_dirty(pending)

    def chart_image(
        self, widget_id: str, image_format: str, query: Mapping[str, str]
    ) -> tuple[str, bytes] | None:
        """Draw the image of one of this session's charts; None if it isn't one.

        Raises `ValueError` for a format or a range it can't draw.
        """
        with self.lock:
            renderer = self.renderers.get(widget_id)
            if not isinstance(renderer, WebChartRenderer):
                return None
            return renderer.image(image_format, query)

    def table_csv(self, widget_id: str) -> tuple[str, Iterator[str]] | None:
        """Get the file name and the CSV, in pieces, of one of this session's large tables.

        None if it isn't one.

        The rows shown at the call (`SourceTableView.csv_chunks`), each piece read under the
        session's lock: the session's other requests go on between two pieces.
        """
        with self.lock:
            renderer = self.renderers.get(widget_id)
            if not isinstance(renderer, WebSourceTableRenderer):
                return None
            filename, chunks = renderer.csv_file()

        def locked() -> Iterator[str]:
            while True:
                with self.lock:
                    chunk = next(chunks, None)
                if chunk is None:
                    return
                yield chunk

        return filename, locked()

    def poll_jobs(self) -> str:
        """Render the jobs' poller as it is now, and what changed outside any request.

        The poller fetches this while the main view's jobs run (see `jobs_poller`).
        """
        with self.lock:
            pending = render_dirty(self.take_pending())
            return jobs_poller(is_running=self.main_view.jobs.is_running) + pending


#: a session id, as `SessionStore.create` makes them: also the name of its saved directory
_SESSION_ID = re.compile(r"[A-Za-z0-9_-]{43}")


class SessionStore:
    """The live sessions by id, each dropped once idle for longer than `ttl` seconds.

    Expiry is checked whenever the store is used, so an idle server keeps its sessions
    until the next request. A dropped session's `StatusBar` timer may still fire; it
    then clears a message on a tree nothing displays any more, which is harmless.

    With `saved`, a ``--reload`` server's directory, `save_all` saves the live sessions
    there as the server stops. The server started next opens one there when its browser
    comes back, under the same id: its cookie, signed with the same key, still names it.
    """

    def __init__(
        self,
        build_session: Callable[[], tuple[MainView, Model | None]],
        *,
        ttl: float,
        max_sessions: int,
        saved: Path | None = None,
    ) -> None:
        self._build_session = build_session
        self._ttl = ttl
        self._max_sessions = max_sessions
        self._saved = saved
        self._sessions: dict[str, tuple[WebSession, float]] = {}
        #: sessions being built, outside the lock: they count against `max_sessions` too
        self._building = 0
        self._lock = threading.Lock()

    def get(self, session_id: Any) -> WebSession | None:
        """Return the live session with this id (from a cookie, so of any type), or None."""
        with self._lock:
            self._drop_expired()
            entry = self._sessions.get(session_id) if isinstance(session_id, str) else None
            if entry is None:
                return self._restore(session_id)
            session = entry[0]
            self._sessions[session_id] = (session, time.monotonic())
            return session

    def create(self) -> tuple[str, WebSession] | None:
        """Build a new session; None while `max_sessions` are live.

        A full store refuses new sessions rather than dropping old ones: requests without
        a cookie, which anyone can send, would otherwise push out the users' own sessions
        and their unsaved work.
        """
        with self._lock:
            self._drop_expired()
            if len(self._sessions) + self._building >= self._max_sessions:
                return None
            self._building += 1
        try:
            # built outside the store's lock: building runs app code, which may be slow
            session = WebSession(*self._build_session())
            session_id = secrets.token_urlsafe(32)
            with self._lock:
                self._sessions[session_id] = (session, time.monotonic())
        finally:
            with self._lock:
                self._building -= 1
        return session_id, session

    def save_all(self) -> None:
        """Save every live session into `saved`, as a ``--reload`` server's process stops."""
        assert self._saved is not None  # only such a server's lifespan calls it
        with self._lock:
            sessions = [
                (session_id, session) for session_id, (session, _) in self._sessions.items()
            ]
        for session_id, session in sessions:
            directory = self._saved / session_id
            directory.mkdir(exist_ok=True)
            session.save_to(directory)

    def _restore(self, session_id: Any) -> WebSession | None:
        """Open the session the previous server saved under `session_id`; None if none.

        Called with the lock held. The session is built under it too, unlike `create`'s,
        so two requests of its browser can't both open it: only a ``--reload`` server,
        for its developer, saves sessions.
        """
        if (
            self._saved is None
            or not isinstance(session_id, str)
            # its directory's name: never a path elsewhere
            or _SESSION_ID.fullmatch(session_id) is None
            or len(self._sessions) + self._building >= self._max_sessions
        ):
            return None
        directory = self._saved / session_id
        if not directory.is_dir():
            return None
        session = WebSession(*self._build_session())
        session.open_saved(directory)
        shutil.rmtree(directory, ignore_errors=True)
        self._sessions[session_id] = (session, time.monotonic())
        return session

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

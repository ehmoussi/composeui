"""The application classes of the web backend."""

from __future__ import annotations

import asyncio
import contextlib
import functools
import importlib.abc
import importlib.util
import logging
import os
import secrets
import sys
import tempfile
import threading
import time
import types
from collections import deque
from contextvars import ContextVar
from http import HTTPStatus
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Generic,
    Literal,
    NamedTuple,
    TypeVar,
    cast,
    overload,
)

import attrs
import itsdangerous
import uvicorn
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.middleware import Middleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from typing_extensions import override

from composeui.core._views.base import made_signals, view_fields
from composeui.core._views.tables import FILTER_PATTERNS_VARIABLE
from composeui.core.application import Application, WebSettings, _add_reference_to_signals
from composeui.core.jobs import starting_study, stop_running_processes
from composeui.core.reactivity import start_reactions
from composeui.core.registry import RendererType
from composeui.core.reload import has_change_events
from composeui.core.study import open_study
from composeui.core.view import View
from composeui.webcore._renderers.navigation import INTERNAL_ROUTE, check_routes
from composeui.webcore.headers import SecurityHeadersMiddleware
from composeui.webcore.limits import BodySizeLimitMiddleware
from composeui.webcore.order import DuplicatePostError
from composeui.webcore.origin import SameOriginMiddleware
from composeui.webcore.routes import (
    chart_image,
    console_text,
    download,
    duplicate_post,
    homepage,
    icon,
    jobs_poll,
    page,
    picture,
    reload_poll,
    state_download,
    state_save,
    state_upload,
    table_csv,
    widget_event,
    widget_file,
    widget_fragment,
)
from composeui.webcore.session import Hibernation, SessionFolder, SessionStore
from composeui.webcore.streaming import StreamPlaces
from composeui.webcore.style import StyleFiles, style_file, theme

if TYPE_CHECKING:
    import datetime
    from collections.abc import AsyncIterator, Sequence

    from starlette.types import ASGIApp, Receive, Scope, Send
    from typing_extensions import TypeVarTuple, Unpack

    from composeui.core.application import _ConnectDecorator, _ConnectModelDecorator
    from composeui.core.model import Model
    from composeui.core.signal import Signal
    from composeui.core.view import MainView
    from composeui.core.webstyle import WebStyle

    Ts = TypeVarTuple("Ts")


MainViewT = TypeVar("MainViewT", bound="MainView")
ModelT = TypeVar("ModelT", bound="Model")
ViewT = TypeVar("ViewT", bound="View")

#: attribute names leading from a main view to one of its views or signals
_AttributePath = tuple[str, ...]

#: environment variable naming the program a reloaded server process runs again
_RELOAD_ENTRY_VARIABLE = "COMPOSEUI_WEB_ENTRY"
#: environment variables of a ``--reload`` server's processes: the directory where they
#: leave their sessions to the next, and the key signing the sessions' cookies, which
#: the next must take too
_SAVED_SESSIONS_VARIABLE = "COMPOSEUI_WEB_SAVED_SESSIONS"
_SIGNING_VARIABLE = "COMPOSEUI_WEB_COOKIE_SIGNING"
#: environment variable telling watchfiles whether to poll the files, rather than wait for
#: the system to report their changes
_FORCE_POLLING_VARIABLE = "WATCHFILES_FORCE_POLLING"
#: set while `create_reloaded_starlette_app` runs the program: the apps it ran, unserved
_RELOADED_APPS: ContextVar[list[WebApplication[Any]] | None] = ContextVar(
    "composeui_web_reloaded_apps", default=None
)


class _Connection(NamedTuple):
    """A `connect` made against the template, replayed on every session's main view."""

    view: _AttributePath
    signals: tuple[_AttributePath, ...]
    callback: Callable[..., None]


def _attribute_paths(main_view: MainView) -> dict[int, _AttributePath]:
    """Map the id of every view and signal under `main_view` to its attribute path."""
    paths: dict[int, _AttributePath] = {id(main_view): ()}
    views: deque[tuple[View, _AttributePath]] = deque([(main_view, ())])
    while len(views) > 0:
        view, path = views.popleft()
        for field in view_fields(type(view)):
            child = getattr(view, field.name)
            if isinstance(child, View):
                paths[id(child)] = (*path, field.name)
                views.append((child, (*path, field.name)))
        # a signal `connect` names is made already, by the read naming it
        for name, signal in made_signals(view):
            paths[id(signal)] = (*path, name)
    return paths


def _resolve(main_view: MainView, path: _AttributePath) -> object:
    return functools.reduce(getattr, path, cast("object", main_view))


def create_starlette_app(  # noqa: PLR0913 (each sets a part of the server)
    sessions: SessionStore,
    *,
    max_upload_size: int,
    secret_key: str | None = None,
    reloading: bool = False,
    stream_places: StreamPlaces | None = None,
    style: WebStyle | None = None,
) -> Starlette:
    """Create the Starlette app serving one main view per browser session.

    `max_upload_size` sets the largest body of the route of file uploads, and
    `stream_places` the downloads written at once (`StreamContent`). The pages load
    `style`, checked here: `ValueError` if a stylesheet is missing or names what the page
    couldn't load. `secret_key`
    signs the session cookie, a new one by default. A ``--reload`` server's process
    (`reloading`) saves the sessions as it stops (`SessionStore.save_all`), and its pages
    reload once another process serves (`reload_poll`).
    """
    style_files = StyleFiles(style)
    app = Starlette(
        routes=[
            Route("/", homepage),
            # the backend's own addresses, under one segment that no page takes
            Mount(
                f"/{INTERNAL_ROUTE}",
                routes=[
                    Route("/reload", reload_poll),
                    Route("/widget/{widget_id}", widget_event, methods=["POST"]),
                    Route("/widget/{widget_id}", widget_fragment, methods=["GET"]),
                    Route("/widget/{widget_id}/image", chart_image, methods=["GET"]),
                    Route("/widget/{widget_id}/picture", picture, methods=["GET"]),
                    Route("/widget/{widget_id}/file", widget_file, methods=["POST"]),
                    Route("/widget/{widget_id}/csv", table_csv, methods=["GET"]),
                    Route("/widget/{widget_id}/text", console_text, methods=["GET"]),
                    Route("/download/{ticket}", download, methods=["GET"]),
                    Route("/state", state_download, methods=["GET"]),
                    Route("/state", state_upload, methods=["POST"]),
                    Route("/state/download", state_save, methods=["POST"]),
                    Route("/icon/{name}", icon),
                    Route("/jobs", jobs_poll),
                    Route("/style/theme.css", theme, methods=["GET"]),
                    Route("/style/files/{name:path}", style_file, methods=["GET"]),
                    Mount(
                        "/static",
                        app=StaticFiles(directory=Path(__file__).parent / "static"),
                        name="static",
                    ),
                ],
            ),
            # last: a page's address takes any first segment the others leave
            Route("/{route}", page),
        ],
        middleware=[
            # outermost: every response, a refusal too, carries them
            Middleware(SecurityHeadersMiddleware),
            # before a route reads the body: Starlette would spool an upload of any size
            Middleware(BodySizeLimitMiddleware, max_upload_size=max_upload_size),
            # a request another origin sent is refused before it reaches a session
            Middleware(SameOriginMiddleware),
            # A per-process signing key is enough: sessions live in this process only,
            # so a cookie from before a restart has no session left to point at anyway;
            # a `--reload` server's processes share one, as their sessions outlive them,
            # and so do the servers of a session folder, which holds it (`folder_key`).
            # `same_site="lax"`: cross-site POSTs carry no session cookie, a layer under
            # `SameOriginMiddleware`, which also refuses other ports and subdomains.
            Middleware(
                _SessionMiddleware,
                secret_key=secret_key or sessions.secret_key or secrets.token_urlsafe(32),
                same_site="lax",
            ),
            # the stylesheet, the scripts and a chart's points shrink several times
            Middleware(_GZipMiddleware, minimum_size=1024),
        ],
        exception_handlers={DuplicatePostError: duplicate_post},
        lifespan=_lifespan(sessions, reloading=reloading),
    )
    app.state.sessions = sessions
    #: the app's theme and stylesheets, which its pages load
    app.state.style_files = style_files
    #: the places of the downloads written at once (`StreamResponse`)
    app.state.stream_places = StreamPlaces() if stream_places is None else stream_places
    #: this process of a `--reload` server, which its pages name: None for another server
    app.state.reload_instance = secrets.token_urlsafe(8) if reloading else None
    if reloading:
        _hide_reload_polls()
    return app


class _SteadySigner(itsdangerous.TimestampSigner):
    """A cookie's signer whose clock never goes back, within its process.

    itsdangerous refuses a cookie signed later than its check, by the clock: once the
    system's clock steps back, e.g. at a time sync, every cookie signed before would be
    refused until the clock caught up. Its page would reload into a new session, its
    unsaved work out of reach. The latest second seen is the time instead.
    """

    def __init__(self, secret_key: str) -> None:
        super().__init__(secret_key)
        self._latest = 0
        self._lock = threading.Lock()

    @override
    def get_timestamp(self) -> int:
        with self._lock:
            self._latest = max(self._latest, int(time.time()))
            return self._latest

    @overload
    @override
    def unsign(
        self,
        signed_value: str | bytes,
        max_age: int | None = None,
        return_timestamp: Literal[False] = False,
    ) -> bytes: ...

    @overload
    @override
    def unsign(
        self,
        signed_value: str | bytes,
        max_age: int | None = None,
        return_timestamp: Literal[True] = True,
    ) -> tuple[bytes, datetime.datetime]: ...

    @override
    def unsign(
        self,
        signed_value: str | bytes,
        max_age: int | None = None,
        return_timestamp: bool = False,
    ) -> tuple[bytes, datetime.datetime] | bytes:
        """Check a cookie as itsdangerous does, but take one signed later than now.

        As one that another process signed before the clock stepped back, e.g. a server
        whose sessions outlive it (`session_folder`): the key still proves it, and the
        session's own idle time still ends it.
        """
        value, signed = super().unsign(signed_value, return_timestamp=True)
        age = self.get_timestamp() - int(signed.timestamp())
        if max_age is not None and age > max_age:
            msg = f"Signature age {age} > {max_age} seconds"
            raise itsdangerous.SignatureExpired(msg, payload=value, date_signed=signed)
        return (value, signed) if return_timestamp else value


class _SessionMiddleware(SessionMiddleware):
    """Starlette's session cookie, signed by `_SteadySigner`."""

    def __init__(self, app: ASGIApp, /, secret_key: str, **options: Any) -> None:
        super().__init__(app, secret_key, **options)
        self.signer = _SteadySigner(secret_key)


class _GZipMiddleware(GZipMiddleware):
    """Compress the answers but the app's downloads, sent as they are.

    The downloads are at `/_composeui/download/{ticket}`.

    A download can be large, or written as it's sent (`StreamContent`): compressing it would
    take the event loop's time, which every session shares, piece after piece.
    """

    @override
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["path"].startswith("/_composeui/download/"):
            await self.app(scope, receive, send)
        else:
            await super().__call__(scope, receive, send)


#: the arguments of uvicorn's access log record, in order: the path has its query
_ACCESS_FIELDS = ("client", "method", "path", "http_version", "status")


def _is_logged(record: logging.LogRecord) -> bool:
    """Tell whether uvicorn logs a request: not a page's ask answered "not restarted".

    Every page asks every second (`reload_poll`), which would flood the access log. The
    answer that reloads the page stays: once per restart, it shows the page followed.
    """
    args = record.args
    if not isinstance(args, tuple) or len(args) != len(_ACCESS_FIELDS):
        return True
    path = str(args[_ACCESS_FIELDS.index("path")])
    status = args[_ACCESS_FIELDS.index("status")]
    return path.split("?", maxsplit=1)[0] != "/_composeui/reload" or status != HTTPStatus.NO_CONTENT


def _hide_reload_polls() -> None:
    """Keep the pages' asks out of uvicorn's access log, once its logging is set up."""
    access = logging.getLogger("uvicorn.access")
    if _is_logged not in access.filters:
        access.addFilter(_is_logged)


LOGGER = logging.getLogger("COMPOSEUI")

#: the longest and the shortest wait between two looks for idle sessions to save, in seconds
_MAX_SWEEP_INTERVAL = 30.0
_MIN_SWEEP_INTERVAL = 0.01


def _lifespan(
    sessions: SessionStore, *, reloading: bool
) -> Callable[[Starlette], contextlib.AbstractAsyncContextManager[None]]:
    """Get the server's lifespan: idle sessions saved to disk while it runs.

    A session goes to disk once idle for `WebSettings.session_idle`. Once the server stops,
    the sessions are closed, their uploads removed, or kept in `WebSettings.session_folder`,
    or a ``--reload`` server's saved for its next process. The programs that jobs still run
    are stopped. A server started again takes its session folder again.
    """

    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        if sessions.keeps_sessions:
            # held since the app was made, or taken again after a stop
            sessions.open_folder()
        stopping = asyncio.Event()
        sweeper = None
        if sessions.hibernation is not None:
            # not 0, even for a `session_idle` of 0: the sweep would never wait
            interval = max(
                min(sessions.hibernation.idle / 2, _MAX_SWEEP_INTERVAL), _MIN_SWEEP_INTERVAL
            )
            sweeper = asyncio.ensure_future(_sweep(sessions, interval, stopping))
        try:
            yield
        finally:
            stopping.set()
            if sweeper is not None:
                # not canceled: the session it's saving would be left half saved
                await sweeper
            if reloading:
                sessions.save_all()
            elif sessions.keeps_sessions:
                sessions.keep_all()
            else:
                sessions.close_all()
            # uvicorn ends on SIGTERM by sending it again: Python's exit then doesn't run
            stop_running_processes()

    return lifespan


async def _sweep(sessions: SessionStore, interval: float, stopping: asyncio.Event) -> None:
    """Save the idle sessions every `interval` seconds, until `stopping` is set."""
    while not stopping.is_set():
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stopping.wait(), interval)
        if not stopping.is_set():
            try:
                # saving reads the views and writes files: off the event loop
                await run_in_threadpool(sessions.hibernate_idle)
            except Exception:
                # e.g. an app's model failing to close: the next sessions are still saved
                LOGGER.exception("Can't save the idle sessions to disk.")


def _has_watchfiles() -> bool:
    """Tell whether watchfiles is installed, for uvicorn's reloader watches with it then."""
    return importlib.util.find_spec("watchfiles") is not None


def _entry_point() -> str:
    """Name the program that started this server, so another process can run it again."""
    main = sys.modules["__main__"]
    spec = getattr(main, "__spec__", None)
    if spec is not None:  # `python -m package.module`
        return f"module:{spec.name}"
    path = getattr(main, "__file__", None)
    if path is not None:  # `python script.py`
        return f"path:{Path(path).resolve()}"
    msg = "--reload re-runs the program serving the app: start it as a script or with -m"
    raise ValueError(msg)


def create_reloaded_starlette_app() -> Starlette:
    """Build the app of the program named by `_RELOAD_ENTRY_VARIABLE`: ``--reload``'s factory.

    uvicorn's reloader serves from a new process, started again after every change. That
    process doesn't run the program that started the server. So this function runs the
    program again, with the command line the process inherited (``-f``, ``--debug``,
    ...). It keeps the app whose `run` the program reaches, instead of serving it. So an
    app built inline, connected or configured by the program's `main()` comes back just
    as it was.
    """
    # first: the programs that the app starts, as soon as it runs, inherit the environment,
    # and may show it to a user. The next process gets the key from the reloader's.
    secret_key = os.environ.pop(_SIGNING_VARIABLE)
    kind, _, name = os.environ[_RELOAD_ENTRY_VARIABLE].partition(":")
    spec = (
        importlib.util.find_spec(name)
        if kind == "module"
        else importlib.util.spec_from_file_location("__main__", name)
    )
    if spec is None or not isinstance(spec.loader, importlib.abc.InspectLoader):
        msg = f"can't find {name} to run it again"
        raise RuntimeError(msg)
    code = spec.loader.get_code(spec.name)
    # none only for a compiled extension, which Python can't start as a program
    assert code is not None
    # as its process's `__main__`, for good, not in a scratch module like `runpy`'s:
    # its classes' string annotations (`from __future__ import annotations`) are
    # resolved later, through `sys.modules[cls.__module__]`, when sessions are served
    program = types.ModuleType("__main__")
    program.__spec__ = spec
    program.__file__ = spec.origin
    program.__loader__ = spec.loader
    program.__package__ = spec.parent
    sys.modules["__main__"] = program
    apps: list[WebApplication[Any]] = []
    token = _RELOADED_APPS.set(apps)
    try:
        exec(code, program.__dict__)  # noqa: S102
    finally:
        _RELOADED_APPS.reset(token)
    if len(apps) == 0:
        msg = f"{name} didn't run a WebApplication"
        raise RuntimeError(msg)
    return apps[0].create_starlette_app(
        saved_sessions=Path(os.environ[_SAVED_SESSIONS_VARIABLE]),
        secret_key=secret_key,
    )


class WebApplication(Application[MainViewT]):
    """The web app: it serves the main view over HTTP, one `MainView` per browser session.

    `main_view` is only a template, for the command line (e.g. ``-f``'s extension check).
    Every session gets its own instance from `build_main_view`. So
    ``connect(view=app.main_view..., ...)`` doesn't wire the template. It records where
    the view and the signals sit in the template. Every new session then connects the
    callback to its own view and signals, with its own `view` and `main_view`. Connect
    before serving: a session already open keeps the connections it was built with.
    The server keeps to `settings`: how long sessions live, and how many it serves. The
    pages take the look of `style`, ComposeUI's without one.
    """

    backend = RendererType.WEB

    @override
    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # these were class variables before `WebSettings`: one set in a subclass would now be
        # ignored without a word, e.g. `filter_patterns = False` that a public app relies on
        moved = sorted(set(vars(cls)) & {field.name for field in attrs.fields(WebSettings)})
        if moved:
            msg = (
                f"{cls.__name__} sets {', '.join(moved)}, which moved to WebSettings: pass "
                f"settings=WebSettings(...) to the app, or web_settings=WebSettings(...) to run"
            )
            raise TypeError(msg)

    def __init__(
        self,
        *,
        build_main_view: Callable[[], MainViewT],
        settings: WebSettings | None = None,
        style: WebStyle | None = None,
    ) -> None:
        #: the server's limits: `filter_patterns` is read here, the others as it starts
        self.settings = WebSettings() if settings is None else settings
        #: the pages' look, checked as the server starts
        self.style = style
        self._build_main_view = build_main_view
        self._connections: list[_Connection] = []
        if not self.settings.filter_patterns:
            # the only switch that the tables read, and a reloaded server process inherits it
            os.environ[FILTER_PATTERNS_VARIABLE] = "off"
        super().__init__(build_main_view=build_main_view)
        self._parser.add_argument(
            "--host", metavar="HOST", help="Host to serve on.", default="127.0.0.1"
        )
        self._parser.add_argument(
            "--port", metavar="PORT", help="Port to serve on.", type=int, default=8000
        )
        self._parser.add_argument(
            "--reload",
            help="Restart the server when a Python file under the current directory changes.",
            action="store_true",
        )

    @override
    def connect(
        self, *, view: ViewT, signals: Sequence[Signal[Unpack[Ts]]]
    ) -> _ConnectDecorator[ViewT, MainViewT, Unpack[Ts]]:
        return cast("_ConnectDecorator[ViewT, MainViewT, Unpack[Ts]]", self._record(view, signals))

    def _record(
        self, view: View, signals: Sequence[Signal[Unpack[Ts]]]
    ) -> Callable[[Callable[..., None]], Callable[..., None]]:
        """Return a decorator recording a connection, replayed on every new session."""
        paths = _attribute_paths(self.main_view)
        for target in (view, *signals):
            if id(target) not in paths:
                msg = f"{target!r} isn't part of the app's main view"
                raise ValueError(msg)
        view_path = paths[id(view)]
        signal_paths = tuple(paths[id(s)] for s in signals)

        def wrapper(callback: Callable[..., None]) -> Callable[..., None]:
            self._connections.append(_Connection(view_path, signal_paths, callback))
            return callback

        return wrapper

    @override
    def _start_reactions(self) -> None:
        """Run none on `main_view`, a template: each session runs its own's."""

    def setup_session(self, main_view: MainViewT) -> None:
        """Wire a new session's main view; override to connect app-level behavior."""

    def create_starlette_app(
        self, *, saved_sessions: Path | None = None, secret_key: str | None = None
    ) -> Starlette:
        """Create the Starlette app, building a fresh main view for each new session.

        A page whose route takes one of the backend's addresses stops it here, before
        serving, rather than failing every request. A ``--reload`` server's process gets
        `saved_sessions`, the directory where its processes leave their sessions to the
        next, and `secret_key`, which they all sign the sessions' cookies with.
        """
        check_routes(self.main_view)
        settings = self.settings
        sessions = SessionStore(
            self._new_session,
            ttl=settings.session_ttl,
            max_sessions=settings.max_sessions,
            # a `--reload` server keeps its sessions in a directory of its own
            saved=saved_sessions
            if saved_sessions is not None or settings.session_folder is None
            else SessionFolder(settings.session_folder, settings.max_saved_sessions),
            hibernation=None
            if settings.session_idle is None
            else Hibernation(settings.session_idle, settings.max_saved_sessions),
        )
        try:
            return create_starlette_app(
                sessions,
                max_upload_size=self.main_view.max_upload_size,
                stream_places=StreamPlaces(
                    self.settings.max_download_streams,
                    self.settings.max_session_download_streams,
                ),
                secret_key=secret_key,
                reloading=saved_sessions is not None,
                style=self.style,
            )
        except BaseException:
            # e.g. a stylesheet missing: the app fixed, the server made again takes it
            if sessions.keeps_sessions:
                sessions.close_folder()
            raise

    @override
    def run(self) -> None:
        """Build and serve the app."""
        super().run()
        assert self._args is not None
        reloaded_apps = _RELOADED_APPS.get()
        if reloaded_apps is not None:  # the program is run again by the reloader's process
            reloaded_apps.append(self)
            return
        # the same for each process of a `--reload` server, which uvicorn configures
        server = {
            "host": self._args.host,
            "port": self._args.port,
            # a download being written would hold the server up until it's sent: past it, it's
            # canceled, and its writer stops at its next write
            "timeout_graceful_shutdown": self.settings.shutdown_timeout,
        }
        if not self._args.reload:
            uvicorn.run(self.create_starlette_app(), **server)
            return
        # uvicorn reloads only an app it can import by name, in a process of its own
        os.environ[_RELOAD_ENTRY_VARIABLE] = _entry_point()
        # uvicorn watches with watchfiles, if installed, which polls anywhere on WSL by
        # default and misses changes so, where the system reports them
        if (
            _FORCE_POLLING_VARIABLE not in os.environ
            and _has_watchfiles()
            and has_change_events(Path.cwd())
        ):
            os.environ[_FORCE_POLLING_VARIABLE] = "false"
        with tempfile.TemporaryDirectory(prefix="composeui-sessions-") as saved_sessions:
            # for the server's processes, which keep the sessions across its restarts
            os.environ[_SAVED_SESSIONS_VARIABLE] = saved_sessions
            os.environ[_SIGNING_VARIABLE] = secrets.token_urlsafe(32)
            uvicorn.run(
                f"{__name__}:{create_reloaded_starlette_app.__name__}",
                factory=True,
                reload=True,
                **server,
            )

    def _new_session(self) -> tuple[MainViewT, Model | None]:
        """Build a new session's main view, wired, and its model."""
        main_view = self._build_main_view()
        model = self._new_session_model()
        try:
            _add_reference_to_signals(main_view, model)
            main_view.is_visible = True
            for connection in self._connections:
                self._replay(connection, main_view)
            # what the session does on its own as it starts isn't the user's change
            with starting_study(main_view.jobs):
                self.setup_session(main_view)
                if model is not None:
                    self._setup_model(main_view, model)
                if self._args is not None and self._args.language is not None:
                    main_view.set_language(self._args.language)
                start_reactions(main_view)
                # after the wiring, like Qt/Textual apps loading `-f` once everything is
                # connected
                if self._args is not None and self._args.f is not None:
                    open_study(main_view, model, self._args.f)  # emits `loaded`
                else:
                    main_view.loaded.emit()  # the study the session starts with is in place
                if self._args is not None:
                    main_view.apply_arguments(self._args)
            # what the user starts from: changes from now on are theirs
            main_view._mark_saved()  # noqa: SLF001
        except BaseException:
            if model is not None:  # no session owns it yet
                model.close()
            raise
        return main_view, model

    def _new_session_model(self) -> Model | None:
        """Build a new session's model: none, unless the app has one."""
        return None

    def _setup_model(self, main_view: MainViewT, model: Model) -> None:
        """Wire a new session's model, which only an app with a model has."""

    def _replay(self, connection: _Connection, main_view: MainViewT) -> None:
        """Connect `connection`'s callback to this session's own view and signals.

        `model` needs no binding: the session's signals inject their own (see
        `_add_reference_to_signals`).
        """
        available = {"view": _resolve(main_view, connection.view), "main_view": main_view}
        requested = self._requested_kwargs(connection.callback, tuple(available))
        bound = functools.partial(
            connection.callback, **{k: v for k, v in available.items() if k in requested}
        )
        for path in connection.signals:
            cast("Signal[Unpack[tuple[object, ...]]]", _resolve(main_view, path)).connect(bound)


class WebModelApplication(WebApplication[MainViewT], Generic[MainViewT, ModelT]):
    """A `WebApplication` whose every session also gets its own model from `build_model`.

    Each session has its own model, as it has its own main view. A browser only ever sees
    the fragments its own requests return. So a model shared between sessions would leave
    every other browser showing stale views, and would need its own locking. Callbacks
    asking for `model` get their session's model, whether a view's own callbacks or those
    connected through `connect`. `setup_model` wires each session's model to its main
    view.
    """

    def __init__(
        self,
        *,
        build_main_view: Callable[[], MainViewT],
        build_model: Callable[[], ModelT],
        setup_model: Callable[[MainViewT, ModelT], None] | None = None,
        settings: WebSettings | None = None,
        style: WebStyle | None = None,
    ) -> None:
        self._build_model = build_model
        self._model_setup = setup_model
        super().__init__(build_main_view=build_main_view, settings=settings, style=style)

    @override
    def connect(
        self, *, view: ViewT, signals: Sequence[Signal[Unpack[Ts]]]
    ) -> _ConnectModelDecorator[ViewT, MainViewT, ModelT, Unpack[Ts]]:
        return cast(
            "_ConnectModelDecorator[ViewT, MainViewT, ModelT, Unpack[Ts]]",
            self._record(view, signals),
        )

    def setup_model(self, main_view: MainViewT, model: ModelT) -> None:
        """Wire a new session's model to its main view: calls the `setup_model` given.

        Runs after `setup_session`, e.g. to refresh views when a `SqliteTable` changes.
        """
        if self._model_setup is not None:
            self._model_setup(main_view, model)

    @override
    def _new_session_model(self) -> ModelT:
        return self._build_model()

    @override
    def _study_model(self) -> ModelT:
        """Get a model for the template main view alone, which ``-f`` is opened into first.

        Not a session's: only so a study that doesn't fit stops the app as it starts,
        rather than failing every session, each opening it into its own model. A study
        with the model's data (an archive) needs a model to be read at all.
        """
        return self._build_model()

    @override
    def _setup_model(self, main_view: MainViewT, model: Model) -> None:
        self.setup_model(main_view, cast("ModelT", model))


#: the backend's applications, for `composeui.core.application.run`
APPLICATION = WebApplication
MODEL_APPLICATION = WebModelApplication

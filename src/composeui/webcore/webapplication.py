"""The application classes of the web backend."""

from __future__ import annotations

import contextlib
import functools
import importlib.abc
import importlib.util
import logging
import os
import secrets
import sys
import tempfile
import types
from collections import deque
from contextvars import ContextVar
from http import HTTPStatus
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, ClassVar, Generic, NamedTuple, TypeVar, cast

import attrs
import uvicorn
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from typing_extensions import override

from composeui.core.application import Application, _add_reference_to_signals
from composeui.core.reload import has_change_events
from composeui.core.signal import Signal
from composeui.core.study import open_study
from composeui.core.view import View
from composeui.webcore.headers import SecurityHeadersMiddleware
from composeui.webcore.limits import BodySizeLimitMiddleware
from composeui.webcore.origin import SameOriginMiddleware
from composeui.webcore.routes import (
    chart_image,
    homepage,
    icon,
    jobs_poll,
    page,
    reload_poll,
    state_download,
    state_save,
    state_upload,
    table_csv,
    widget_event,
    widget_file,
    widget_fragment,
)
from composeui.webcore.session import SessionStore
from composeui.webcore.webrenderer import check_routes

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from typing_extensions import TypeVarTuple, Unpack

    from composeui.core.application import _ConnectDecorator, _ConnectModelDecorator
    from composeui.core.model import Model
    from composeui.core.view import MainView

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
        for field in attrs.fields(cast("type[attrs.AttrsInstance]", type(view))):
            child = getattr(view, field.name)
            if isinstance(child, (View, Signal)):
                paths[id(child)] = (*path, field.name)
            if isinstance(child, View):
                views.append((child, (*path, field.name)))
    return paths


def _resolve(main_view: MainView, path: _AttributePath) -> object:
    return functools.reduce(getattr, path, cast("object", main_view))


def create_starlette_app(
    sessions: SessionStore, *, secret_key: str | None = None, reloading: bool = False
) -> Starlette:
    """Create the Starlette app serving one main view per browser session.

    `secret_key` signs the session cookie, a new one by default. A ``--reload`` server's
    process (`reloading`) saves the sessions as it stops (`SessionStore.save_all`), and
    its pages reload once another process serves (`reload_poll`).
    """
    app = Starlette(
        routes=[
            Route("/", homepage),
            Route("/reload", reload_poll),
            Route("/widget/{widget_id}", widget_event, methods=["POST"]),
            Route("/widget/{widget_id}", widget_fragment, methods=["GET"]),
            Route("/widget/{widget_id}/image", chart_image, methods=["GET"]),
            Route("/widget/{widget_id}/file", widget_file, methods=["POST"]),
            Route("/widget/{widget_id}/csv", table_csv, methods=["GET"]),
            Route("/state", state_download, methods=["GET"]),
            Route("/state", state_upload, methods=["POST"]),
            Route("/state/download", state_save, methods=["POST"]),
            Route("/icon/{name}", icon),
            Route("/jobs", jobs_poll),
            Mount(
                "/static",
                app=StaticFiles(directory=Path(__file__).parent / "static"),
                name="static",
            ),
            # last: a page's address takes any first segment the others leave
            Route("/{route}", page),
        ],
        middleware=[
            # outermost: every response, a refusal too, carries them
            Middleware(SecurityHeadersMiddleware),
            # before a route reads the body: Starlette would spool an upload of any size
            Middleware(BodySizeLimitMiddleware),
            # a request another origin sent is refused before it reaches a session
            Middleware(SameOriginMiddleware),
            # A per-process signing key is enough: sessions live in this process only,
            # so a cookie from before a restart has no session left to point at anyway;
            # a `--reload` server's processes share one, as their sessions outlive them.
            # `same_site="lax"`: cross-site POSTs carry no session cookie, a layer under
            # `SameOriginMiddleware`, which also refuses other ports and subdomains.
            Middleware(
                SessionMiddleware,
                secret_key=secret_key or secrets.token_urlsafe(32),
                same_site="lax",
            ),
            # the stylesheet, the scripts and a chart's points shrink several times
            Middleware(GZipMiddleware, minimum_size=1024),
        ],
        lifespan=_saving(sessions) if reloading else None,
    )
    app.state.sessions = sessions
    #: this process of a `--reload` server, which its pages name: None for another server
    app.state.reload_instance = secrets.token_urlsafe(8) if reloading else None
    if reloading:
        _hide_reload_polls()
    return app


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
    return path.split("?", maxsplit=1)[0] != "/reload" or status != HTTPStatus.NO_CONTENT


def _hide_reload_polls() -> None:
    """Keep the pages' asks out of uvicorn's access log, once its logging is set up."""
    access = logging.getLogger("uvicorn.access")
    if _is_logged not in access.filters:
        access.addFilter(_is_logged)


def _saving(
    sessions: SessionStore,
) -> Callable[[Starlette], contextlib.AbstractAsyncContextManager[None]]:
    """Get a lifespan saving the sessions once the server stops, e.g. for a change."""

    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        yield
        sessions.save_all()

    return lifespan


def _has_watchfiles() -> bool:
    """Tell whether watchfiles is installed, for uvicorn's reloader watches with it then."""
    try:
        return importlib.util.find_spec("watchfiles") is not None
    except ValueError:  # in `sys.modules` without a spec, e.g. blocked as None
        return False


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
    if code is None:
        msg = f"{name} has no code to run"
        raise RuntimeError(msg)
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
        secret_key=os.environ[_SIGNING_VARIABLE],
    )


class WebApplication(Application[MainViewT]):
    """The web app: it serves the main view over HTTP, one `MainView` per browser session.

    `main_view` is only a template, for the command line (e.g. ``-f``'s extension check).
    Every session gets its own instance from `build_main_view`. So
    ``connect(view=app.main_view..., ...)`` doesn't wire the template. It records where
    the view and the signals sit in the template. Every new session then connects the
    callback to its own view and signals, with its own `view` and `main_view`. Connect
    before serving: a session already open keeps the connections it was built with.
    """

    #: seconds a session may stay idle before it is dropped
    session_ttl: ClassVar[float] = 3600.0
    #: most sessions live at once: past it, a new browser gets 503 until one is dropped
    #: (each holds a main view, and maybe a model, in memory)
    max_sessions: ClassVar[int] = 1000

    def __init__(self, *, build_main_view: Callable[[], MainViewT]) -> None:
        self._build_main_view = build_main_view
        self._connections: list[_Connection] = []
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
        sessions = SessionStore(
            self._new_session,
            ttl=self.session_ttl,
            max_sessions=self.max_sessions,
            saved=saved_sessions,
        )
        return create_starlette_app(
            sessions, secret_key=secret_key, reloading=saved_sessions is not None
        )

    def run(self) -> None:
        """Build and serve the app."""
        super().run()
        assert self._args is not None
        reloaded_apps = _RELOADED_APPS.get()
        if reloaded_apps is not None:  # the program is run again by the reloader's process
            reloaded_apps.append(self)
            return
        if not self._args.reload:
            uvicorn.run(self.create_starlette_app(), host=self._args.host, port=self._args.port)
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
                host=self._args.host,
                port=self._args.port,
            )

    def _new_session(self) -> tuple[MainViewT, Model | None]:
        """Build a new session's main view, wired, and its model."""
        main_view = self._build_main_view()
        model = self._new_session_model()
        _add_reference_to_signals(main_view, model)
        main_view.is_visible = True
        for connection in self._connections:
            self._replay(connection, main_view)
        self.setup_session(main_view)
        if model is not None:
            self._setup_model(main_view, model)
        if self._args is not None and self._args.language is not None:
            main_view.set_language(self._args.language)
        # after the wiring, like Qt/Textual apps loading `-f` once everything is connected
        if self._args is not None and self._args.f is not None:
            open_study(main_view, model, self._args.f)
        if self._args is not None:
            main_view.apply_arguments(self._args)
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
    ) -> None:
        self._build_model = build_model
        self._model_setup = setup_model
        super().__init__(build_main_view=build_main_view)

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

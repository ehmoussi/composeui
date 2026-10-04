from __future__ import annotations

import functools
import importlib.abc
import importlib.util
import os
import secrets
import sys
import types
from collections import deque
from contextvars import ContextVar
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, ClassVar, Generic, NamedTuple, TypeVar, cast

import attrs
import uvicorn
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from composeui.core.application import Application, _add_reference_to_signals
from composeui.core.signal import Signal
from composeui.core.view import View
from composeui.webcore.routes import (
    homepage,
    state_download,
    state_upload,
    widget_event,
    widget_fragment,
)
from composeui.webcore.session import SessionStore

if TYPE_CHECKING:
    from collections.abc import Sequence

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


def create_starlette_app(sessions: SessionStore) -> Starlette:
    """Create the Starlette app serving one main view per browser session."""
    app = Starlette(
        routes=[
            Route("/", homepage),
            Route("/widget/{widget_id}", widget_event, methods=["POST"]),
            Route("/widget/{widget_id}", widget_fragment, methods=["GET"]),
            Route("/state", state_download, methods=["GET"]),
            Route("/state", state_upload, methods=["POST"]),
            Mount(
                "/static",
                app=StaticFiles(directory=Path(__file__).parent / "static"),
                name="static",
            ),
        ],
        middleware=[
            # A per-process signing key is enough: sessions live in this process only,
            # so a cookie from before a restart has no session left to point at anyway.
            # `same_site="lax"`: cross-site POSTs carry no session cookie, so another
            # site can't drive a user's session (the CSRF story for now).
            Middleware(SessionMiddleware, secret_key=secrets.token_urlsafe(32), same_site="lax"),
        ],
    )
    app.state.sessions = sessions
    return app


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
    """Build the app of the program named by `_RELOAD_ENTRY_VARIABLE`: `--reload`'s factory.

    uvicorn's reloader serves from a new process, started again after every change,
    which doesn't run the program that started the server. So this runs it again, with
    the command line the process inherited (`-f`, `--debug`, ...), and keeps the app
    whose `run` it reaches instead of serving it: an app built inline, connected or
    configured by the program's `main()` comes back just as it was.
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
    return apps[0].create_starlette_app()


class WebApplication(Application[MainViewT]):
    """Serve the app over HTTP, building one `MainView` per browser session.

    `main_view` is only a template (for the command line, e.g. `-f`'s extension
    check): every session gets its own instance from `build_main_view`. So
    `connect(view=app.main_view..., ...)` doesn't wire the template: it records where the
    view and signals sit in it, and every new session connects the callback to its own
    ones, with its own `view` and `main_view`. Connect before serving: a session already
    open keeps the connections it was built with.
    """

    #: seconds a session may stay idle before it is dropped
    session_ttl: ClassVar[float] = 3600.0

    def __init__(self, *, build_main_view: Callable[[], MainViewT]) -> None:
        self._build_main_view = build_main_view
        self._connections: list[_Connection] = []
        super().__init__(main_view=build_main_view())
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

    def create_starlette_app(self) -> Starlette:
        """Create the Starlette app, building a fresh main view for each new session."""
        return create_starlette_app(SessionStore(self._new_session_view, ttl=self.session_ttl))

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
        uvicorn.run(
            f"{__name__}:{create_reloaded_starlette_app.__name__}",
            factory=True,
            reload=True,
            host=self._args.host,
            port=self._args.port,
        )

    def _new_session_view(self) -> MainViewT:
        main_view = self._build_main_view()
        model = self._new_session_model()
        _add_reference_to_signals(main_view, model)
        main_view.is_visible = True
        for connection in self._connections:
            self._replay(connection, main_view)
        self.setup_session(main_view)
        # after the wiring, like Qt/Textual apps loading `-f` once everything is connected
        if self._args is not None and self._args.f is not None:
            main_view.load_state(self._args.f)
        return main_view

    def _new_session_model(self) -> Model | None:
        """Build a new session's model: none, unless the app has one."""
        return None

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

    Per session rather than shared, like the main views: a browser only ever sees the
    fragments its own requests return, so a model shared between sessions would leave
    every other browser showing stale views (and would need its own locking). Callbacks
    asking for `model`, whether a view's own or connected through `connect`, get their
    session's.
    """

    def __init__(
        self, *, build_main_view: Callable[[], MainViewT], build_model: Callable[[], ModelT]
    ) -> None:
        self._build_model = build_model
        super().__init__(build_main_view=build_main_view)

    def connect(
        self, *, view: ViewT, signals: Sequence[Signal[Unpack[Ts]]]
    ) -> _ConnectModelDecorator[ViewT, MainViewT, ModelT, Unpack[Ts]]:
        return cast(
            "_ConnectModelDecorator[ViewT, MainViewT, ModelT, Unpack[Ts]]",
            self._record(view, signals),
        )

    def _new_session_model(self) -> ModelT:
        return self._build_model()

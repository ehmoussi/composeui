"""The app: it builds the main view, wires its signals and runs it on a backend (`run`)."""

from __future__ import annotations

import argparse
import contextlib
import functools
import importlib
import importlib.util
import inspect
import logging
import logging.handlers
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Generic, Optional, Protocol, TextIO, TypeVar, cast

import attrs
from typing_extensions import TypedDict, TypeVarTuple, Unpack, overload, override

from composeui.core._files import cleanup_abandoned
from composeui.core._views.base import _STREAM_HANDLER as VIEW_STREAM_HANDLER
from composeui.core._views.base import LOGGER as VIEW_LOGGER
from composeui.core._views.base import set_references
from composeui.core._views.tables import take_filter_patterns
from composeui.core.autosave import Autosave
from composeui.core.client import ClientCapabilities, set_client
from composeui.core.jobs import starting_study
from composeui.core.reactivity import TRACE_LOGGER as REACTIVITY_LOGGER
from composeui.core.reactivity import start_reactions
from composeui.core.registry import RendererType, has_renderer
from composeui.core.reload import is_reloaded
from composeui.core.signal import _STREAM_HANDLER as SIGNAL_STREAM_HANDLER
from composeui.core.signal import LOGGER as SIGNAL_LOGGER
from composeui.core.signal import Signal
from composeui.core.study import open_study

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence

    from composeui.core.model import Model
    from composeui.core.signal import (
        _BoundCallback,
        _MainViewCallback,
        _ModelCallback,
        _ViewMainCallback,
        _ViewMainModelCallback,
        _ViewModelCallback,
        _ViewOnlyCallback,
    )
    from composeui.core.view import MainView, View
    from composeui.core.webstyle import WebStyle

__all__ = [
    "Application",
    "ModelApplication",
    "WebSettings",
    "current_backend",
    "get_logger",
    "renders",
    "run",
]


LOGGER = logging.getLogger("COMPOSEUI")
_STREAM_HANDLER = logging.StreamHandler(sys.stdout)
_STREAM_HANDLER.setFormatter(logging.Formatter("%(asctime)s: %(message)s", "%Y-%m-%d %H:%M:%S"))
LOGGER.addHandler(_STREAM_HANDLER)
_REACTIVITY_STREAM_HANDLER = logging.StreamHandler(sys.stdout)
_REACTIVITY_STREAM_HANDLER.setFormatter(_STREAM_HANDLER.formatter)
REACTIVITY_LOGGER.addHandler(_REACTIVITY_STREAM_HANDLER)
#: the size at which a log file starts again, its previous content kept beside it
_LOG_FILE_MAX_BYTES = 5 * 1024 * 1024
_LOG_OUTPUTS = (
    (LOGGER, _STREAM_HANDLER),
    (SIGNAL_LOGGER, SIGNAL_STREAM_HANDLER),
    (REACTIVITY_LOGGER, _REACTIVITY_STREAM_HANDLER),
    (VIEW_LOGGER, VIEW_STREAM_HANDLER),
)

# T = TypeVar("T", bound=MainView)
Ts = TypeVarTuple("Ts")

_ViewT_contra = TypeVar("_ViewT_contra", contravariant=True)
_MainViewT_contra = TypeVar("_MainViewT_contra", contravariant=True)
_ModelT_contra = TypeVar("_ModelT_contra", contravariant=True)
ViewT = TypeVar("ViewT", bound="View")
MainViewT = TypeVar("MainViewT", bound="MainView")
ModelT = TypeVar("ModelT", bound="Model")


_ViewTD = TypeVar("_ViewTD")
_MainViewTD = TypeVar("_MainViewTD")
_ModelTD = TypeVar("_ModelTD")
_TsD = TypeVarTuple("_TsD")


class AvailableBounds(TypedDict, Generic[_ViewT_contra, _MainViewT_contra]):
    """The arguments `Application.connect` can give a callback by name."""

    view: _ViewT_contra
    main_view: _MainViewT_contra


class AvailableModelBounds(TypedDict, Generic[_ViewT_contra, _MainViewT_contra, _ModelT_contra]):
    """The arguments `ModelApplication.connect` can give a callback by name."""

    view: _ViewT_contra
    main_view: _MainViewT_contra
    model: _ModelT_contra


class _ConnectDecorator(Protocol[_ViewTD, _MainViewTD, Unpack[_TsD]]):
    @overload
    def __call__(
        self, callback: Callable[[Unpack[_TsD]], None]
    ) -> Callable[[Unpack[_TsD]], None]: ...
    @overload
    def __call__(
        self, callback: _MainViewCallback[_MainViewTD, Unpack[_TsD]]
    ) -> _MainViewCallback[_MainViewTD, Unpack[_TsD]]: ...
    @overload
    def __call__(
        self, callback: _ViewOnlyCallback[_ViewTD, Unpack[_TsD]]
    ) -> _ViewOnlyCallback[_ViewTD, Unpack[_TsD]]: ...
    @overload
    def __call__(
        self, callback: _ViewMainCallback[_ViewTD, _MainViewTD, Unpack[_TsD]]
    ) -> _ViewMainCallback[_ViewTD, _MainViewTD, Unpack[_TsD]]: ...


class _ConnectModelDecorator(Protocol[_ViewTD, _MainViewTD, _ModelTD, Unpack[_TsD]]):
    @overload
    def __call__(
        self, callback: Callable[[Unpack[_TsD]], None]
    ) -> Callable[[Unpack[_TsD]], None]: ...
    @overload
    def __call__(
        self, callback: _MainViewCallback[_MainViewTD, Unpack[_TsD]]
    ) -> _MainViewCallback[_MainViewTD, Unpack[_TsD]]: ...
    @overload
    def __call__(
        self, callback: _ModelCallback[_ModelTD, Unpack[_TsD]]
    ) -> _ModelCallback[_ModelTD, Unpack[_TsD]]: ...
    @overload
    def __call__(
        self, callback: _BoundCallback[_MainViewTD, _ModelTD, Unpack[_TsD]]
    ) -> _BoundCallback[_MainViewTD, _ModelTD, Unpack[_TsD]]: ...
    @overload
    def __call__(
        self, callback: _ViewOnlyCallback[_ViewTD, Unpack[_TsD]]
    ) -> _ViewOnlyCallback[_ViewTD, Unpack[_TsD]]: ...
    @overload
    def __call__(
        self, callback: _ViewMainCallback[_ViewTD, _MainViewTD, Unpack[_TsD]]
    ) -> _ViewMainCallback[_ViewTD, _MainViewTD, Unpack[_TsD]]: ...
    @overload
    def __call__(
        self, callback: _ViewModelCallback[_ViewTD, _ModelTD, Unpack[_TsD]]
    ) -> _ViewModelCallback[_ViewTD, _ModelTD, Unpack[_TsD]]: ...
    @overload
    def __call__(
        self, callback: _ViewMainModelCallback[_ViewTD, _MainViewTD, _ModelTD, Unpack[_TsD]]
    ) -> _ViewMainModelCallback[_ViewTD, _MainViewTD, _ModelTD, Unpack[_TsD]]: ...


def _add_reference_to_signals(main_view: MainView, model: Model | None) -> None:
    set_references(main_view, main_view, model)
    if model is not None:
        main_view.jobs.set_model(model)
        model._set_main_view(main_view)  # noqa: SLF001 (the app wires its model)
        for signal in model.signals:
            signal.set_main_view(main_view)
            signal.set_model(model)


class _Running:
    """The backend of the app this process runs, from the start of its build."""

    backend: ClassVar[RendererType | None] = None


def get_logger(name: str) -> logging.Logger:
    """Get a logger for app code, with ComposeUI's output and the level `--log` sets."""
    return LOGGER.getChild(name)


class _LogFile(logging.handlers.RotatingFileHandler):
    """The file of the log messages, which another app can write and rotate too."""

    _is_closed = False

    @override
    def emit(self, record: logging.LogRecord) -> None:
        if self._is_closed:  # from a thread already logging as the block ended
            _STREAM_HANDLER.emit(record)
        else:
            super().emit(record)

    @override
    def close(self) -> None:
        self.acquire()  # `handle` holds it while it emits
        try:
            self._is_closed = True
            super().close()
        finally:
            self.release()

    @override
    def doRollover(self) -> None:
        stream = self.stream
        assert stream is not None  # `shouldRollover` opened it
        if self._is_replaced(stream):  # posix only
            stream.close()
            self.stream = self._open()
            return
        try:
            super().doRollover()
        except OSError:  # Windows refuses to rename a file that another app has open
            self.stream = self._open()

    def _is_replaced(self, stream: TextIO) -> bool:
        """Say whether another app rotated the file, which this one would rotate away."""
        try:
            on_disk = Path(self.baseFilename).stat()
            return not os.path.samestat(os.fstat(stream.fileno()), on_disk)
        except FileNotFoundError:  # posix only
            return True


def check_writable(path: Path) -> None:
    """Raise an `OSError` if the file `path` can't be written; leave no new file behind."""
    is_new = not path.exists()
    with path.open("a", encoding="utf-8"):
        pass
    if is_new:
        path.unlink()


@contextlib.contextmanager
def logs_in_file(path: Path, *, names_file: bool = True) -> Iterator[None]:
    """Write ComposeUI's log messages to the file `path` instead of the standard output.

    The first message creates the file. After the block, the standard output shows its path,
    unless `names_file` is false.
    """
    log_file = _LogFile(
        path, maxBytes=_LOG_FILE_MAX_BYTES, backupCount=1, encoding="utf-8", delay=True
    )
    log_file.setFormatter(_STREAM_HANDLER.formatter)
    # each output is added before the other leaves: a job's thread can log at any time
    for logger, stream_handler in _LOG_OUTPUTS:
        logger.addHandler(log_file)
        logger.removeHandler(stream_handler)
    try:
        yield
    finally:
        for logger, stream_handler in _LOG_OUTPUTS:
            logger.addHandler(stream_handler)
            logger.removeHandler(log_file)
        is_written = log_file.stream is not None
        log_file.close()
        if is_written and names_file:
            LOGGER.info("Log messages written to %s", log_file.baseFilename)


def current_backend() -> RendererType | None:
    """Get the backend of the app running, e.g. `RendererType.QT`; None before an app is built.

    It is set before the app builds its main view, so the views can read it as they are
    built. To tell whether the backend shows a kind of view, use `renders` instead.
    """
    return _Running.backend


def renders(view_type: type[View]) -> bool:
    """Tell whether the backend of the app running shows views of `view_type`.

    For example, `MapView` shows on Qt and the web, but not on Textual, where an app can
    show a table of the points instead. False before an app is built.
    """
    backend = current_backend()
    keys = view_type._renderer_keys()  # noqa: SLF001 (the views' own rule)
    return backend is not None and len(keys) > 0 and all(has_renderer(backend, k) for k in keys)


class Application(Generic[MainViewT]):
    """An app showing the main view `build_main_view` builds; each backend has its own.

    The app builds its main view itself, so every backend takes the same arguments: a web
    app builds one per browser session.
    """

    #: the backend that shows the app, given by each backend's app (`current_backend`)
    backend: ClassVar[RendererType | None] = None
    #: whether the backend autosaves a main view with `MainView.autosave` (Qt, Textual)
    can_autosave: ClassVar[bool] = False

    def __init__(self, *, build_main_view: Callable[[], MainViewT]) -> None:
        cleanup_abandoned()  # what a crash left: nothing else would remove it
        take_filter_patterns()  # a mistyped setting stops the app here, not at a first filter
        if self.backend is not None:
            _Running.backend = self.backend
        set_client(self._client())
        self._main_view = build_main_view()
        self._args: argparse.Namespace | None = None
        self._parser = argparse.ArgumentParser()
        self._parser.add_argument("--debug", help="Run the app in debug mode", action="store_true")
        self._parser.add_argument(
            "-f", metavar="FILE", help="Open the app with the FILE study", type=Path
        )
        self._parser.add_argument("--log", help="Display the debug Log.", action="store_true")
        self._parser.add_argument(
            "--log-signals", help="Log all the emitted signals.", action="store_true"
        )
        self._parser.add_argument(
            "--log-reactivity",
            help="Log what schedules reactive methods and when they run.",
            action="store_true",
        )
        self._parser.add_argument(
            "--language", metavar="LANGUAGE", help="Show the app in LANGUAGE, e.g. fr."
        )
        self._add_reference_to_signals()
        # what the app does on its own as it starts isn't the user's change
        with starting_study(self._main_view.jobs):
            self._set_up()
            self._start_reactions()

    def _set_up(self) -> None:
        """Wire the main view once it's built: nothing here, `setup_model` with a model."""

    def _add_reference_to_signals(self) -> None:
        _add_reference_to_signals(self._main_view, None)

    @property
    def main_view(self) -> MainViewT:
        return self._main_view

    def connect(
        self, *, view: ViewT, signals: Sequence[Signal[Unpack[Ts]]]
    ) -> _ConnectDecorator[ViewT, MainViewT, Unpack[Ts]]:
        def wrapper(callback: Callable[..., None]) -> Callable[..., None]:
            available_bounds: AvailableBounds[ViewT, MainViewT] = {
                "view": view,
                "main_view": self._main_view,
            }
            requested_bounds = self._requested_kwargs(callback, tuple(available_bounds))
            bound = functools.partial(
                callback, **{k: v for k, v in available_bounds.items() if k in requested_bounds}
            )
            new_callback = cast("Callable[[Unpack[Ts]], None]", bound)
            for s in signals:
                s.connect(new_callback)
            return callback

        return cast("_ConnectDecorator[ViewT, MainViewT, Unpack[Ts]]", wrapper)

    def render(self, renderer_type: RendererType) -> None:
        self._main_view.is_visible = True
        self._main_view.render(renderer_type)

    def run(self) -> None:
        self._args = self._parse_arguments()
        self._start()

    def _start(self) -> None:
        """Apply the command line and emit `loaded`, what comes before showing the main view."""
        assert self._args is not None
        if self._args.log or self._args.debug:
            LOGGER.setLevel(level=logging.DEBUG)
        else:
            LOGGER.setLevel(level=logging.INFO)
        if self._args.log_signals or self._args.debug:
            SIGNAL_LOGGER.setLevel(level=logging.DEBUG)
        else:
            SIGNAL_LOGGER.setLevel(level=logging.INFO)
        REACTIVITY_LOGGER.setLevel(
            logging.DEBUG if self._args.log_reactivity or self._args.debug else logging.INFO
        )
        if self._args.language is not None:
            self.main_view.set_language(self._args.language)
        # the file asked for wins: the work an unclean end left waits for the next start
        autosave = self._start_autosave(restores=self._args.f is None)
        with starting_study(self.main_view.jobs):
            if self._args.f is not None:
                open_study(self.main_view, self._study_model(), self._args.f)  # emits `loaded`
            else:
                self.main_view.loaded.emit()  # the study the app starts with is in place too
            self.main_view.apply_arguments(self._args)
        # what the user starts from: changes from now on are theirs
        self.main_view._mark_saved()  # noqa: SLF001
        # once the start's mark is taken; the backend asks about the work left once it shows
        # the main view (`Autosave.ask_restore`)
        self.main_view._autosave = autosave  # noqa: SLF001

    def _start_autosave(self, *, restores: bool) -> Autosave | None:
        """Take the main view's folder of autosaves, if it autosaves on this backend.

        Not under ``--reload``, which saves the study itself between two runs of the code.
        """
        assert self._args is not None
        if (
            not self.can_autosave
            or not type(self.main_view).autosave
            or getattr(self._args, "reload", False)
            or is_reloaded()
        ):
            return None
        return Autosave.start(self.main_view, self._study_model(), restores=restores)

    def _start_reactions(self) -> None:
        """Run the main view's reactive methods once it's wired (`setup_model`)."""
        start_reactions(self.main_view)

    def _client(self) -> ClientCapabilities:
        """Get what the app can do for its user (`MainView.client`): on their computer here."""
        return ClientCapabilities.local()

    def _study_model(self) -> Model | None:
        """Get the model opened, saved and started over with the views: none here."""
        return None

    def _parse_arguments(self) -> argparse.Namespace:
        # last: after the backend's own, which a subclass adds once built
        type(self.main_view).add_arguments(self._parser)
        args = self._parser.parse_args()
        if (
            args.f is not None
            and isinstance(args.f, Path)
            and args.f.is_file()
            and args.f.suffix != self.main_view.extension
        ):
            msg = (
                f"Invalid file extension: '{args.f.suffix}'. "
                f"Expected extension: '{self.main_view.extension}'. "
                "Please provide a file with the correct extension."
            )
            raise ValueError(msg)
        return args

    @staticmethod
    def _requested_kwargs(callback: object, names: tuple[str, ...]) -> frozenset[str]:
        try:
            params = inspect.signature(callback).parameters  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return frozenset()
        return frozenset(name for name in names if name in params)


class ModelApplication(Application[MainViewT], Generic[MainViewT, ModelT]):
    """An app with a model beside its main view, given to the callbacks asking for `model`.

    `setup_model` wires them once both are built, e.g. to refresh views when the model
    changes.
    """

    def __init__(
        self,
        *,
        build_main_view: Callable[[], MainViewT],
        build_model: Callable[[], ModelT],
        setup_model: Callable[[MainViewT, ModelT], None] | None = None,
    ) -> None:
        # first: the base class gives it to the signals
        self._model = build_model()
        self._wire_model = setup_model
        super().__init__(build_main_view=build_main_view)

    @override
    def _set_up(self) -> None:
        if self._wire_model is not None:
            self._wire_model(self._main_view, self._model)

    @override
    def _add_reference_to_signals(self) -> None:
        _add_reference_to_signals(self._main_view, self._model)

    @property
    def model(self) -> ModelT:
        return self._model

    @override
    def _study_model(self) -> ModelT:
        return self._model

    @override
    def connect(
        self, *, view: ViewT, signals: Sequence[Signal[Unpack[Ts]]]
    ) -> _ConnectModelDecorator[ViewT, MainViewT, ModelT, Unpack[Ts]]:
        def wrapper(callback: Callable[..., None]) -> Callable[..., None]:
            available_bounds: AvailableModelBounds[ViewT, MainViewT, ModelT] = {
                "view": view,
                "main_view": self._main_view,
                "model": self._model,
            }
            requested_bounds = self._requested_kwargs(callback, tuple(available_bounds))
            bound = functools.partial(
                callback, **{k: v for k, v in available_bounds.items() if k in requested_bounds}
            )
            new_callback = cast("Callable[[Unpack[Ts]], None]", bound)
            for s in signals:
                s.connect(new_callback)
            return callback

        return cast("_ConnectModelDecorator[ViewT, MainViewT, ModelT, Unpack[Ts]]", wrapper)


#: environment variable naming the backend `run` started: a process the app starts again,
#: e.g. the web's ``--reload`` server, gets the command line without ``--backend``
BACKEND_VARIABLE = "COMPOSEUI_BACKEND"


@attrs.frozen(kw_only=True)
class WebSettings:
    """The limits of a web server: how long its sessions live, and how many it serves.

    Pass them to `run`, which gives them to the web backend only, e.g.
    ``run(build_main_view, web_settings=WebSettings(session_ttl=8 * 3600.0))``. A
    `WebApplication` takes them as ``settings``. "Serve the app to other users" in the user
    guide explains when to change them.
    """

    #: Seconds without a request before a session ends. Its browser then gets a new, empty
    #: session, and its user loses what they didn't save. Raise it when users leave the page
    #: open for long periods, such as a working day.
    session_ttl: float = 3600.0
    #: Seconds after a browser's last visit that it keeps its id (`MainView.browser_id`),
    #: in the session cookie, or `session_ttl` if longer, at most 400 days: a browser keeps
    #: no cookie longer. Each visit starts them again. Set it longer than `session_ttl`, so
    #: that a browser keeps its id once its session ends, e.g. a year. Without a
    #: `session_folder`, a restart of the server gives every browser a new id, except with
    #: ``--reload``.
    browser_ttl: float = 14 * 24 * 3600.0
    #: Most sessions in memory at once. Past it, a new browser gets an error (503) until a
    #: session ends, and the open sessions keep working. Each session holds its main view,
    #: and its model if the app has one. Sessions on disk don't count.
    max_sessions: int = 1000
    #: Seconds without a request before a session is saved to disk and its memory freed.
    #: Its next request opens it again and reloads its page. None keeps every session in
    #: memory. Set it when dozens of sessions stay open but idle. A session that holds what
    #: a study doesn't keep stays in memory (see `MainView.can_hibernate`).
    session_idle: Optional[float] = None
    #: Most sessions on disk at once, with `session_idle` or `session_folder`. Past it, idle
    #: sessions stay in memory, and the server's stop saves no more.
    max_saved_sessions: int = 10_000
    #: The folder where the sessions outlive a restart of the server. The server saves
    #: every session there as it stops, and keeps there the key that signs the cookies and
    #: the files uploaded to path fields and table cells. With `session_idle`, the idle
    #: sessions wait there, and survive a crash too. A crash loses the sessions in memory.
    #: A session that holds what a study doesn't keep (see `MainView.can_hibernate`) is lost
    #: at a restart. One server at a time uses a folder, of its own. A ``--reload`` server
    #: keeps its own. None, the default, loses every session at a restart.
    session_folder: Optional[Path] = attrs.field(
        default=None, converter=attrs.converters.optional(Path)
    )
    #: Most large downloads (`StreamContent`) sent at once, for all sessions. Each takes a
    #: thread until it is sent, and the next waits for one to end. Raise it when many users
    #: download large files at the same time.
    max_download_streams: int = 8
    #: Most large downloads sent at once for one session, so that one browser can't take
    #: them all. Its next download waits without taking a place of the server's.
    max_session_download_streams: int = 2
    #: Seconds that a server which stops, or restarts with ``--reload``, waits for the
    #: requests in progress, such as a large download, before it ends them. None waits for
    #: all of them.
    shutdown_timeout: Optional[int] = 5
    #: Whether table filters take regular expressions (``/pattern/``). Set it to False for a
    #: public app: a crafted expression can make every session wait for a long time.
    filter_patterns: bool = True
    #: What the app can do for its users (`MainView.client`). The default,
    #: `ClientCapabilities.served`, suits a server that users reach from their own
    #: computers. Set `ClientCapabilities.local` for a server on the user's own computer,
    #: outside a container: `MainView.open_folder` then opens their file manager, and
    #: `display_path` shows the whole path.
    client: ClientCapabilities = attrs.field(factory=ClientCapabilities.served)


def run(  # noqa: PLR0913 (each is an option of the app)
    build_main_view: Callable[[], MainViewT],
    *,
    build_model: Callable[[], ModelT] | None = None,
    setup_model: Callable[[MainViewT, ModelT], None] | None = None,
    default_backend: RendererType = RendererType.WEB,
    web_settings: WebSettings | None = None,
    web_style: WebStyle | None = None,
) -> None:
    """Run the app on the backend the command line names, e.g. ``--backend qt``.

    Without ``--backend``, on the one `BACKEND_VARIABLE` names, else on `default_backend`.
    The rest of the command line goes to the backend's app (``-f``, ``--language``,
    ``--port``, ``--help``...). Only that backend is imported, so the others' extras
    needn't be installed; without its own, it stops and names the extra. With `build_model`,
    the app has a model, wired to its main view by `setup_model`: once, or per session on the
    web. On the web, the server keeps to `web_settings`, and the pages take the look of
    `web_style`; the other backends ignore them.
    """
    if build_model is None and setup_model is not None:
        msg = "setup_model needs a model: pass build_model too"
        raise ValueError(msg)
    backends = {backend.name.lower(): backend for backend in RendererType}
    parser = argparse.ArgumentParser(add_help=False)
    default = os.environ.get(BACKEND_VARIABLE, "")
    if default not in backends:
        default = default_backend.name.lower()
    parser.add_argument("--backend", choices=backends, default=default)
    args, rest = parser.parse_known_args()
    # the app parses the command line itself when it runs; a process it starts again
    # inherits its environment, and so the backend
    sys.argv = [sys.argv[0], *rest]
    os.environ[BACKEND_VARIABLE] = args.backend
    backend = backends[args.backend].value
    try:
        module = importlib.import_module(backend.applications)
    except ImportError:
        # only the extra not installed: another import error is a bug, shown as it is
        missing = [name for name in backend.packages if importlib.util.find_spec(name) is None]
        if not missing:
            raise
        parser.error(
            f"the {args.backend} backend needs {', '.join(missing)}, from the "
            f'{backend.extra} extra: pip install "composeui[{backend.extra}]"'
        )
    # only the web's applications take settings and a style
    settings: dict[str, object] = {}
    if backends[args.backend] is RendererType.WEB:
        if web_settings is not None:
            settings["settings"] = web_settings
        if web_style is not None:
            settings["style"] = web_style
    app: Application[MainViewT]
    if build_model is None:
        app = module.APPLICATION(build_main_view=build_main_view, **settings)
    else:
        app = module.MODEL_APPLICATION(
            build_main_view=build_main_view,
            build_model=build_model,
            setup_model=setup_model,
            **settings,
        )
    app.run()

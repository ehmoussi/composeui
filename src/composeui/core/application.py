from __future__ import annotations

import argparse
import functools
import importlib
import inspect
import logging
import sys
import weakref
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING, Generic, Protocol, TypeVar, cast

import attrs
from typing_extensions import TypedDict, TypeVarTuple, Unpack, overload, override

from composeui.core.registry import RendererType
from composeui.core.signal import LOGGER as SIGNAL_LOGGER
from composeui.core.signal import Signal
from composeui.core.study import open_study

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from composeui.core.model import Model
    from composeui.core.view import MainView, View


LOGGER = logging.getLogger("COMPOSEUI")
_STREAM_HANDLER = logging.StreamHandler(sys.stdout)
_STREAM_HANDLER.setFormatter(logging.Formatter("%(asctime)s: %(message)s", "%Y-%m-%d %H:%M:%S"))
LOGGER.addHandler(_STREAM_HANDLER)

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
    view: _ViewT_contra
    main_view: _MainViewT_contra


class AvailableModelBounds(TypedDict, Generic[_ViewT_contra, _MainViewT_contra, _ModelT_contra]):
    view: _ViewT_contra
    main_view: _MainViewT_contra
    model: _ModelT_contra


class _ViewOnlyCallback(Protocol[_ViewT_contra, Unpack[Ts]]):
    def __call__(self, *args: Unpack[Ts], view: _ViewT_contra) -> None: ...


class _ViewMainCallback(Protocol[_ViewT_contra, _MainViewT_contra, Unpack[Ts]]):
    def __call__(
        self, *args: Unpack[Ts], view: _ViewT_contra, main_view: _MainViewT_contra
    ) -> None: ...


class _ViewModelCallback(Protocol[_ViewT_contra, _ModelT_contra, Unpack[Ts]]):
    def __call__(self, *args: Unpack[Ts], view: _ViewT_contra, model: _ModelT_contra) -> None: ...


class _ViewMainModelCallback(
    Protocol[_ViewT_contra, _MainViewT_contra, _ModelT_contra, Unpack[Ts]]
):
    def __call__(
        self,
        *args: Unpack[Ts],
        view: _ViewT_contra,
        main_view: _MainViewT_contra,
        model: _ModelT_contra,
    ) -> None: ...


class _ConnectDecorator(Protocol[_ViewTD, _MainViewTD, Unpack[_TsD]]):
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
    views: deque[View] = deque([main_view])
    main_view_reference = weakref.ref(main_view)
    while len(views) > 0:
        current_view = views.popleft()
        current_view._main_view = main_view_reference  # noqa: SLF001
        # its children, not only its view fields: e.g. a language menu's actions
        views.extend(current_view.children_views)
        for field_row_attr in attrs.fields(cast("type[attrs.AttrsInstance]", type(current_view))):
            child = getattr(current_view, field_row_attr.name)
            if isinstance(child, Signal):
                child.set_main_view(main_view)
                if model is not None:
                    child.set_model(model)
    if model is not None:
        main_view.jobs.set_model(model)
        for signal in model.signals:
            signal.set_main_view(main_view)
            signal.set_model(model)


class Application(Generic[MainViewT]):
    """An app showing the main view `build_main_view` builds; each backend has its own.

    The app builds its main view itself, so every backend takes the same arguments: a web
    app builds one per browser session.
    """

    def __init__(self, *, build_main_view: Callable[[], MainViewT]) -> None:
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
            "--language", metavar="LANGUAGE", help="Show the app in LANGUAGE, e.g. fr."
        )
        self._add_reference_to_signals()

    def _add_reference_to_signals(self) -> None:
        _add_reference_to_signals(self._main_view, None)

    @property
    def main_view(self) -> MainViewT:
        return self._main_view

    def connect(
        self, *, view: ViewT, signals: Sequence[Signal[Unpack[Ts]]]
    ) -> _ConnectDecorator[ViewT, MainViewT, Unpack[Ts]]:
        def wrapper(
            callback: _ViewOnlyCallback[ViewT, Unpack[Ts]]
            | _ViewMainCallback[ViewT, MainViewT, Unpack[Ts]],
        ) -> _ViewOnlyCallback[ViewT, Unpack[Ts]] | _ViewMainCallback[ViewT, MainViewT, Unpack[Ts]]:
            available_bounds: AvailableBounds[ViewT, MainViewT] = {
                "view": view,
                "main_view": self._main_view,
            }
            requested_bounds = self._requested_kwargs(callback, tuple(available_bounds))
            raw = cast("Callable[..., None]", callback)
            bound = functools.partial(
                raw, **{k: v for k, v in available_bounds.items() if k in requested_bounds}
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
        if self._args.log or self._args.debug:
            LOGGER.setLevel(level=logging.DEBUG)
        else:
            LOGGER.setLevel(level=logging.INFO)
        if self._args.log_signals or self._args.debug:
            SIGNAL_LOGGER.setLevel(level=logging.DEBUG)
        else:
            SIGNAL_LOGGER.setLevel(level=logging.INFO)
        if self._args.language is not None:
            self.main_view.set_language(self._args.language)
        if self._args.f is not None:
            open_study(self.main_view, self._study_model(), self._args.f)

    def _study_model(self) -> Model | None:
        """Get the model opened, saved and started over with the views: none here."""
        return None

    def _parse_arguments(self) -> argparse.Namespace:
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
        super().__init__(build_main_view=build_main_view)
        if setup_model is not None:
            setup_model(self._main_view, self._model)

    @override
    def _add_reference_to_signals(self) -> None:
        _add_reference_to_signals(self._main_view, self._model)

    @property
    def model(self) -> ModelT:
        return self._model

    @override
    def _study_model(self) -> ModelT:
        return self._model

    def connect(
        self, *, view: ViewT, signals: Sequence[Signal[Unpack[Ts]]]
    ) -> _ConnectModelDecorator[ViewT, MainViewT, ModelT, Unpack[Ts]]:
        def wrapper(
            callback: _ViewOnlyCallback[ViewT, Unpack[Ts]]
            | _ViewMainCallback[ViewT, MainViewT, Unpack[Ts]],
        ) -> (
            _ViewOnlyCallback[ViewT, Unpack[Ts]]
            | _ViewMainCallback[ViewT, MainViewT, Unpack[Ts]]
            | _ViewMainCallback[ViewT, ModelT, Unpack[Ts]]
            | _ViewMainCallback[ViewT, MainViewT, ModelT, Unpack[Ts]]
        ):
            available_bounds: AvailableModelBounds[ViewT, MainViewT, ModelT] = {
                "view": view,
                "main_view": self._main_view,
                "model": self._model,
            }
            requested_bounds = self._requested_kwargs(callback, tuple(available_bounds))
            raw = cast("Callable[..., None]", callback)
            bound = functools.partial(
                raw, **{k: v for k, v in available_bounds.items() if k in requested_bounds}
            )
            new_callback = cast("Callable[[Unpack[Ts]], None]", bound)
            for s in signals:
                s.connect(new_callback)
            return callback

        return cast("_ConnectModelDecorator[ViewT, MainViewT, ModelT, Unpack[Ts]]", wrapper)


def run(
    build_main_view: Callable[[], MainViewT],
    *,
    build_model: Callable[[], ModelT] | None = None,
    setup_model: Callable[[MainViewT, ModelT], None] | None = None,
    default_backend: RendererType = RendererType.WEB,
) -> None:
    """Run the app on the backend the command line names, e.g. ``--backend qt``.

    Without ``--backend``, on `default_backend`. The rest of the command line goes to the
    backend's app (``-f``, ``--language``, ``--port``, ``--help``...). Only that backend is
    imported, so the others' extras needn't be installed. With `build_model`, the app has
    a model, wired to its main view by `setup_model`: once, or per session on the web.
    """
    if build_model is None and setup_model is not None:
        msg = "setup_model needs a model: pass build_model too"
        raise ValueError(msg)
    backends = {backend.name.lower(): backend for backend in RendererType}
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--backend", choices=backends, default=default_backend.name.lower())
    args, rest = parser.parse_known_args()
    # the app parses the command line itself when it runs
    sys.argv = [sys.argv[0], *rest]
    module = importlib.import_module(backends[args.backend].value.applications)
    app: Application[MainViewT]
    if build_model is None:
        app = module.APPLICATION(build_main_view=build_main_view)
    else:
        app = module.MODEL_APPLICATION(
            build_main_view=build_main_view, build_model=build_model, setup_model=setup_model
        )
    app.run()

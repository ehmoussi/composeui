from __future__ import annotations

import functools
import inspect
import logging
import sys
import weakref
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Generic, TypeVar, Union, cast, overload

from typing_extensions import Protocol, TypeAliasType, TypeVarTuple, Unpack

if TYPE_CHECKING:
    from collections.abc import Sequence
    from types import CodeType
    from weakref import ReferenceType

    from qtpy.QtCore import SignalInstance

    from composeui.core.model import Model
    from composeui.core.view import MainView


_LOGGER = logging.getLogger("COMPOSEUI_SIGNAL")
_STREAM_HANDLER = logging.StreamHandler(sys.stdout)
_STREAM_HANDLER.setFormatter(logging.Formatter("%(asctime)s: %(message)s", "%Y-%m-%d %H:%M:%S"))
_LOGGER.addHandler(_STREAM_HANDLER)
_LOGGER.setLevel(logging.DEBUG)

Ts = TypeVarTuple("Ts")

_MainViewT_contra = TypeVar("_MainViewT_contra", contravariant=True)
_ModelT_contra = TypeVar("_ModelT_contra", contravariant=True)


class _MainViewCallback(Protocol[_MainViewT_contra, Unpack[Ts]]):
    __code__: CodeType

    def __call__(self, *args: Unpack[Ts], main_view: _MainViewT_contra) -> None: ...


class _ModelCallback(Protocol[_ModelT_contra, Unpack[Ts]]):
    __code__: CodeType

    def __call__(self, *args: Unpack[Ts], model: _ModelT_contra) -> None: ...


class _BoundCallback(Protocol[_MainViewT_contra, _ModelT_contra, Unpack[Ts]]):
    __code__: CodeType

    def __call__(
        self, *args: Unpack[Ts], main_view: _MainViewT_contra, model: _ModelT_contra
    ) -> None: ...


CallbackT = TypeAliasType(
    "CallbackT",
    (
        Union[
            Callable[[Unpack[Ts]], None],
            _MainViewCallback["MainView", Unpack[Ts]],
            _ModelCallback["Model", Unpack[Ts]],
            _BoundCallback["MainView", "Model", Unpack[Ts]],
        ]
    ),
    type_params=(Ts,),
)


class Signal(Generic[Unpack[Ts]]):
    def __init__(self) -> None:
        self._name = ""
        self._qt_signal = _QtSignal()
        self._callbacks: list[Callable[[Unpack[Ts]], None]] = [self._log_signal]
        self._logger = _LOGGER
        self._main_view: ReferenceType[MainView] | None = None
        self._model: ReferenceType[Model] | None = None

    def set_name(self, name: str) -> None:
        self._name = name

    def set_main_view(self, main_view: MainView) -> None:
        self._main_view = weakref.ref(main_view)
        for callback in self._callbacks:
            if isinstance(callback, InjectedCallback):
                callback.set_main_view(self._main_view)

    def set_model(self, model: Model) -> None:
        self._model = weakref.ref(model)
        for callback in self._callbacks:
            if isinstance(callback, InjectedCallback):
                callback.set_model(self._model)

    def add_qt_signal(self, signal: SignalInstance) -> None:
        """Add the qt signal."""
        self._qt_signal.add_signal(signal, self._callbacks)

    @overload
    def connect(self, callback: Callable[[Unpack[Ts]], None]) -> None: ...
    @overload
    def connect(self, callback: _MainViewCallback[MainView, Unpack[Ts]]) -> None: ...
    @overload
    def connect(self, callback: _ModelCallback[Model, Unpack[Ts]]) -> None: ...
    @overload
    def connect(self, callback: _BoundCallback[MainView, Model, Unpack[Ts]]) -> None: ...
    def connect(self, callback: CallbackT[Unpack[Ts]]) -> None:
        injected_callback = self._inject_callback(callback)
        self._callbacks.append(injected_callback)
        self._qt_signal.connect(injected_callback)

    def disconnect(self) -> None:
        self._qt_signal.disconnect(self._callbacks)
        self._callbacks = [self._log_signal]
        self._qt_signal.connect(self._log_signal)

    def emit(self, *args: Unpack[Ts]) -> None:
        for callback in self._callbacks:
            callback(*args)

    def _log_signal(self, *args: Unpack[Ts]) -> None:
        log_msgs = ["EMIT SIGNAL %s"]
        log_args = [self._name]
        nb_callbacks = 0
        for callback in self._callbacks:
            if callback != self._log_signal:
                callback_name = self.get_function_name(callback)
                callback_file = self.get_function_file(callback)
                if len(args) > 0:
                    log_msgs.append("  -> CALL %s(%s)\n          %s")
                else:
                    log_msgs.append("  -> CALL %s()\n          %s")
                log_args.append(callback_name)
                log_args.extend(",".join(str(arg) for arg in args))
                log_args.append(callback_file)
                nb_callbacks += 1
        if nb_callbacks > 0:
            self._logger.debug("\n".join(log_msgs), *log_args)

    def _inject_callback(
        self, callback: CallbackT[Unpack[Ts]]
    ) -> Callable[[Unpack[Ts]], None] | InjectedCallback[Unpack[Ts]]:
        requested_bounds = self._requested_bounds(callback)
        if len(requested_bounds) > 0:
            return InjectedCallback(
                callback=callback,
                requested_bounds=requested_bounds,
                main_view=self._main_view,
                model=self._model,
            )
        return cast("Callable[[Unpack[Ts]], None]", callback)

    @staticmethod
    def _requested_bounds(callback: CallbackT[Unpack[Ts]]) -> frozenset[str]:
        names = ("main_view", "model")
        try:
            params = inspect.signature(callback).parameters
        except (TypeError, ValueError):
            return frozenset()
        return frozenset(name for name in names if name in params)

    @staticmethod
    def get_function_name(callback: CallbackT[Any]) -> str:
        if isinstance(callback, InjectedCallback):
            return Signal.get_function_name(callback.get_callback())  # type: ignore[arg-type]
        if isinstance(callback, functools.partial):
            inner = Signal.get_function_name(callback.func)
            args = list(map(repr, callback.args))
            kwargs = [f"{n}={type(arg).__name__}" for n, arg in callback.keywords.items()]
            return f"{inner}({', '.join(args + kwargs)})"
        name = getattr(callback, "__qualname__", None) or getattr(callback, "__name__", None)
        return name or type(callback).__name__

    @staticmethod
    def get_function_file(callback: CallbackT[Any]) -> str:
        if isinstance(callback, InjectedCallback):
            return Signal.get_function_file(callback.get_callback())  # type: ignore[arg-type]
        if isinstance(callback, functools.partial):
            return Signal.get_function_file(callback.func)
        return f'File "{callback.__code__.co_filename}", line {callback.__code__.co_firstlineno}'


if TYPE_CHECKING:
    SignalNoArgs = Signal[()]
else:
    SignalNoArgs = Signal


class _QtSignal:
    def __init__(self) -> None:
        self._qt_signals: list[SignalInstance] = []

    def add_signal(self, signal: SignalInstance, callbacks: Sequence[Callable[..., None]]) -> None:
        """Add the qt signal."""
        self._qt_signals.append(signal)
        for callback in callbacks:
            signal.connect(callback)

    def connect(self, callback: Callable[..., None]) -> None:
        for qt_signal in self._qt_signals:
            qt_signal.connect(callback)

    def disconnect(self, callbacks: Sequence[Callable[..., None]]) -> None:
        for qt_signal in self._qt_signals:
            for callback in callbacks:
                qt_signal.disconnect(callback)


class InjectedCallback(Generic[Unpack[Ts]]):
    def __init__(
        self,
        *,
        callback: CallbackT[Unpack[Ts]],
        requested_bounds: frozenset[str],
        main_view: ReferenceType[MainView] | None,
        model: ReferenceType[Model] | None,
    ) -> None:
        self._callback = weakref.WeakMethod(callback)
        self._requested_bounds = requested_bounds
        self._main_view = main_view
        self._model = model

    def set_main_view(self, main_view: ReferenceType[MainView]) -> None:
        self._main_view = main_view

    def set_model(self, model: ReferenceType[Model]) -> None:
        self._model = model

    def get_callback(self) -> CallbackT[Unpack[Ts]]:
        callback = self._callback()
        if callback is None:
            msg = "callback has been garbage collected"
            raise ValueError(msg)
        return callback

    def __call__(self, *args: Unpack[Ts]) -> None:
        callback = self._callback()
        if callback is None:
            msg = "callback has been garbage collected"
            raise ValueError(msg)
        kwargs: dict[str, MainView | Model] = {}
        if "main_view" in self._requested_bounds:
            main_view = None if self._main_view is None else self._main_view()
            if main_view is None:
                msg = "The main view is missing."
                raise ValueError(msg)
            kwargs["main_view"] = main_view
        if "model" in self._requested_bounds:
            model = None if self._model is None else self._model()
            if model is None:
                msg = "The model is missing."
                raise ValueError(msg)
            kwargs["model"] = model
        return callback(*args, **kwargs)  # type: ignore[arg-type]

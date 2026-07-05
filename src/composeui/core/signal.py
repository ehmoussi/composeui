from __future__ import annotations

import functools
import logging
import sys
import weakref
from typing import TYPE_CHECKING, Generic, TypeVar

from typing_extensions import Protocol, TypeVarTuple, Unpack

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
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
    def __call__(self, *args: Unpack[Ts], main_view: _MainViewT_contra) -> None: ...


class _ModelCallback(Protocol[_ModelT_contra, Unpack[Ts]]):
    def __call__(self, *args: Unpack[Ts], model: _ModelT_contra) -> None: ...


class _BoundCallback(Protocol[_MainViewT_contra, _ModelT_contra, Unpack[Ts]]):
    def __call__(
        self, *args: Unpack[Ts], main_view: _MainViewT_contra, model: _ModelT_contra
    ) -> None: ...


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
            if isinstance(callback, (MainViewBoundCallback, BoundCallback)):
                callback.set_main_view(self._main_view)

    def set_model(self, model: Model) -> None:
        self._model = weakref.ref(model)
        for callback in self._callbacks:
            if isinstance(callback, (ModelBoundCallback, BoundCallback)):
                callback.set_model(self._model)

    def add_qt_signal(self, signal: SignalInstance) -> None:
        """Add the qt signal."""
        self._qt_signal.add_signal(signal, self._callbacks)

    def connect(self, callback: Callable[[Unpack[Ts]], None]) -> None:
        self._callbacks.append(callback)
        self._qt_signal.connect(callback)

    def connect2(self, callback: _MainViewCallback[MainView, Unpack[Ts]]) -> None:
        bound_callback = MainViewBoundCallback(callback=callback, main_view=self._main_view)
        self.connect(bound_callback)

    def connect3(self, callback: _ModelCallback[Model, Unpack[Ts]]) -> None:
        bound_callback = ModelBoundCallback(callback=callback, model=self._model)
        self.connect(bound_callback)

    def connect4(self, callback: _BoundCallback[MainView, Model, Unpack[Ts]]) -> None:
        bound_callback = BoundCallback(
            callback=callback, main_view=self._main_view, model=self._model
        )
        self.connect(bound_callback)

    def disconnect(self) -> None:
        self._qt_signal.disconnect(self._callbacks)
        self._callbacks.clear()

    def emit(self, *args: Unpack[Ts]) -> None:
        for callback in self._callbacks:
            callback(*args)

    def _log_signal(self, *args: Unpack[Ts]) -> None:
        log_msgs = ["EMIT SIGNAL %s"]
        log_args = [self._name]
        nb_callbacks = 0
        for callback in self._callbacks:
            if callback != self._log_signal:
                callback_name = _get_function_name(callback)
                callback_file = _get_function_file(callback)
                if len(args) > 0:
                    log_msgs.append("  -> CALL %s(%s)\n          %s")
                else:
                    log_msgs.append("  -> CALL %s()\n          %s")
                log_args.append(callback_name)
                log_args.extend(str(arg) for arg in args)
                log_args.append(callback_file)
                nb_callbacks += 1
        if nb_callbacks > 0:
            self._logger.debug("\n".join(log_msgs), *log_args)


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


def _get_function_name(callback: Callable[..., None]) -> str:
    if isinstance(callback, MainViewBoundCallback):
        return _get_function_name(callback._callback)  # noqa: SLF001
    if isinstance(callback, functools.partial):
        inner = _get_function_name(callback.func)
        args = list(map(repr, callback.args))
        kwargs = [f"{n}={type(arg).__name__}" for n, arg in callback.keywords.items()]
        return f"{inner}({', '.join(args + kwargs)})"
    name = getattr(callback, "__qualname__", None) or getattr(callback, "__name__", None)
    return name or type(callback).__name__


def _get_function_file(callback: Callable[..., None]) -> str:
    if isinstance(callback, MainViewBoundCallback):
        return _get_function_file(callback._callback)  # noqa: SLF001
    if isinstance(callback, functools.partial):
        return _get_function_file(callback.func)
    return f'File "{callback.__code__.co_filename}", line {callback.__code__.co_firstlineno}'


class MainViewBoundCallback(Generic[_MainViewT_contra, Unpack[Ts]]):
    def __init__(
        self,
        callback: _MainViewCallback[_MainViewT_contra, Unpack[Ts]],
        main_view: ReferenceType[_MainViewT_contra] | None,
    ) -> None:
        self._callback = callback
        self._main_view = main_view

    def set_main_view(self, main_view: ReferenceType[_MainViewT_contra]) -> None:
        self._main_view = main_view

    def __call__(self, *args: Unpack[Ts]) -> None:
        main_view = None if self._main_view is None else self._main_view()
        if main_view is None:
            msg = "The main view is missing."
            raise ValueError(msg)
        return self._callback(*args, main_view=main_view)


class ModelBoundCallback(Generic[_ModelT_contra, Unpack[Ts]]):
    def __init__(
        self,
        callback: _ModelCallback[_ModelT_contra, Unpack[Ts]],
        model: ReferenceType[_ModelT_contra] | None,
    ) -> None:
        self._callback = callback
        self._model = model

    def set_model(self, model: ReferenceType[_ModelT_contra]) -> None:
        self._model = model

    def __call__(self, *args: Unpack[Ts]) -> None:
        model = None if self._model is None else self._model()
        if model is None:
            msg = "The model is missing."
            raise ValueError(msg)
        return self._callback(*args, model=model)


class BoundCallback(Generic[_MainViewT_contra, _ModelT_contra, Unpack[Ts]]):
    def __init__(
        self,
        *,
        callback: _BoundCallback[_MainViewT_contra, _ModelT_contra, Unpack[Ts]],
        main_view: ReferenceType[_MainViewT_contra] | None,
        model: ReferenceType[_ModelT_contra] | None,
    ) -> None:
        self._callback = callback
        self._main_view = main_view
        self._model = model

    def set_main_view(self, main_view: ReferenceType[_MainViewT_contra]) -> None:
        self._main_view = main_view

    def set_model(self, model: ReferenceType[_ModelT_contra]) -> None:
        self._model = model

    def __call__(self, *args: Unpack[Ts]) -> None:
        main_view = None if self._main_view is None else self._main_view()
        if main_view is None:
            msg = "The main view is missing."
            raise ValueError(msg)
        model = None if self._model is None else self._model()
        if model is None:
            msg = "The model is missing."
            raise ValueError(msg)
        return self._callback(*args, main_view=main_view, model=model)

from __future__ import annotations

import functools
import logging
import sys
from typing import TYPE_CHECKING, Generic

from typing_extensions import TypeVarTuple, Unpack

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from qtpy.QtCore import SignalInstance


_LOGGER = logging.getLogger("COMPOSEUI_SIGNAL")
_STREAM_HANDLER = logging.StreamHandler(sys.stdout)
_STREAM_HANDLER.setFormatter(
    logging.Formatter("%(asctime)s: %(message)s", "%Y-%m-%d %H:%M:%S")
)
_LOGGER.addHandler(_STREAM_HANDLER)
_LOGGER.setLevel(logging.DEBUG)

Ts = TypeVarTuple("Ts")


class Signal(Generic[Unpack[Ts]]):
    def __init__(self) -> None:
        self._name = ""
        self._qt_signal = _QtSignal()
        self._callbacks: list[Callable[[Unpack[Ts]], None]] = [self._log_signal]
        self._logger = _LOGGER

    def set_name(self, name: str) -> None:
        self._name = name

    def add_qt_signal(self, signal: SignalInstance) -> None:
        """Add the qt signal."""
        self._qt_signal.add_signal(signal, self._callbacks)

    def connect(self, callback: Callable[[Unpack[Ts]], None]) -> None:
        self._callbacks.append(callback)
        self._qt_signal.connect(callback)

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
                if len(args) > 0:
                    log_msgs.append("  -> CALL %s(%s)")
                else:
                    log_msgs.append("  -> CALL %s()")
                log_args.append(callback_name)
                log_args.extend(str(arg) for arg in args)
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

    def add_signal(
        self, signal: SignalInstance, callbacks: Sequence[Callable[..., None]]
    ) -> None:
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
    if isinstance(callback, functools.partial):
        inner = _get_function_name(callback.func)
        args = ", ".join(map(repr, callback.args))
        return f"{inner}({args})"
    name = getattr(callback, "__qualname__", None) or getattr(
        callback, "__name__", None
    )
    return name or type(callback).__name__

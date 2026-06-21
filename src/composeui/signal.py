from collections.abc import Callable
from typing import TYPE_CHECKING, Generic, TypeVar

if TYPE_CHECKING:
    from qtpy.QtCore import SignalInstance


T = TypeVar("T")


class Signal(Generic[T]):
    def __init__(self) -> None:
        self._qt_signals: list[SignalInstance] = []
        self._callbacks: list[Callable[..., None]] = []

    def add_qt_signal(self, signal: "SignalInstance") -> None:
        """Add the qt signal."""
        self._qt_signals.append(signal)
        for callback in self._callbacks:
            signal.connect(callback)

    def connect(self, callback: Callable[[T], None]) -> None:
        self._callbacks.append(callback)
        for qt_signal in self._qt_signals:
            qt_signal.connect(callback)

    def disconnect(self) -> None:
        for qt_signal in self._qt_signals:
            for callback in self._callbacks:
                qt_signal.disconnect(callback)

    def emit(self, value: T) -> None:
        for callback in self._callbacks:
            callback(value)


class SignalNoArgs:
    def __init__(self) -> None:
        self._qt_signals: list[SignalInstance] = []
        self._callbacks: list[Callable[..., None]] = []

    def add_qt_signal(self, signal: "SignalInstance") -> None:
        """Add the qt signal."""
        self._qt_signals.append(signal)
        for callback in self._callbacks:
            signal.connect(callback)

    def connect(self, callback: Callable[[], None]) -> None:
        self._callbacks.append(callback)
        for qt_signal in self._qt_signals:
            qt_signal.connect(callback)

    def disconnect(self) -> None:
        for qt_signal in self._qt_signals:
            for callback in self._callbacks:
                qt_signal.disconnect(callback)

    def emit(self) -> None:
        for callback in self._callbacks:
            callback()

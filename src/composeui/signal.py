import typing
from collections.abc import Callable

if typing.TYPE_CHECKING:
    from qtpy.QtCore import SignalInstance


class Signal:
    def __init__(self) -> None:
        self._qt_signals: list[SignalInstance] = []
        self._callbacks: list[Callable[..., None]] = []

    def add_qt_signal(self, signal: "SignalInstance") -> None:
        """Add the qt signal."""
        self._qt_signals.append(signal)
        for callback in self._callbacks:
            signal.connect(callback)

    def connect(self, callback: Callable[..., None]) -> None:
        self._callbacks.append(callback)
        for qt_signal in self._qt_signals:
            qt_signal.connect(callback)

    def disconnect(self) -> None:
        for qt_signal in self._qt_signals:
            for callback in self._callbacks:
                qt_signal.disconnect(callback)

    def emit(self) -> None: ...

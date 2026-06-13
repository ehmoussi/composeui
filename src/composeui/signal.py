import typing

if typing.TYPE_CHECKING:
    from qtpy.QtCore import SignalInstance


class Signal:
    def __init__(self) -> None:
        self._qt_signals: list[SignalInstance] = []

    def add_qt_signal(self, signal: "SignalInstance") -> None:
        """Add the qt signal."""
        self._qt_signals.append(signal)

    def connect(self) -> None: ...
    def disconnect(self) -> None: ...
    def emit(self) -> None: ...

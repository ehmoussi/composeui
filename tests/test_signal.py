from __future__ import annotations

from composeui.core.signal import Signal


class _Recorder:
    def __init__(self) -> None:
        self.received: list[int] = []

    def __call__(self, value: int) -> None:
        self.received.append(value)


def test_emit_calls_callbacks_without_a_code_object() -> None:
    """Signal logging must not require `__code__`: built-ins and callable objects have none."""
    signal: Signal[int] = Signal()
    appended: list[int] = []
    recorder = _Recorder()
    signal.connect(appended.append)
    signal.connect(recorder)

    signal.emit(3)

    assert appended == [3]
    assert recorder.received == [3]

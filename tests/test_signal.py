from __future__ import annotations

import gc

from composeui.core.application import Application
from composeui.core.signal import Signal
from composeui.core.view import MainView, StatusBar, View, define_view


@define_view
class _MainView(MainView):
    app_title = "Signals"
    extension = ".signals"


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


def test_app_connect_injects_the_view_and_main_view() -> None:
    """`Application.connect` hands a plain function its `view` and the app's `main_view`."""
    app = Application(main_view=_MainView())
    status_bar = app.main_view.status_bar
    calls: list[tuple[View, MainView]] = []

    @app.connect(view=status_bar, signals=[app.main_view.file_menu.save.triggered])
    def record(*, view: StatusBar, main_view: _MainView) -> None:
        calls.append((view, main_view))

    gc.collect()  # nothing but the signal holds the callback `connect` built
    app.main_view.file_menu.save.triggered.emit()

    assert len(calls) == 1
    assert calls[0][0] is status_bar
    assert calls[0][1] is app.main_view

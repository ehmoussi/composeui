from __future__ import annotations

import gc
from typing import TYPE_CHECKING

import pytest

from composeui.core.application import Application
from composeui.core.signal import Signal
from composeui.core.view import MainView, StatusBar, View, define_view

if TYPE_CHECKING:
    from composeui.core.model import Model


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
    app = Application(build_main_view=_MainView)
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


def test_a_callback_gets_as_many_of_the_signal_s_arguments_as_it_takes() -> None:
    app = Application(build_main_view=_MainView)
    signal: Signal[int, str] = Signal()
    signal.set_main_view(app.main_view)
    calls: list[tuple[object, ...]] = []

    def first(value: int) -> None:
        calls.append((value,))

    def none_but_the_main_view(main_view: _MainView) -> None:
        calls.append((main_view,))

    def every(*args: object) -> None:
        calls.append(args)

    signal.connect(first)
    signal.connect(none_but_the_main_view)
    signal.connect(every)
    signal.emit(3, "three")

    assert calls == [(3,), (app.main_view,), (3, "three")]


def test_now_calls_the_callback_right_away_then_on_each_emit() -> None:
    app = Application(build_main_view=_MainView)
    signal: Signal[int] = Signal()
    signal.set_main_view(app.main_view)
    calls: list[tuple[object, ...]] = []

    def record(*values: int, main_view: _MainView) -> None:
        calls.append((*values, main_view))

    signal.connect(record, now=True)
    assert calls == [(app.main_view,)]
    signal.emit(3)
    assert calls == [(app.main_view,), (3, app.main_view)]


@define_view
class _RecordView(View):
    """A record's view, showing what a longer-lived signal (e.g. its model's) emits."""

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.shown: list[int] = []

    def show(self, value: int, *, main_view: MainView) -> None:
        self.shown.append(value)


def test_a_view_s_method_is_no_longer_called_once_the_view_is_gone() -> None:
    main_view = _MainView()
    changed: Signal[int] = Signal()  # e.g. a model's, outliving its records' views
    changed.set_main_view(main_view)
    record = _RecordView()
    changed.connect(record.show)
    changed.emit(1)
    shown = record.shown
    del record
    gc.collect()

    changed.emit(2)  # e.g. once the record is deleted

    assert shown == [1]


def test_a_signal_disconnected_calls_none_of_its_callbacks() -> None:
    signal: Signal[int] = Signal()
    received: list[int] = []
    signal.connect(received.append)
    signal.disconnect()
    after: list[int] = []
    signal.connect(after.append)  # connected again since

    signal.emit(1)

    assert (received, after) == ([], [1])


def test_a_callback_asking_for_what_the_signal_hasn_t_is_told() -> None:
    def show(value: int, *, main_view: MainView) -> None:
        pass

    def sign(value: int, *, model: Model) -> None:
        pass

    def maybe_sign(value: int, *, model: Model | None = None) -> None:
        pass

    for callback, error in ((show, "The main view is missing."), (sign, "The model is missing.")):
        signal: Signal[int] = Signal()  # e.g. a view's, not given its main view yet
        signal.connect(callback)
        with pytest.raises(ValueError, match=error):
            signal.emit(1)
    optional: Signal[int] = Signal()
    optional.connect(maybe_sign)
    optional.emit(1)  # its default instead

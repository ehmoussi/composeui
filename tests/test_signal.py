from __future__ import annotations

import functools
import gc
import inspect
import logging
import sys
import threading
from typing import Any

import pytest

from composeui.core.application import Application, ModelApplication
from composeui.core.model import Model
from composeui.core.reactivity import reactive, start_reactions
from composeui.core.signal import Signal, SignalNoArgs
from composeui.core.view import (
    ButtonView,
    LabelView,
    MainView,
    StatusBar,
    View,
    child,
    define_view,
)


@define_view
class _MainView(MainView):
    app_title = "Signals"
    extension = ".signals"


class _Recorder:
    def __init__(self) -> None:
        self.received: list[int] = []

    def __call__(self, value: int) -> None:
        self.received.append(value)


def _first(value: int) -> None:
    pass


def _tag(label: str, *_values: object, into: list[str]) -> None:
    into.append(label)


@pytest.mark.parametrize("call", ["emit", "call_callbacks"])
def test_a_logged_signal_names_each_callback_with_the_arguments_and_where_it_is(
    call: str, caplog: pytest.LogCaptureFixture
) -> None:
    """As `--log-signals` shows them: a callback without a code object, by its `repr`."""
    signal: Signal[int] = Signal()
    signal.set_name("Pipe.changed")
    main_view = _MainView()
    signal.set_main_view(main_view)
    appended: list[int] = []
    recorder = _Recorder()
    tags: list[str] = []
    record = _RecordView()
    signal.connect(_first)
    signal.connect(appended.append)
    signal.connect(recorder)
    signal.connect(functools.partial(_tag, "pipe", into=tags))
    signal.connect(record.show)
    del record
    gc.collect()  # its method is no longer called, but still listed

    unconnected: Signal[int] = Signal()

    with caplog.at_level(logging.DEBUG, logger="COMPOSEUI_SIGNAL"):
        getattr(unconnected, call)(3)  # calls nothing: logs nothing
        getattr(signal, call)(3)

    here = f'File "{__file__}", line'
    assert [record.getMessage() for record in caplog.records] == [
        "\n".join(
            [
                "EMIT SIGNAL Pipe.changed",
                "  -> CALL _first(3)",
                f"          {here} {inspect.getsourcelines(_first)[1]}",
                "  -> CALL list.append(3)",
                f"          {appended.append!r}",
                "  -> CALL _Recorder(3)",
                f"          {recorder!r}",
                "  -> CALL _tag('pipe', into=list)(3)",
                f"          {here} {inspect.getsourcelines(_tag)[1]}",
                "  -> CALL <collected>(3)",
                "          ",
            ]
        )
    ]
    assert (appended, recorder.received, tags) == ([3], [3], ["pipe"])


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


def test_two_threads_connecting_a_signal_at_once_keep_both_callbacks() -> None:
    """E.g. the tables of two sessions, each in its request's thread, following one source."""
    signal: Signal[int] = Signal()  # connected by none yet
    checked, resume, second_done = threading.Event(), threading.Event(), threading.Event()
    received: list[str] = []

    def pause_once_checked(frame: Any, event: str, arg: object) -> None:
        # the first thread stops as `connect` has looked at the callbacks, before it adds one
        if event == "c_return" and arg is isinstance and frame.f_code.co_name == "connect":
            sys.setprofile(None)
            checked.set()
            resume.wait(timeout=5)

    def connect_first() -> None:
        sys.setprofile(pause_once_checked)
        signal.connect(lambda _value: received.append("first"))

    def connect_second() -> None:
        signal.connect(lambda _value: received.append("second"))
        second_done.set()

    first = threading.Thread(target=connect_first)
    first.start()
    assert checked.wait(timeout=5)
    second = threading.Thread(target=connect_second)
    second.start()
    second_done.wait(timeout=0.5)  # done at once, unless it waits for the first thread
    resume.set()
    first.join()
    second.join()

    signal.emit(1)

    assert sorted(received) == ["first", "second"]


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


@define_view
class _WiredMainView(MainView):
    app_title = "Wired"
    extension = ".wired"

    early: ButtonView = child(ButtonView, text="Early")
    late: ButtonView = child(ButtonView, text="Late")

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.early.clicked.connect(lambda: None)  # made as the view is built


def test_a_signal_made_before_or_after_the_app_wires_its_view_gives_main_view_and_model() -> None:
    app = ModelApplication(build_main_view=_WiredMainView, build_model=Model)
    given: list[tuple[MainView, Model]] = []

    def record(*, main_view: MainView, model: Model) -> None:
        given.append((main_view, model))

    for button in (app.main_view.early, app.main_view.late):  # `late`'s made only now
        button.clicked.connect(record)
        button.clicked.emit()

    assert given == [(app.main_view, app.model)] * 2


def test_a_signal_given_to_a_view_or_set_since_is_the_one_it_emits() -> None:
    clicked = SignalNoArgs()
    calls: list[str] = []
    clicked.connect(lambda: calls.append("clicked"))

    button = ButtonView(clicked=clicked)
    button.clicked.emit()
    assert button.clicked is clicked
    assert calls == ["clicked"]

    replaced = SignalNoArgs()
    button.clicked = replaced  # in place of the one made
    button.clicked.emit()

    assert button.clicked is replaced
    assert calls == ["clicked"]  # the first one's callback, not the new one's


def test_two_threads_reading_a_view_s_new_signal_at_once_share_it() -> None:
    """A view's signal is made on its first read: two first reads must make one."""
    button = ButtonView()
    looked, resume = threading.Event(), threading.Event()
    read: list[Signal[()]] = []

    def pause_once_looked(frame: Any, event: str, _arg: object) -> None:
        # the first thread stops as it found no signal made, before it makes one
        if event == "return" and frame.f_code.co_name == "made_signal":
            sys.setprofile(None)
            looked.set()
            resume.wait(timeout=5)

    def read_first() -> None:
        sys.setprofile(pause_once_looked)
        read.append(button.clicked)

    first = threading.Thread(target=read_first)
    first.start()
    assert looked.wait(timeout=5)
    second = button.clicked  # made meanwhile
    resume.set()
    first.join()

    assert read == [second]
    assert read[0] is second


@define_view
class _ReactiveMainView(MainView):
    app_title = "Reactive"
    extension = ".reactive"

    name: LabelView = child(LabelView, text="Ada")
    greeting: LabelView = child(LabelView)

    @reactive
    def greet(self) -> None:
        self.greeting.text = f"Hello {self.name.text}"


def test_a_view_built_once_a_reactive_method_runs_still_gives_its_signals() -> None:
    start_reactions(_ReactiveMainView())  # reads of view fields are tracked from now on
    button = ButtonView()
    calls: list[str] = []

    button.clicked.connect(lambda: calls.append("clicked"))
    button.clicked.emit()

    assert isinstance(button.clicked, Signal)
    assert calls == ["clicked"]


def test_a_view_replacing_a_signal_with_another_kind_of_field_is_refused() -> None:
    # what type checkers refuse already: as an app without one writes it
    namespace = {"__annotations__": {"clicked": "int"}, "clicked": 0}
    counted = type("_CountedButton", (ButtonView,), namespace)
    with pytest.raises(TypeError, match="replaces a signal"):
        define_view(counted)

from __future__ import annotations

import functools
import gc
import inspect
import logging
import subprocess
import sys
import threading
from typing import TYPE_CHECKING, Any

import pytest
from typing_extensions import override

from composeui.core.application import Application, ModelApplication
from composeui.core.model import Model
from composeui.core.reactivity import reactive, start_reactions
from composeui.core.signal import Signal, SignalNoArgs
from composeui.core.view import (
    ButtonView,
    LabelView,
    MainView,
    StatusBar,
    TableView,
    View,
    child,
    define_view,
)

if TYPE_CHECKING:
    from pathlib import Path


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


def test_app_connect_gives_its_own_main_view_and_model_whatever_signal_emits() -> None:
    """Not those of the signal, from another app, or none for a signal that no view owns."""
    app = ModelApplication(build_main_view=_WiredMainView, build_model=Model)
    other = ModelApplication(build_main_view=_WiredMainView, build_model=Model)
    standalone = SignalNoArgs()
    given: list[tuple[object, ...]] = []

    @app.connect(view=app.main_view.early, signals=[other.main_view.early.clicked, standalone])
    def record(*, view: ButtonView, main_view: MainView, model: Model) -> None:
        given.append((view, main_view, model))

    other.main_view.early.clicked.emit()
    standalone.emit()

    assert given == [(app.main_view.early, app.main_view, app.model)] * 2


def test_a_signal_injects_its_owning_view_without_an_app() -> None:
    table = TableView()
    calls: list[tuple[object, ...]] = []

    def record(row: int, column: int, text: str, *, view: TableView) -> None:
        calls.append((row, column, text, view))

    def first(row: int, *, view: TableView) -> None:
        calls.append((row, view))

    def first_two(row: int, column: int, *, view: TableView) -> None:
        calls.append((row, column, view))

    def owner_only(view: TableView) -> None:
        calls.append((view,))

    def every(*values: object, view: TableView) -> None:
        calls.append((*values, view))

    table.cell_edited.connect(record)
    table.cell_edited.connect(first)
    table.cell_edited.connect(first_two)
    table.cell_edited.connect(owner_only, now=True)
    table.cell_edited.connect(every)
    table.cell_edited.emit(0, 1, "Ada")

    assert calls == [
        (table,),
        (0, 1, "Ada", table),
        (0, table),
        (0, 1, table),
        (table,),
        (0, 1, "Ada", table),
    ]


def test_view_injection_keeps_the_signal_arguments_typed(tmp_path: Path) -> None:
    script = tmp_path / "view_callback_types.py"
    source = (
        "from composeui.core.signal import Signal\n"
        "from composeui.core.view import ButtonView, MainView\n"
        "from composeui.core.model import Model\n"
        "signal: Signal[int, str, float] = Signal()\n"
        "def first(row: int, *, view: ButtonView) -> None: pass\n"
        "def first_two(row: int, text: str, *, view: ButtonView) -> None: pass\n"
        "def full(row: int, text: str, value: float, *, view: ButtonView) -> None: pass\n"
        "def context(row: int, *, view: ButtonView, main_view: MainView, model: Model)"
        " -> None: pass\n"
        "def two_main(row: int, text: str, *, view: ButtonView, main_view: MainView)"
        " -> None: pass\n"
        "def two_model(row: int, text: str, *, view: ButtonView, model: Model)"
        " -> None: pass\n"
        "def two_context(row: int, text: str, *, view: ButtonView, main_view: MainView,"
        " model: Model) -> None: pass\n"
        "def wrong_first(row: str, *, view: ButtonView) -> None: pass\n"
        "def wrong_second(row: int, text: int, *, view: ButtonView) -> None: pass\n"
        "def wrong_full(row: str, text: str, value: float, *, view: ButtonView) -> None: pass\n"
        "def wrong_context(row: str, *, view: ButtonView, main_view: MainView, model: Model)"
        " -> None: pass\n"
        "def wrong_two_main(row: int, text: int, *, view: ButtonView, main_view: MainView)"
        " -> None: pass\n"
        "def wrong_two_model(row: int, text: int, *, view: ButtonView, model: Model)"
        " -> None: pass\n"
        "def wrong_two_context(row: int, text: int, *, view: ButtonView, main_view: MainView,"
        " model: Model) -> None: pass\n"
        "signal.connect(first)\n"
        "signal.connect(first_two)\n"
        "signal.connect(full)\n"
        "signal.connect(context)\n"
        "signal.connect(two_main)\n"
        "signal.connect(two_model)\n"
        "signal.connect(two_context)\n"
        "signal.connect(wrong_first)\n"
        "signal.connect(wrong_second)\n"
        "signal.connect(wrong_full)\n"
        "signal.connect(wrong_context)\n"
        "signal.connect(wrong_two_main)\n"
        "signal.connect(wrong_two_model)\n"
        "signal.connect(wrong_two_context)\n"
    )
    script.write_text(source, encoding="utf-8")
    result = subprocess.run(  # noqa: S603 (mypy checks only the declarations above)
        [
            sys.executable,
            "-m",
            "mypy",
            "--follow-imports=silent",
            "--cache-dir",
            str(tmp_path / "cache"),
            str(script),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    errors = list(
        dict.fromkeys(
            line.split(": error:")[0] for line in result.stdout.splitlines() if ": error:" in line
        )
    )
    assert result.returncode == 1
    assert errors == [
        f"{script}:{number}"
        for number, line in enumerate(source.splitlines(), start=1)
        if ".connect(" in line and "wrong_" in line
    ]


def test_a_signal_does_not_keep_its_owning_view_alive() -> None:
    button = ButtonView()
    signal = button.clicked
    calls: list[str] = []

    def record(*, view: ButtonView) -> None:
        calls.append(view.text)

    signal.connect(record)
    signal.emit()
    assert calls == [button.text]
    del button
    gc.collect()

    with pytest.raises(ValueError, match=r"The view is missing\."):
        signal.emit()
    assert len(calls) == 1


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

    @override
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


class _PausingCallback:
    """A callback asking for its view, which pauses on its `pause_at`-th signature read."""

    def __init__(self, pause_at: int = 0) -> None:
        self.reads = 0
        self.pause_at = pause_at
        self.paused, self.resume = threading.Event(), threading.Event()
        self.received: list[ButtonView] = []

    @property
    def __signature__(self) -> inspect.Signature:
        # `connect` reads it as it prepares the callback, before registering it
        self.reads += 1
        if self.reads == self.pause_at:
            self.paused.set()
            if not self.resume.wait(timeout=5):
                raise TimeoutError
        return inspect.signature(self.__call__)

    def __call__(self, *, view: ButtonView) -> None:
        self.received.append(view)


@pytest.mark.parametrize("now", [False, True])
def test_a_signal_assigned_while_a_callback_connects_gives_it_the_owner(*, now: bool) -> None:
    def connect(signal: SignalNoArgs, callback: _PausingCallback, errors: list[Exception]) -> None:
        try:
            signal.connect(callback, now=now)
        except Exception as error:  # noqa: BLE001 - the main thread asserts the error
            errors.append(error)

    counted = _PausingCallback()
    SignalNoArgs().connect(counted)
    assert counted.reads > 0  # else no pause below tests anything
    for pause_at in range(1, counted.reads + 1):
        signal = SignalNoArgs()
        callback = _PausingCallback(pause_at)
        errors: list[Exception] = []
        worker = threading.Thread(target=connect, args=(signal, callback, errors))
        worker.start()
        try:
            assert callback.paused.wait(timeout=5)
            button = ButtonView(clicked=signal)  # while the callback is half connected
        finally:
            callback.resume.set()
            worker.join(timeout=5)
        assert not worker.is_alive()
        assert errors == []

        signal.emit()

        assert callback.received == [button] * (2 if now else 1), pause_at


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

    def owner(value: int, *, view: View) -> None:
        pass

    def maybe_sign(value: int, *, model: Model | None = None) -> None:
        pass

    def maybe_show(value: int, *, main_view: MainView | None = None) -> None:
        pass

    for callback, error in (
        (show, "The main view is missing."),
        (sign, "The model is missing."),
        (owner, "The view is missing."),
    ):
        signal: Signal[int] = Signal()  # e.g. a view's, not given its main view yet
        signal.connect(callback)
        with pytest.raises(ValueError, match=error):
            signal.emit(1)
    optional: Signal[int] = Signal()
    optional.connect(maybe_sign)
    optional.connect(maybe_show)
    optional.emit(1)  # their defaults instead


def test_a_view_refuses_a_signal_another_view_owns() -> None:
    first, second = ButtonView(text="first"), ButtonView(text="second")
    received: list[ButtonView] = []

    def record(*, view: ButtonView) -> None:
        received.append(view)

    first.clicked.connect(record)
    with pytest.raises(ValueError, match=r"ButtonView\.clicked belongs to another view"):
        second.clicked = first.clicked
    first.clicked = first.clicked  # its own: nothing changes

    first.clicked.emit()
    second.clicked.emit()

    assert received == [first]  # the callback still gets its view, and second kept its signal


def test_an_optional_view_uses_its_default_until_the_signal_has_an_owner() -> None:
    signal = SignalNoArgs()
    calls: list[str] = []

    def record(*, view: ButtonView | None = None) -> None:
        calls.append("no view" if view is None else view.text)

    signal.connect(record, now=True)
    button = ButtonView(text="Ready", clicked=signal)
    signal.emit()
    del button
    gc.collect()
    signal.emit()

    assert calls == ["no view", "Ready", "no view"]


@define_view
class _WiredMainView(MainView):
    app_title = "Wired"
    extension = ".wired"

    early: ButtonView = child(ButtonView, text="Early")
    late: ButtonView = child(ButtonView, text="Late")

    @override
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.early.clicked.connect(lambda: None)  # made as the view is built


def test_a_signal_made_before_or_after_the_app_wires_its_view_injects_its_context() -> None:
    app = ModelApplication(build_main_view=_WiredMainView, build_model=Model)
    given: list[tuple[View, MainView, Model]] = []

    def record(*, view: ButtonView, main_view: MainView, model: Model) -> None:
        given.append((view, main_view, model))

    def with_main(*, view: ButtonView, main_view: MainView) -> None:
        assert main_view is app.main_view
        view.text = "Main"

    def with_model(*, view: ButtonView, model: Model) -> None:
        assert model is app.model
        view.text += " and model"

    for button in (app.main_view.early, app.main_view.late):  # `late`'s made only now
        button.clicked.connect(with_main)
        button.clicked.connect(with_model)
        button.clicked.connect(record)
        button.clicked.emit()
        assert button.text == "Main and model"

    assert given == [
        (app.main_view.early, app.main_view, app.model),
        (app.main_view.late, app.main_view, app.model),
    ]


def test_a_signal_given_to_a_view_or_set_since_is_the_one_it_emits() -> None:
    clicked = SignalNoArgs()
    calls: list[object] = []
    clicked.connect(lambda: calls.append("clicked"))

    def record(*, view: ButtonView) -> None:
        calls.append(view)

    clicked.connect(record)

    button = ButtonView(clicked=clicked)
    button.clicked.emit()
    assert button.clicked is clicked
    assert calls == ["clicked", button]

    replaced = SignalNoArgs()
    replaced.connect(record)
    button.clicked = replaced  # in place of the one made
    button.clicked.emit()

    assert button.clicked is replaced
    assert calls == ["clicked", button, button]


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

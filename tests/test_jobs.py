"""Tests of `MainView.jobs`: functions run in threads, their outcome emitted on the main one."""

from __future__ import annotations

import functools
import gc
import logging
import subprocess
import sys
import threading
import time
import weakref
from typing import TYPE_CHECKING, cast

import attrs
import pytest
from typing_extensions import override

from composeui.core.application import ModelApplication
from composeui.core.jobs import CalledInJobError, JobCanceledError, repeat_wait, starting_study
from composeui.core.model import Model, RefusedError
from composeui.core.reactivity import reactive, start_reactions
from composeui.core.registry import RendererType
from composeui.core.study import new_study
from composeui.core.view import (
    OMIT,
    ActionView,
    ButtonView,
    InputView,
    LabelRowInputView,
    LabelView,
    ListView,
    MainView,
    View,
    child,
    define_view,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from pytestqt.qtbot import QtBot

    from composeui.core.jobs import Job


class _Model(Model):
    pass


@pytest.fixture
def app() -> ModelApplication[MainView, _Model]:
    return ModelApplication(build_main_view=MainView, build_model=_Model)


@pytest.fixture
def thread_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[BaseException], threading.Event]:
    errors: list[BaseException] = []
    surfaced = threading.Event()

    def record(args: threading.ExceptHookArgs) -> None:
        assert args.exc_value is not None
        errors.append(args.exc_value)
        surfaced.set()

    monkeypatch.setattr(threading, "excepthook", record)
    return errors, surfaced


def _double(_job: Job[int], value: int) -> int:
    return 2 * value


def _sleep(job: Job[bool]) -> bool:
    return job.sleep(60)


def _sleep_until_canceled(job: Job[None], slept: list[bool]) -> None:
    slept.append(job.sleep(60))


@define_view
class _Panel(View):
    """A view, not a main view, building its task as it is built."""

    status: LabelView = child(LabelView)
    result: LabelView = child(LabelView)

    @override
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.loader = self.build_task(_double)
        self.loader.show_state(self.status, views=[self.result])
        self.loader.disables(self.result)  # a callback holding the view


@define_view
class _Row(View):
    status: LabelView = child(LabelView)

    @override
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.loader = self.build_task(_sleep_until_canceled)
        self.loader.show_state(self.status, loading_text="Waiting")


@define_view
class _Rows(ListView[int]):
    @override
    def build_item(self, item: int) -> View:
        return _Row()


@define_view
class _PanelsView(MainView):
    panel: _Panel = child(_Panel)
    rows: _Rows = child(_Rows)


@define_view
class _SolverView(MainView):
    """A main view whose task enables and disables views, with `disables` and `cancel_with`."""

    #: not in the study, e.g. a setting of the app: New and Open keep it
    path: InputView = attrs.field(
        factory=lambda: InputView(text="study.comm"), metadata={OMIT: True}
    )
    study: InputView = child(InputView)
    open_button: ButtonView = child(ButtonView)
    stop: ButtonView = child(ButtonView)

    @override
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.release = threading.Event()
        self.solver = self.jobs.task(self._solve)
        self.solver.disables(self.study)
        self.solver.disables(self.open_button, enabled_if=lambda: self.path.text != "")
        self.solver.cancel_with(self.stop)

    def _solve(self, _job: Job[None]) -> None:
        assert self.release.wait(5)


def test_a_job_s_result_is_emitted_with_what_its_callbacks_ask_for(
    app: ModelApplication[MainView, _Model],
) -> None:
    jobs = app.main_view.jobs
    running: list[bool] = []
    results: list[tuple[int, MainView, _Model]] = []
    jobs.running_changed.connect(running.append)

    def show(result: int, *, main_view: MainView, model: _Model) -> None:
        results.append((result, main_view, model))

    jobs.start(_double, 21).finished.connect(show)
    assert jobs.is_running
    jobs.wait()

    assert results == [(42, app.main_view, app.model)]
    assert running == [True, False]
    assert not jobs.is_running


@pytest.mark.parametrize(
    "error_type", [ValueError, RefusedError, JobCanceledError, KeyError, OSError, RuntimeError]
)
def test_what_a_job_raises_is_logged_emitted_and_ends_it(
    app: ModelApplication[MainView, _Model],
    caplog: pytest.LogCaptureFixture,
    error_type: type[Exception],
) -> None:
    caplog.set_level(logging.INFO, "COMPOSEUI")
    jobs = app.main_view.jobs
    errors: list[Exception] = []
    finished: list[int] = []
    error = error_type("no luck")

    def fail(_job: Job[int]) -> int:
        raise error

    job = jobs.start(fail)
    job.failed.connect(errors.append)
    job.finished.connect(finished.append)

    jobs.wait()

    assert errors == [error]
    assert finished == []
    assert not jobs.is_running
    (record,) = [record for record in caplog.records if record.name == "COMPOSEUI"]
    if error_type is RefusedError:
        assert record.levelno == logging.WARNING
        assert record.exc_info is None
        assert "no luck" in record.getMessage()
    elif error_type is JobCanceledError:
        # the user asked for it: no traceback in the log
        assert record.levelno == logging.INFO
        assert record.exc_info is None
        assert "no luck" in record.getMessage()
    else:
        assert record.levelno == logging.ERROR
        assert isinstance(record.exc_info, tuple)
        assert record.exc_info[1] is error


@pytest.mark.parametrize(
    "method", ["start", "cancel", "drop", "task", "view.build_task", "task.start", "task.cancel"]
)
@pytest.mark.parametrize("tracked", [False, True])
def test_a_job_changing_the_jobs_surfaces_and_clears_its_runtime_state(
    app: ModelApplication[MainView, _Model],
    thread_errors: tuple[list[BaseException], threading.Event],
    method: str,
    *,
    tracked: bool,
) -> None:
    jobs = app.main_view.jobs
    surfaced_errors, surfaced = thread_errors
    running: list[bool] = []
    jobs.running_changed.connect(running.append)
    task = jobs.task(_double)
    calls = {
        "start": lambda: jobs.start(_double, 1),
        "cancel": jobs.cancel,
        "drop": jobs.drop,
        "task": lambda: jobs.task(_double),
        "view.build_task": lambda: LabelView().build_task(_double),
        "task.start": lambda: task.start(1),
        "task.cancel": task.cancel,
    }

    def change_the_jobs(job: Job[bool]) -> bool:
        calls[method]()
        return job.is_canceled

    errors: list[Exception] = []
    broken = None
    job = None
    if tracked:
        broken = jobs.task(change_the_jobs)
        broken.start()
    else:
        job = jobs.start(change_the_jobs)
        job.failed.connect(errors.append)
    assert surfaced.wait(5)
    jobs.wait()

    assert [type(error) for error in surfaced_errors] == [CalledInJobError]
    assert errors == []
    assert running == [True, False]
    assert not jobs.is_running
    if broken is not None:
        assert not broken.is_running
        assert broken.error is None
        assert not broken.has_result
    else:
        assert job is not None
        assert not job.is_canceled  # nothing else canceled, nor started


@pytest.mark.parametrize(
    "error_type",
    [
        AssertionError,
        AttributeError,
        NameError,
        NotImplementedError,
        TypeError,
        SystemExit,
        KeyboardInterrupt,
    ],
)
def test_programming_errors_and_exits_escape_to_the_thread_exception_handler(
    app: ModelApplication[MainView, _Model],
    thread_errors: tuple[list[BaseException], threading.Event],
    error_type: type[BaseException],
) -> None:
    error = error_type("programming mistake")
    errors, surfaced = thread_errors
    failures: list[Exception] = []
    results: list[int] = []

    def fail(_job: Job[int]) -> int:
        raise error

    job = app.main_view.jobs.start(fail)
    job.failed.connect(failures.append)
    job.finished.connect(results.append)
    assert surfaced.wait(5)
    app.main_view.jobs.wait()
    assert errors == [error]
    assert failures == []
    assert results == []
    assert not app.main_view.jobs.is_running


def test_aborting_a_task_preserves_other_work_and_allows_a_fresh_run(
    thread_errors: tuple[list[BaseException], threading.Event],
) -> None:
    view = MainView()
    errors, surfaced = thread_errors

    def work(job: Job[int, int], *, broken: bool) -> int:
        job.report_progress(1)
        if broken:
            msg = "broken task"
            raise TypeError(msg)
        return 42

    healthy = view.jobs.task(_sleep)
    broken = view.jobs.task(work)
    other_running: list[bool] = []

    def stopped() -> None:
        if not broken.is_running:
            other_running.append(healthy.is_running)
            healthy.cancel()

    broken.changed.connect(stopped)
    healthy.start()
    broken.start(broken=True)
    assert surfaced.wait(5)
    view.jobs.wait()
    assert other_running == [True]
    assert len(errors) == 1
    assert broken.progress is None
    assert broken.result is None
    assert broken.error is None
    assert healthy.has_result
    assert healthy.result is False
    broken.start(broken=False)
    view.jobs.wait()
    assert broken.result == 42
    assert broken.has_result


def test_a_dropped_jobs_programming_error_still_surfaces_without_touching_the_new_run(
    app: ModelApplication[MainView, _Model],
    thread_errors: tuple[list[BaseException], threading.Event],
) -> None:
    release = threading.Event()
    errors, surfaced = thread_errors
    error = AssertionError("old job's bug")

    def fail(_job: Job[int]) -> int:
        release.wait(5)
        raise error

    app.main_view.jobs.start(fail)
    app.main_view.jobs.drop()
    release.set()
    assert surfaced.wait(5)
    results: list[int] = []
    app.main_view.jobs.start(_double, 21).finished.connect(results.append)
    app.main_view.jobs.wait()
    assert errors == [error]
    assert results == [42]


def test_a_canceled_job_stops_sleeping_and_still_finishes(
    app: ModelApplication[MainView, _Model],
) -> None:
    jobs = app.main_view.jobs
    slept: list[bool] = []
    jobs.start(_sleep).finished.connect(slept.append)

    jobs.cancel()
    jobs.wait(timeout=5)

    assert slept == [False]  # long before its 60 s


def test_a_new_study_drops_the_jobs_working_for_the_old_one(
    app: ModelApplication[MainView, _Model],
) -> None:
    jobs = app.main_view.jobs
    running: list[bool] = []
    slept: list[bool] = []
    jobs.running_changed.connect(running.append)
    job = jobs.start(_sleep)
    job.finished.connect(slept.append)

    app.main_view.reset_state()

    assert job.is_canceled
    assert running == [True, False]
    jobs.wait()  # nothing left to wait for
    assert slept == []


def test_a_job_s_result_is_emitted_on_the_gui_thread(qtbot: QtBot) -> None:
    pytest.importorskip("qtpy")
    main_view = MainView()
    main_view.render(RendererType.QT)
    threads: list[threading.Thread] = []

    def record(_result: int) -> None:
        threads.append(threading.current_thread())

    main_view.jobs.start(_double, 1).finished.connect(record)
    qtbot.waitUntil(lambda: len(threads) == 1)

    assert threads == [threading.main_thread()]
    with pytest.raises(RuntimeError):  # the event loop emits them
        main_view.jobs.wait()


def test_a_job_s_callbacks_are_called_on_the_main_thread_before_its_result(
    app: ModelApplication[MainView, _Model],
) -> None:
    jobs = app.main_view.jobs
    calls: list[tuple[str, threading.Thread]] = []

    def record(name: str) -> None:
        calls.append((name, threading.current_thread()))

    def count(job: Job[int], value: int) -> int:
        for step in range(value):
            job.call_on_main_thread(functools.partial(record, f"step {step}"))
        return value

    jobs.start(count, 2).finished.connect(lambda _: record("finished"))
    jobs.wait()

    main = threading.current_thread()
    assert calls == [("step 0", main), ("step 1", main), ("finished", main)]


@pytest.mark.parametrize("report_progress", [False, True])
def test_a_dropped_job_s_callbacks_are_not_called(
    app: ModelApplication[MainView, _Model],
    *,
    report_progress: bool,
) -> None:
    jobs = app.main_view.jobs
    handed_over = threading.Event()
    calls: list[str] = []

    def hand_over(job: Job[None, str]) -> None:
        if report_progress:
            job.report_progress("called")
        else:
            job.call_on_main_thread(lambda: calls.append("called"))
        handed_over.set()

    jobs.start(hand_over).progress.connect(calls.append)
    assert handed_over.wait(5)
    jobs.drop()
    jobs.start(_double, 1)  # waiting for it calls what the dropped one handed over
    jobs.wait()

    assert calls == []


def test_a_job_handing_over_before_the_main_view_renders_reaches_it_in_order(
    qtbot: QtBot,
) -> None:
    pytest.importorskip("qtpy")
    main_view = MainView()
    handed_over = threading.Event()
    calls: list[tuple[str, threading.Thread]] = []

    def record(name: str) -> None:
        calls.append((name, threading.current_thread()))

    def step(job: Job[int]) -> int:
        job.call_on_main_thread(functools.partial(record, "step"))
        handed_over.set()
        return 1

    # started as `setup_model` would, before the app shows its main view
    main_view.jobs.start(step).finished.connect(lambda _: record("finished"))
    assert handed_over.wait(5)
    main_view.render(RendererType.QT)
    qtbot.waitUntil(lambda: len(calls) == 2)

    main = threading.main_thread()
    assert calls == [("step", main), ("finished", main)]


def test_a_main_view_its_backend_doesn_t_render_still_gets_its_jobs_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    renderers = pytest.importorskip("composeui.webcore.renderers").RENDERERS
    monkeypatch.delitem(renderers, "main")  # e.g. a backend of an app's own
    main_view = MainView()
    results: list[int] = []

    main_view.render(RendererType.WEB)
    main_view.jobs.start(_double, 1).finished.connect(results.append)
    main_view.jobs.wait()  # no renderer: waiting emits them

    assert main_view.renderer is None
    assert results == [2]


@pytest.mark.parametrize("report_progress", [False, True])
def test_a_job_s_callbacks_are_called_on_the_gui_thread(
    qtbot: QtBot, *, report_progress: bool
) -> None:
    pytest.importorskip("qtpy")
    main_view = MainView()
    main_view.render(RendererType.QT)
    threads: list[threading.Thread] = []

    def hand_over(job: Job[None, int]) -> None:
        if report_progress:
            job.report_progress(1)
        else:
            job.call_on_main_thread(lambda: threads.append(threading.current_thread()))

    main_view.jobs.start(hand_over).progress.connect(
        lambda _value: threads.append(threading.current_thread())
    )
    qtbot.waitUntil(lambda: len(threads) == 1)

    assert threads == [threading.main_thread()]


@pytest.mark.parametrize("fail", [False, True])
def test_job_progress_injects_context_and_arrives_before_the_outcome(
    app: ModelApplication[MainView, _Model], *, fail: bool
) -> None:
    calls: list[tuple[int, threading.Thread, MainView, _Model]] = []
    outcomes: list[str] = []

    def work(job: Job[int, int]) -> int:
        job.report_progress(1)
        job.report_progress(2)
        if fail:
            msg = "refused"
            raise RefusedError(msg)
        return 2

    def progress(value: int, *, main_view: MainView, model: _Model) -> None:
        assert outcomes == []
        calls.append((value, threading.current_thread(), main_view, model))

    job = app.main_view.jobs.start(work)
    job.progress.connect(progress)
    job.finished.connect(lambda _result: outcomes.append("finished"))
    job.failed.connect(lambda _error: outcomes.append("failed"))
    app.main_view.jobs.wait()

    assert calls == [
        (1, threading.current_thread(), app.main_view, app.model),
        (2, threading.current_thread(), app.main_view, app.model),
    ]
    assert outcomes == (["failed"] if fail else ["finished"])


def _report_each(
    job: Job[None, int], count: int, reported: threading.Event, release: threading.Event
) -> None:
    """Report 1 to `count`, then wait for `release`: its outcome comes after them."""
    for value in range(1, count + 1):
        job.report_progress(value)
    reported.set()
    assert release.wait(10)


@define_view
class _CopyMainView(MainView):
    @override
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.copy = self.build_task(_report_each)
        self.shown: list[int | None] = []

    @reactive
    def show_progress(self) -> None:
        self.shown.append(self.copy.progress)


def test_progress_reported_while_the_main_thread_is_busy_reaches_it_at_once(
    qtbot: QtBot,
) -> None:
    pytest.importorskip("qtpy")
    main_view = _CopyMainView()
    main_view.render(RendererType.QT)
    start_reactions(main_view)
    values: list[int] = []
    main_view.copy.progress_reported.connect(values.append)
    reported, release = threading.Event(), threading.Event()
    try:
        main_view.copy.start(3, reported, release)
        assert reported.wait(5)  # the main thread ran no event meanwhile
        assert values == []
        qtbot.waitUntil(lambda: len(values) == 3)
    finally:
        release.set()
    qtbot.waitUntil(lambda: not main_view.copy.is_running)

    assert values == [1, 2, 3]  # each one
    # its first run, the start, once for the three reports, the outcome
    assert main_view.shown == [None, None, 3, 3]


def test_a_callback_raising_doesn_t_stop_what_the_job_handed_over_after_it(
    qtbot: QtBot,
) -> None:
    pytest.importorskip("qtpy")
    main_view = MainView()
    main_view.render(RendererType.QT)
    values: list[int] = []
    error = ValueError("no luck")

    def show(value: int) -> None:
        values.append(value)
        if value == 1:
            raise error

    reported, release = threading.Event(), threading.Event()
    with qtbot.capture_exceptions() as exceptions:
        try:
            main_view.jobs.start(_report_each, 3, reported, release).progress.connect(show)
            assert reported.wait(5)  # the three wait for the main thread together
            qtbot.waitUntil(lambda: len(values) == 3)
        finally:
            release.set()
        qtbot.waitUntil(lambda: not main_view.jobs.is_running)

    assert values == [1, 2, 3]
    assert [exception for _type, exception, _traceback in exceptions] == [error]


def test_the_jobs_report_their_end_when_a_result_s_callback_raises() -> None:
    main_view = MainView()
    running: list[bool] = []
    main_view.jobs.running_changed.connect(running.append)
    error = ValueError("no luck")

    def show(_result: int) -> None:
        raise error

    main_view.jobs.start(_double, 1).finished.connect(show)
    with pytest.raises(ValueError, match="no luck"):
        main_view.jobs.wait()

    assert running == [True, False]


def test_a_job_whose_thread_doesn_t_start_leaves_nothing_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main_view = MainView()
    running: list[bool] = []
    main_view.jobs.running_changed.connect(running.append)
    task = main_view.jobs.task(_double)
    latest = main_view.jobs.task(_sleep)
    start = threading.Thread.start

    def fail(_thread: threading.Thread) -> None:
        msg = "can't start new thread"
        raise RuntimeError(msg)

    monkeypatch.setattr(threading.Thread, "start", fail)
    with pytest.raises(RuntimeError, match="can't start"):
        task.start(1)
    assert not task.is_running
    assert not main_view.jobs.has_workers
    assert running == [True, False]
    monkeypatch.setattr(threading.Thread, "start", start)
    latest.start()
    try:
        monkeypatch.setattr(threading.Thread, "start", fail)
        with pytest.raises(RuntimeError, match="can't start"):
            latest.start_latest()
    finally:
        monkeypatch.setattr(threading.Thread, "start", start)
        # the run before goes on, no thread replaced it: it's the one canceled
        latest.cancel()
    main_view.jobs.wait()

    assert latest.result is False
    assert running == [True, False, True, False]
    assert task.start(2)
    main_view.jobs.wait()
    assert task.result == 4


def test_a_callback_s_nested_event_loop_gets_what_the_job_handed_over_in_order(
    qtbot: QtBot,
) -> None:
    pytest.importorskip("qtpy")
    main_view = MainView()
    main_view.render(RendererType.QT)
    values: list[int] = []
    reported, release = threading.Event(), threading.Event()

    def report(job: Job[None, int]) -> None:
        job.report_progress(1)
        job.report_progress(2)
        reported.set()
        assert release.wait(10)
        job.report_progress(3)

    def show(value: int) -> None:
        values.append(value)
        if value == 1:  # as a modal dialog does, while 2 waits and 3 isn't reported yet
            release.set()
            qtbot.waitUntil(lambda: 3 in values)

    try:
        main_view.jobs.start(report).progress.connect(show)
        assert reported.wait(5)
        qtbot.waitUntil(lambda: not main_view.jobs.is_running)
    finally:
        release.set()

    assert values == [1, 2, 3]


@define_view
class _NoteMainView(MainView):
    note: InputView = child(InputView)
    summary: InputView = child(InputView)

    @reactive
    def summarize(self) -> None:
        self.summary.text = self.note.text[:4]


def _read(job: Job[str], text: str) -> str:
    """Read `text`, as a job reading what the next start reads again, e.g. a file."""
    del job
    return text


def test_what_a_study_s_job_gives_on_a_toolkit_is_no_unsaved_change(
    qtbot: QtBot,
) -> None:
    pytest.importorskip("qtpy")
    main_view = _NoteMainView()
    main_view.render(RendererType.QT)
    start_reactions(main_view)
    main_view._mark_saved()  # noqa: SLF001 (as the app's start does)
    with starting_study(main_view.jobs):  # as the app's start does
        job = main_view.jobs.start(_read, "from the job")
    job.finished.connect(lambda text: setattr(main_view.note, "text", text))
    qtbot.waitUntil(lambda: not main_view.jobs.is_running)

    # its reactive method ran before the study was taken as saved, not after a batch
    assert main_view.summary.text == "from"
    assert not main_view.has_unsaved_changes()


def test_raise_if_canceled_stops_the_job_once_it_is_canceled(
    app: ModelApplication[MainView, _Model],
) -> None:
    jobs = app.main_view.jobs
    started = threading.Event()

    def work(job: Job[int]) -> int:
        job.raise_if_canceled()  # not yet: it goes on
        started.set()
        job.sleep(10)
        job.raise_if_canceled()
        return 1

    job = jobs.start(work)
    errors: list[Exception] = []
    results: list[int] = []
    job.failed.connect(errors.append)
    job.finished.connect(results.append)
    assert started.wait(5)
    job.cancel()
    jobs.wait()

    assert results == []
    (error,) = errors
    assert isinstance(error, JobCanceledError)


def test_waiting_for_a_job_running_past_its_time_says_how_many(
    app: ModelApplication[MainView, _Model],
) -> None:
    jobs = app.main_view.jobs
    jobs.start(_sleep)

    with pytest.raises(TimeoutError, match=r"1 jobs still running after 0\.1 s"):
        jobs.wait(timeout=0.1)
    jobs.cancel()
    jobs.wait(timeout=5)


def test_progress_values_and_handlers_keep_the_workers_type(tmp_path: Path) -> None:
    script = tmp_path / "progress_types.py"
    script.write_text(
        "from typing_extensions import assert_type\n"
        "from typing import Optional\n"
        "from composeui.core.jobs import Job, Task\n"
        "from composeui.core.view import MainView\n"
        "def work(job: Job[str, int]) -> str:\n"
        "    job.report_progress(1)\n"
        "    job.report_progress('wrong type')\n"
        "    return 'done'\n"
        "def plain(job: Job[int]) -> int:\n"
        "    return 1\n"
        "def tracked(job: Job[str, int], value: int, /) -> str:\n"
        "    return str(value)\n"
        "def show(value: int) -> None:\n"
        "    pass\n"
        "def wrong_handler(value: str) -> None:\n"
        "    pass\n"
        "view = MainView()\n"
        "job = view.jobs.start(work)\n"
        "assert_type(job, Job[str, int])\n"
        "job.progress.connect(show)\n"
        "job.progress.connect(wrong_handler)\n"
        "ordinary = view.jobs.start(plain)\n"
        "assert_type(ordinary, Job[int])\n"
        "task = view.jobs.task(tracked)\n"
        "assert_type(task, Task[str, [int], int])\n"
        "assert_type(task.result, Optional[str])\n"
        "assert_type(task.progress, Optional[int])\n"
        "task.start(1)\n"
        "task.start('wrong type')\n",
        encoding="utf-8",
    )
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
    assert result.returncode == 1
    assert (
        'to "report_progress" of "Job" has incompatible type "str"; expected "int"' in result.stdout
    )
    assert 'to "connect" of "Signal" has incompatible type' in result.stdout
    assert 'to "start" of "Task" has incompatible type "str"; expected "int"' in result.stdout
    assert "Found 3 errors in 1 file" in result.stdout


@pytest.mark.parametrize("create_before_app", [False, True])
def test_a_task_tracks_runs_and_injects_context_on_the_main_thread(
    *, create_before_app: bool
) -> None:
    view = MainView()
    error = RefusedError("Try again")

    def work(job: Job[int, int], value: int, *, fail: bool) -> int:
        job.report_progress(value)
        if fail:
            raise error
        return value * 2

    task = view.jobs.task(work) if create_before_app else None
    app = ModelApplication(build_main_view=lambda: view, build_model=_Model)
    if task is None:
        task = view.jobs.task(work)
    states: list[tuple[bool, int | None, int | None, Exception | None, bool]] = []

    def record(*, main_view: MainView, model: _Model) -> None:
        assert threading.current_thread() is threading.main_thread()
        assert main_view is view
        assert model is app.model
        states.append((task.is_running, task.progress, task.result, task.error, task.has_result))

    task.changed.connect(record)
    # each outcome after `changed`, by the count of its states then
    outcomes: list[tuple[int, object]] = []

    def finished(result: int, *, main_view: MainView, model: _Model) -> None:
        assert main_view is view
        assert model is app.model
        outcomes.append((len(states), result))

    task.finished.connect(finished)
    task.failed.connect(lambda failure: outcomes.append((len(states), failure)))

    def reported(value: int, *, main_view: MainView, model: _Model) -> None:
        assert main_view is view
        assert model is app.model
        outcomes.append((len(states), f"reported {value}"))

    task.progress_reported.connect(reported)
    assert not task.is_running
    assert task.result is None
    assert task.progress is None
    assert task.error is None
    assert not task.has_result
    assert task.start(3, fail=True)
    assert not task.start(99, fail=False)
    view.jobs.wait()
    assert states == [
        (True, None, None, None, False),
        (True, 3, None, None, False),
        (False, 3, None, error, False),
    ]
    assert task.start(4, fail=False)
    view.jobs.wait()
    assert states[-3:] == [
        (True, None, None, None, False),
        (True, 4, None, None, False),
        (False, 4, 8, None, True),
    ]
    task.start(5, fail=True)
    view.jobs.wait()
    view.jobs.drop()
    assert states[-1] == (False, None, None, None, False)
    # dropping emits no outcome
    assert outcomes == [
        (2, "reported 3"),
        (3, error),
        (5, "reported 4"),
        (6, 8),
        (8, "reported 5"),
        (9, error),
    ]


def test_a_task_can_succeed_with_none_and_restart_from_its_changed_callback() -> None:
    view = MainView()

    def work(_job: Job[None]) -> None:
        return None

    task = view.jobs.task(work)
    results: list[None] = []

    def restart() -> None:
        if task.has_result:
            results.append(task.result)
            if len(results) == 1:
                task.start()

    task.changed.connect(restart)
    task.start()
    view.jobs.wait()
    assert results == [None, None]
    assert task.has_result
    assert not task.is_running


@pytest.mark.parametrize("fail", [False, True])
def test_a_task_disables_its_views_while_it_runs_and_enables_its_stop_until_asked(
    *, fail: bool
) -> None:
    view = MainView()
    started = threading.Event()

    def work(job: Job[str]) -> str:
        started.set()
        while job.sleep(0.01):
            pass
        if fail:
            msg = "stopped badly"
            raise RefusedError(msg)
        return "stopped"

    task = view.jobs.task(work)
    source, stop, stop_action = LabelRowInputView(), ButtonView(), ActionView()
    task.disables(source)
    task.cancel_with(stop, stop_action)
    states: list[tuple[bool, bool, bool, bool]] = []

    def record() -> None:
        states.append(
            (source.is_enabled, stop.is_enabled, stop_action.is_enabled, task.is_canceled)
        )

    task.changed.connect(record)
    record()  # idle
    task.start()
    assert started.wait(5)
    stop_action.triggered.emit()  # e.g. Stop in the toolbar
    stop.clicked.emit()  # asked already: nothing more
    view.jobs.wait()

    assert states == [
        (True, False, False, False),
        (False, True, True, False),
        (False, False, False, True),
        (True, False, False, False),  # whatever the outcome
    ]
    assert (task.result, task.error is not None) == (None if fail else "stopped", fail)

    # New or Open drop the run: its views come back
    started.clear()
    task.start()
    assert started.wait(5)
    view.reset_state()
    assert (source.is_enabled, stop.is_enabled) == (True, False)
    view.jobs.wait()


def test_a_view_that_a_task_disables_keeps_its_own_condition_after_the_run() -> None:
    view = MainView()
    started, release = threading.Event(), threading.Event()

    def work(_job: Job[None]) -> None:
        started.set()
        assert release.wait(5)

    task = view.jobs.task(work)
    path, open_file = InputView(), ButtonView()
    task.disables(open_file, enabled_if=lambda: path.text != "")
    states = [open_file.is_enabled]
    path.text = "study.comm"
    states.append(open_file.is_enabled)
    try:
        task.start()
        assert started.wait(5)
        states.append(open_file.is_enabled)
        path.text = ""  # cleared during the run
        path.text = "other.comm"  # filled again: the run still disables it
        states.append(open_file.is_enabled)
        path.text = ""
    finally:
        release.set()
        view.jobs.wait()
    states.append(open_file.is_enabled)  # the run is over, the path still empty
    path.text = "study.comm"
    states.append(open_file.is_enabled)
    assert states == [False, True, False, False, False, True]


def test_opening_a_study_saved_during_a_run_enables_the_task_s_views_as_no_run_goes_on(
    tmp_path: Path,
) -> None:
    view = _SolverView()
    view.solver.start()
    try:
        view.save_state(tmp_path / "study.json")
    finally:
        view.release.set()
        view.jobs.wait()
    view.load_state(tmp_path / "study.json")
    assert not view.solver.is_running
    assert (view.study.is_enabled, view.open_button.is_enabled, view.stop.is_enabled) == (
        True,
        True,
        False,
    )


def test_new_keeps_the_condition_of_a_view_on_a_field_that_the_study_doesn_t_hold() -> None:
    view = _SolverView()
    view.path.text = ""
    assert not view.open_button.is_enabled
    view.reset_state()
    assert view.path.text == ""
    # a newly built main view, whose path is filled, enables it
    assert not view.open_button.is_enabled


def test_canceling_a_task_at_startup_leaves_other_jobs_running() -> None:
    view = MainView()
    task = view.jobs.task(_sleep)
    task.cancel()  # An idle task has nothing to cancel.

    def cancel_task(running: bool) -> None:
        if running:
            task.cancel()

    view.jobs.running_changed.connect(cancel_task)
    task.start()
    other = view.jobs.start(_sleep)
    assert not other.is_canceled
    other.cancel()
    view.jobs.wait()
    assert task.has_result
    assert task.result is False


@pytest.mark.parametrize("fail", [False, True])
def test_dropping_a_task_clears_state_and_discards_queued_progress_and_outcomes(
    *, fail: bool
) -> None:
    view = MainView()
    queued = threading.Event()
    threads: list[threading.Thread] = []

    def work(job: Job[int, int], value: int, *, fail: bool) -> int:
        threads.append(threading.current_thread())
        job.report_progress(value)
        queued.set()
        if fail:
            msg = "dropped failure"
            raise RefusedError(msg)
        return value

    task = view.jobs.task(work)
    states: list[tuple[bool, int | None, int | None, Exception | None]] = []
    task.changed.connect(
        lambda: states.append((task.is_running, task.progress, task.result, task.error))
    )
    task.start(1, fail=fail)
    assert queued.wait(5)
    threads[0].join(5)  # The old outcome is queued before replacing the study.
    assert not threads[0].is_alive()
    view.reset_state()
    assert states[-1] == (False, None, None, None)
    task.start(2, fail=False)
    view.jobs.wait()
    assert states == [
        (True, None, None, None),
        (False, None, None, None),
        (True, None, None, None),
        (True, 2, None, None),
        (False, 2, 2, None),
    ]
    view.jobs.drop()
    assert not task.has_result
    assert states[-1] == (False, None, None, None)


def test_drop_resets_all_tasks_before_a_handler_starts_another_run() -> None:
    view = MainView()
    first = view.jobs.task(_sleep)
    second = view.jobs.task(_double)

    def start_another() -> None:
        if not first.is_running:
            second.start(21)

    first.changed.connect(start_another)
    first.start()
    view.jobs.drop()
    view.jobs.wait()
    assert not first.has_result
    assert not first.is_running
    assert second.has_result
    assert second.result == 42


def test_a_views_tasks_built_before_or_after_its_main_view_run_with_its_jobs() -> None:
    app = ModelApplication(build_main_view=_PanelsView, build_model=_Model)
    panel = app.main_view.panel
    later = panel.build_task(_double)
    outcomes: list[int] = []

    def finished(result: int, *, main_view: _PanelsView, model: _Model) -> None:
        assert main_view is app.main_view
        assert model is app.model
        outcomes.append(result)

    panel.loader.finished.connect(finished)
    later.finished.connect(finished)
    # `show_state` followed the task before its view was in a main view
    assert panel.status.is_visible
    assert not panel.result.is_visible
    panel.loader.start(3)
    later.start(4)
    app.main_view.jobs.wait()
    assert sorted(outcomes) == [6, 8]
    assert not panel.status.is_visible
    assert panel.result.is_visible


def test_a_task_of_a_view_in_no_main_view_refuses_to_start() -> None:
    panel = _Panel()
    with pytest.raises(RuntimeError, match="its view isn't in a main view"):
        panel.loader.start(1)
    assert not panel.loader.is_running


def test_removing_a_list_row_cancels_its_tasks_run_and_drops_its_outcome() -> None:
    main_view = _PanelsView()
    running: list[bool] = []
    main_view.jobs.running_changed.connect(running.append)
    main_view.rows.items = [1, 2, 3]  # rows built after the main view
    rows = main_view.rows.item_views
    assert all(isinstance(row, _Row) for row in rows)
    removed, last, idle = cast("list[_Row]", rows)
    outcomes: list[None] = []
    slept: list[bool] = []
    for row in (removed, last):
        row.loader.finished.connect(outcomes.append)
        assert row.loader.start(slept)
    main_view.rows.items = [2]  # a running row and an idle one
    assert running == [True]  # the last row's run goes on
    assert not removed.loader.is_running
    assert last.loader.is_running
    main_view.rows.items = []
    assert running == [True, False]
    workers_over = threading.Event()
    main_view.jobs.after_workers(workers_over.set)
    assert workers_over.wait(5)
    assert slept == [False, False]  # both canceled
    # the next job's wait emits what the rows' runs queued: nothing
    main_view.jobs.start(_double, 1)
    main_view.jobs.wait()
    assert outcomes == []
    assert removed.status.text == "Waiting"
    for row in (removed, last, idle):
        with pytest.raises(RuntimeError, match="its view isn't in a main view"):
            row.loader.start(slept)


def test_a_row_removed_by_a_callback_of_drop_hears_no_more_of_its_task() -> None:
    main_view = _PanelsView()
    main_view.rows.items = [1]
    (row,) = main_view.rows.item_views
    assert isinstance(row, _Row)
    heard: list[bool] = []
    row.loader.changed.connect(lambda: heard.append(True))

    def remove_the_row() -> None:
        main_view.rows.items = []

    # the panel's task, adopted before the row's, hears of the drop first
    main_view.panel.loader.changed.connect(remove_the_row)
    main_view.jobs.drop()
    assert heard == []


def test_a_view_replaced_in_its_main_view_is_freed_with_its_tasks_callbacks() -> None:
    main_view = _PanelsView()
    old = weakref.ref(main_view.panel.result)
    main_view.panel = _Panel()
    gc.collect()
    assert old() is None


def _until(main_view: MainView, condition: Callable[[], bool]) -> None:
    """Emit what the jobs of `main_view`, rendered by no toolkit, give until `condition` holds.

    A repeating task's next run comes from the timer's thread, after its wait.
    """
    deadline = time.monotonic() + 10
    while True:
        main_view.jobs.wait()
        if condition() or time.monotonic() > deadline:
            break
        time.sleep(0.01)
    assert condition()


@pytest.mark.parametrize(
    ("max_wait", "failures", "wait"),
    [
        (None, 0, 1.0),  # no failure: `every`
        (None, 1, 2.0),
        (None, 3, 8.0),
        (None, 4, 10.0),  # ten times `every` at most
        (None, 5000, 10.0),  # past what a float holds
        (5.0, 3, 5.0),
    ],
)
def test_a_repeating_task_waits_longer_after_each_failure_in_a_row(
    max_wait: float | None, failures: int, wait: float
) -> None:
    assert repeat_wait(1.0, 2.0, max_wait, failures) == wait


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({"every": 0.0}, "every must be more than 0 seconds"),
        ({"every": 1.0, "backoff": 0.5}, "backoff must be 1 or more"),
        ({"every": 2.0, "max_wait": 1.0}, "must be every"),
    ],
)
def test_a_task_refuses_a_wait_that_can_t_repeat_it(
    options: dict[str, float], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        MainView().jobs.task(_read, **options)


def test_a_failed_run_waits_longer_and_a_run_that_succeeds_waits_every_again() -> None:
    main_view = MainView()
    times: list[tuple[float, float]] = []  # each run's start and end, one run at a time

    def work(_job: Job[int]) -> int:
        start = time.monotonic()
        try:
            if len(times) in (0, 2):
                msg = "the server didn't answer"
                raise RefusedError(msg)
            return len(times)
        finally:
            times.append((start, time.monotonic()))

    # after a failure, 0.5 s; after two in a row, 25 s: longer than `_until` waits
    task = main_view.jobs.task(work, every=0.01, backoff=50.0, max_wait=100.0)
    task.start()
    _until(main_view, lambda: task.error is not None)
    assert not task.has_result

    _until(main_view, lambda: task.has_result)
    assert task.error is None  # the success replaced the failure
    assert times[1][0] - times[0][1] >= 0.5  # never sooner than the wait

    # the success set the count of failures back: the next failure waits 0.5 s again
    _until(main_view, lambda: len(times) == 4 and not task.is_running)
    task.cancel()


def test_start_latest_repeats_a_task_with_its_new_arguments() -> None:
    main_view = MainView()
    runs: list[str] = []
    entered, release = threading.Event(), threading.Event()

    def work(_job: Job[str], name: str) -> str:
        runs.append(name)
        if name == "first":
            entered.set()
            assert release.wait(10)
        return name

    task = main_view.jobs.task(work, every=0.01, debounce=0.0)
    try:
        assert task.start("first")
        assert entered.wait(10)
        assert not task.start("second")  # it repeats: already started
        task.start_latest("latest")  # while the first run goes on: it no longer counts
    finally:
        release.set()
    _until(main_view, lambda: runs.count("latest") >= 2)
    task.cancel()

    assert runs[0] == "first"
    assert set(runs[1:]) == {"latest"}
    assert task.result == "latest"


def test_a_run_that_the_timer_posted_before_a_stop_starts_no_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main_view = _PollMainView()
    jobs = main_view.jobs
    runs: list[int] = []
    posted, release, delivered = threading.Event(), threading.Event(), threading.Event()
    post = jobs._post  # noqa: SLF001 (held, then let through, as a busy main thread would)

    def held(callback: Callable[[], None]) -> None:
        posted.set()
        assert release.wait(10)
        post(callback)
        delivered.set()

    monkeypatch.setattr(jobs, "_post", held)

    def work(_job: Job[int]) -> int:
        runs.append(1)
        if len(runs) == 2:  # its next run then comes after the test, 100 s later
            msg = "the server didn't answer"
            raise RefusedError(msg)
        return len(runs)

    task = jobs.task(work, every=0.01, backoff=10_000.0, max_wait=1000.0)
    task.cancel_with(main_view.stop)
    try:
        task.start()
        _until(main_view, lambda: task.has_result)
        assert posted.wait(10)  # the next run is on its way to the main thread
        assert main_view.stop.is_enabled  # between two runs, Stop still stops it

        task.cancel()
        assert not main_view.stop.is_enabled
        task.start()  # again, while the run posted before the stop is on its way
    finally:
        release.set()
    assert delivered.wait(10)
    jobs.wait()

    assert runs == [1, 1]  # the start's run, not the one posted before the stop
    task.cancel()


def test_cancelling_the_jobs_during_a_run_ends_the_repeat() -> None:
    main_view = MainView()
    entered, release = threading.Event(), threading.Event()

    def work(job: Job[int]) -> int:
        entered.set()
        assert release.wait(10)
        return 1 if job.is_canceled else 2

    task = main_view.jobs.task(work, every=0.01)
    try:
        task.start()
        assert entered.wait(10)
        main_view.jobs.cancel()
    finally:
        release.set()
    main_view.jobs.wait()

    assert task.result == 1
    assert not task.is_repeating
    assert main_view.jobs.repeat_every is None


def test_cancelling_the_jobs_stops_a_task_waiting_for_its_next_run() -> None:
    main_view = MainView()
    task = main_view.jobs.task(_read, every=0.01)
    task.start("status")
    # its run is over: the next one, due or not, waits for `wait` to start
    _until(main_view, lambda: task.has_result and not task.is_running)
    heard: list[bool] = []
    task.changed.connect(lambda: heard.append(task.is_repeating))
    once = main_view.jobs.task(_read)  # no repeat to stop: nothing to tell
    once.changed.connect(lambda: heard.append(True))

    main_view.jobs.cancel()
    main_view.jobs.wait()

    assert heard == [False]  # e.g. a Stop button disabled
    assert not task.is_running  # a run posted before the cancel starts nothing


@define_view
class _PollMainView(MainView):
    status: InputView = child(InputView)
    stop: ButtonView = child(ButtonView)


def test_new_stops_a_repeating_task_and_a_loaded_callback_starts_it_for_the_new_study() -> None:
    main_view = _PollMainView()
    runs: list[str] = []

    def work(_job: Job[str], study: str) -> str:
        runs.append(study)
        return f"{study} checked {len(runs)} times"

    task = main_view.jobs.task(work, every=0.01)
    task.finished.connect(lambda status: setattr(main_view.status, "text", status))
    studies = iter(["first", "second"])

    def start_checking() -> None:
        task.start(next(studies))

    main_view.loaded.connect(start_checking)
    new_study(main_view, None)  # as the app's start does
    # between two runs: the next one, posted or not, can start only in `wait`, after New
    _until(main_view, lambda: len(runs) >= 2 and not task.is_running)
    # each run is the study's, as the one that the start started: no change of the user's
    assert not main_view.has_unsaved_changes()

    new_study(main_view, None)

    assert not task.has_result  # the run before belongs to the study replaced
    count = len(runs)
    _until(main_view, lambda: runs.count("second") >= 2 and not task.is_running)
    task.cancel()

    assert set(runs[count:]) == {"second"}  # the first study's repeat stopped
    assert not main_view.has_unsaved_changes()

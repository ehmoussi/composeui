"""Tests of `MainView.jobs`: functions run in threads, their outcome emitted on the main one."""

from __future__ import annotations

import functools
import logging
import subprocess
import sys
import threading
from typing import TYPE_CHECKING

import pytest

from composeui.core.application import ModelApplication
from composeui.core.jobs import CalledInJobError
from composeui.core.model import Model, RefusedError
from composeui.core.registry import RendererType
from composeui.core.view import MainView

if TYPE_CHECKING:
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


@pytest.mark.parametrize("error_type", [ValueError, RefusedError, KeyError, OSError, RuntimeError])
def test_what_a_job_raises_is_logged_emitted_and_ends_it(
    app: ModelApplication[MainView, _Model],
    caplog: pytest.LogCaptureFixture,
    error_type: type[Exception],
) -> None:
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
    else:
        assert record.levelno == logging.ERROR
        assert isinstance(record.exc_info, tuple)
        assert record.exc_info[1] is error


@pytest.mark.parametrize("method", ["start", "cancel", "drop", "task", "task.start"])
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
        "task.start": lambda: task.start(1),
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
    "error_type", [AssertionError, AttributeError, NameError, NotImplementedError, TypeError]
)
def test_programming_errors_escape_to_the_thread_exception_handler(
    app: ModelApplication[MainView, _Model],
    thread_errors: tuple[list[BaseException], threading.Event],
    error_type: type[Exception],
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
    assert outcomes == [(3, error), (6, 8), (9, error)]


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

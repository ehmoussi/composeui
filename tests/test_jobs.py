"""Tests of `MainView.jobs`: functions run in threads, their outcome emitted on the main one."""

from __future__ import annotations

import functools
import threading
from typing import TYPE_CHECKING

import pytest

from composeui.core.application import ModelApplication
from composeui.core.jobs import CalledInJobError
from composeui.core.model import Model
from composeui.core.registry import RendererType
from composeui.core.view import MainView

if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot

    from composeui.core.jobs import Job


class _Model(Model):
    pass


@pytest.fixture
def app() -> ModelApplication[MainView, _Model]:
    return ModelApplication(build_main_view=MainView, build_model=_Model)


def _double(_job: Job[int], value: int) -> int:
    return 2 * value


def _fail(_job: Job[int]) -> int:
    msg = "no luck"
    raise ValueError(msg)


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


def test_what_a_job_raises_is_emitted_and_ends_it(
    app: ModelApplication[MainView, _Model],
) -> None:
    jobs = app.main_view.jobs
    errors: list[Exception] = []
    finished: list[int] = []
    job = jobs.start(_fail)
    job.failed.connect(errors.append)
    job.finished.connect(finished.append)

    jobs.wait()

    assert [str(error) for error in errors] == ["no luck"]
    assert finished == []
    assert not jobs.is_running


@pytest.mark.parametrize("method", ["start", "cancel", "drop"])
def test_a_job_changing_the_jobs_fails(
    app: ModelApplication[MainView, _Model], method: str
) -> None:
    jobs = app.main_view.jobs
    calls = {
        "start": lambda: jobs.start(_double, 1),
        "cancel": jobs.cancel,
        "drop": jobs.drop,
    }

    def change_the_jobs(job: Job[bool]) -> bool:
        calls[method]()
        return job.is_canceled

    errors: list[Exception] = []
    job = jobs.start(change_the_jobs)
    job.failed.connect(errors.append)
    jobs.wait()

    assert [type(error) for error in errors] == [CalledInJobError]
    assert not job.is_canceled  # nothing else canceled, nor started


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


def test_a_dropped_job_s_callbacks_are_not_called(
    app: ModelApplication[MainView, _Model],
) -> None:
    jobs = app.main_view.jobs
    handed_over = threading.Event()
    calls: list[str] = []

    def hand_over(job: Job[None]) -> None:
        job.call_on_main_thread(lambda: calls.append("called"))
        handed_over.set()

    jobs.start(hand_over)
    assert handed_over.wait(5)
    jobs.drop()
    jobs.start(_double, 1)  # waiting for it calls what the dropped one handed over
    jobs.wait()

    assert calls == []


def test_a_job_s_callbacks_are_called_on_the_gui_thread(qtbot: QtBot) -> None:
    pytest.importorskip("qtpy")
    main_view = MainView()
    main_view.render(RendererType.QT)
    threads: list[threading.Thread] = []

    def hand_over(job: Job[None]) -> None:
        job.call_on_main_thread(lambda: threads.append(threading.current_thread()))

    main_view.jobs.start(hand_over)
    qtbot.waitUntil(lambda: len(threads) == 1)

    assert threads == [threading.main_thread()]


def test_waiting_for_a_job_running_past_its_time_says_how_many(
    app: ModelApplication[MainView, _Model],
) -> None:
    jobs = app.main_view.jobs
    jobs.start(_sleep)

    with pytest.raises(TimeoutError, match=r"1 jobs still running after 0\.1 s"):
        jobs.wait(timeout=0.1)
    jobs.cancel()
    jobs.wait(timeout=5)

"""`Jobs` in any order of starts, ends, cancels, drops and deliveries of their results."""

from __future__ import annotations

import contextlib
import threading
from typing import TYPE_CHECKING, Any

import attrs
from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import Bundle, RuleBasedStateMachine, invariant, rule

from composeui.core.model import RefusedError
from composeui.core.sqlitemodel import SqliteModel, SqliteTable
from composeui.core.view import MainView

if TYPE_CHECKING:
    from composeui.core.jobs import Job

_TIMEOUT = 30.0


class _Numbers(SqliteTable):
    create = "CREATE TABLE number(value INTEGER);"

    def add(self) -> None:
        with self.connection() as db:
            db.execute("INSERT INTO number VALUES (1)")

    def count(self) -> int:
        return int(self.fetch_column("SELECT COUNT(*) FROM number")[0])


class _NumbersModel(SqliteModel):
    def __init__(self) -> None:
        super().__init__()
        self.numbers = self.add_table(_Numbers)


@attrs.define(eq=False)
class _Run:
    """What the machine expects of a job, whose thread waits for `may_end`."""

    writes: bool
    job: Any = None
    thread: Any = None
    started: threading.Event = attrs.Factory(threading.Event)
    may_end: threading.Event = attrs.Factory(threading.Event)
    outcomes: list[str] = attrs.Factory(list)
    has_ended: bool = False
    is_canceled: bool = False
    is_dropped: bool = False
    is_delivered: bool = False

    @property
    def is_awaited(self) -> bool:
        """Tell whether the job's outcome is still to come."""
        return not self.is_dropped and not self.is_delivered


class _JobsMachine(RuleBasedStateMachine):
    runs = Bundle("runs")

    def __init__(self) -> None:
        super().__init__()
        self.main_view = MainView()
        self.jobs = self.main_view.jobs
        self.model = _NumbersModel()
        self.all_runs: list[_Run] = []
        self.written = 0
        self.called_after, self.waiting_after = 0, 0
        self.after_calls: list[int] = []
        self.changes: list[bool] = []
        self.jobs.running_changed.connect(self.changes.append)

    @rule(target=runs, writes=st.booleans(), fails=st.booleans())
    def start(self, *, writes: bool, fails: bool) -> _Run:
        run = _Run(writes=writes)

        def work(_job: Job[None, None]) -> None:
            run.thread = threading.current_thread()
            run.started.set()
            assert run.may_end.wait(_TIMEOUT)
            if writes:
                with contextlib.suppress(RefusedError):  # the machine's dropped jobs
                    self.model.numbers.add()
            if fails:
                msg = "the job's own failure"
                raise ValueError(msg)

        run.job = self.jobs.start(work)
        run.job.finished.connect(lambda _result: run.outcomes.append("finished"))
        run.job.failed.connect(lambda _error: run.outcomes.append("failed"))
        assert run.started.wait(_TIMEOUT)
        self.all_runs.append(run)
        return run

    @rule(run=runs)
    def end(self, run: _Run) -> None:
        if run.has_ended:
            return
        run.may_end.set()
        run.thread.join(_TIMEOUT)
        assert not run.thread.is_alive()
        run.has_ended = True
        if run.writes and not run.is_dropped:
            self.written += 1
        if not self._has_threads:
            self.called_after += self.waiting_after
            self.waiting_after = 0

    @rule()
    def cancel(self) -> None:
        self.jobs.cancel()
        for run in self.all_runs:
            run.is_canceled = run.is_canceled or run.is_awaited

    @rule()
    def drop(self) -> None:
        self.jobs.drop()
        for run in self.all_runs:
            if run.is_awaited:
                run.is_canceled = run.is_dropped = True

    @rule()
    def deliver(self) -> None:
        awaited = [run for run in self.all_runs if run.is_awaited]
        if all(run.has_ended for run in awaited):
            self.jobs.wait(_TIMEOUT)
            for run in awaited:
                run.is_delivered = True
            self._deliver_what_dropped_jobs_queued()

    def _deliver_what_dropped_jobs_queued(self) -> None:
        """Run one more job: `Jobs.wait` handles what's queued only while a job is running."""
        threads: list[threading.Thread] = []
        self.jobs.start(lambda _job: threads.append(threading.current_thread()))
        self.jobs.wait(_TIMEOUT)
        threads[0].join(_TIMEOUT)

    @rule()
    def ask_to_be_called_after_the_threads(self) -> None:
        self.jobs.after_workers(lambda: self.after_calls.append(1))
        if self._has_threads:
            self.waiting_after += 1
        else:
            self.called_after += 1

    @property
    def _has_threads(self) -> bool:
        return not all(run.has_ended for run in self.all_runs)

    @invariant()
    def running_means_an_outcome_is_still_to_come(self) -> None:
        assert self.jobs.is_running == any(run.is_awaited for run in self.all_runs)

    @invariant()
    def a_dropped_job_keeps_its_thread_counted(self) -> None:
        assert self.jobs.has_workers == self._has_threads

    @invariant()
    def each_job_reports_its_state(self) -> None:
        for run in self.all_runs:
            assert (run.job.is_canceled, run.job.is_dropped) == (run.is_canceled, run.is_dropped)

    @invariant()
    def an_outcome_comes_once_and_never_from_a_dropped_job(self) -> None:
        for run in self.all_runs:
            assert len(run.outcomes) == (1 if run.is_delivered else 0)

    @invariant()
    def a_dropped_job_writes_nothing(self) -> None:
        assert self.model.numbers.count() == self.written

    @invariant()
    def callbacks_wait_for_every_thread_and_run_once(self) -> None:
        assert len(self.after_calls) == self.called_after

    @invariant()
    def running_changed_alternates(self) -> None:
        assert self.changes == [index % 2 == 0 for index in range(len(self.changes))]

    def teardown(self) -> None:
        for run in self.all_runs:
            run.may_end.set()
            run.thread.join(_TIMEOUT)
        self.model.close()


TestJobsUsedInAnyOrder = _JobsMachine.TestCase
TestJobsUsedInAnyOrder.settings = settings(max_examples=100, stateful_step_count=20)


def test_a_job_dropped_after_its_thread_ended_emits_nothing() -> None:
    # the sequence the machine finds only some runs: its result is queued as it's dropped
    main_view = MainView()
    jobs = main_view.jobs
    entered = threading.Event()
    threads: list[threading.Thread] = []
    outcomes: list[object] = []

    def work(_job: Job[None, None]) -> None:
        threads.append(threading.current_thread())
        entered.set()

    job = jobs.start(work)
    job.finished.connect(outcomes.append)
    assert entered.wait(_TIMEOUT)
    threads[0].join(_TIMEOUT)

    jobs.drop()
    jobs.start(lambda _job: None)  # `Jobs.wait` handles what's queued while one is running
    jobs.wait(_TIMEOUT)

    assert outcomes == []

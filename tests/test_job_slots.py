"""Job slots: at most a number of jobs at once in a block, the others waiting in line."""

from __future__ import annotations

import functools
import threading
from typing import TYPE_CHECKING, Callable

import pytest

from composeui.core.jobs import JobCanceledError, JobSlots
from composeui.core.view import MainView

if TYPE_CHECKING:
    from collections.abc import Iterator

    from composeui.core.jobs import Job

#: seconds a test waits for a job before it fails
_TIMEOUT = 10


class _Runs:
    """Jobs that each wait for a slot, then hold it until the test releases them."""

    def __init__(self, limit: int) -> None:
        self.slots = JobSlots(limit)
        self.main_view = MainView()
        self.entered: list[str] = []
        #: each job's places in the line, as `on_wait` got them
        self.places: dict[str, list[int]] = {}
        self.errors: dict[str, Exception] = {}
        self._changed = threading.Condition()
        self._released: dict[str, threading.Event] = {}

    def start(self, name: str) -> Job[None]:
        """Start the job `name`: start the next one once this one's place or block is seen."""
        self.places[name] = []
        self._released[name] = threading.Event()
        job = self.main_view.jobs.start(self._run, name)
        job.failed.connect(functools.partial(self.errors.__setitem__, name))
        return job

    def _run(self, job: Job[None], name: str) -> None:
        with self.slots.slot(job, on_wait=functools.partial(self._report, name)):
            with self._changed:
                self.entered.append(name)
                self._changed.notify_all()
            assert self._released[name].wait(_TIMEOUT)

    def _report(self, name: str, place: int) -> None:
        with self._changed:
            self.places[name].append(place)
            self._changed.notify_all()

    def wait_until(self, predicate: Callable[[], bool]) -> None:
        with self._changed:
            assert self._changed.wait_for(predicate, _TIMEOUT)

    def release(self, name: str) -> None:
        self._released[name].set()

    def end(self) -> None:
        for released in self._released.values():
            released.set()
        self.main_view.jobs.wait(_TIMEOUT)


@pytest.fixture
def runs() -> Iterator[Callable[[int], _Runs]]:
    made: list[_Runs] = []

    def make(limit: int) -> _Runs:
        made.append(_Runs(limit))
        return made[-1]

    yield make
    for each in made:
        each.end()


def test_jobs_past_the_limit_wait_and_take_the_slots_in_the_order_they_came(
    runs: Callable[[int], _Runs],
) -> None:
    line = runs(2)
    line.start("a")
    line.wait_until(lambda: line.entered == ["a"])
    line.start("b")
    line.wait_until(lambda: line.entered == ["a", "b"])
    line.start("c")
    line.wait_until(lambda: line.places["c"] == [1])
    line.start("d")
    line.wait_until(lambda: line.places["d"] == [2])

    line.release("a")
    line.wait_until(lambda: line.entered == ["a", "b", "c"] and line.places["d"] == [2, 1])
    line.release("b")
    line.wait_until(lambda: line.entered == ["a", "b", "c", "d"])
    line.end()

    # each place once, as it changed
    assert line.places == {"a": [], "b": [], "c": [1], "d": [2, 1]}
    assert line.errors == {}


def test_a_job_canceled_while_waiting_leaves_the_line_and_the_next_one_moves_up(
    runs: Callable[[int], _Runs],
) -> None:
    line = runs(1)
    line.start("a")
    line.wait_until(lambda: line.entered == ["a"])
    canceled = line.start("b")
    line.wait_until(lambda: line.places["b"] == [1])
    line.start("c")
    line.wait_until(lambda: line.places["c"] == [2])

    canceled.cancel()
    line.wait_until(lambda: line.places["c"] == [2, 1])
    line.release("a")
    line.wait_until(lambda: line.entered == ["a", "c"])
    line.end()

    assert isinstance(line.errors.pop("b"), JobCanceledError)
    assert line.errors == {}


def test_a_job_canceled_doesn_t_take_a_free_slot() -> None:
    slots = JobSlots(1)
    main_view = MainView()
    ran: list[bool] = []
    errors: list[Exception] = []

    def take(job: Job[None]) -> None:
        job.cancel()
        with slots.slot(job):
            ran.append(True)

    main_view.jobs.start(take).failed.connect(errors.append)
    main_view.jobs.wait(_TIMEOUT)

    assert ran == []
    assert [type(error) for error in errors] == [JobCanceledError]


def test_a_block_that_raises_frees_its_slot() -> None:
    slots = JobSlots(1)
    main_view = MainView()
    outcomes: list[object] = []

    def fail(job: Job[None]) -> None:
        with slots.slot(job):
            msg = "the calculation failed"
            raise OSError(msg)

    def take(job: Job[str]) -> str:
        with slots.slot(job):
            return "taken"

    main_view.jobs.start(fail).failed.connect(outcomes.append)
    main_view.jobs.wait(_TIMEOUT)
    main_view.jobs.start(take).finished.connect(outcomes.append)
    main_view.jobs.wait(_TIMEOUT)

    assert [type(outcome) for outcome in outcomes] == [OSError, str]


def test_a_job_holding_a_slot_can_t_take_a_second_one() -> None:
    # a slot is left: without the check, the job would take both
    slots = JobSlots(2)
    main_view = MainView()
    errors: list[Exception] = []

    def nest(job: Job[None]) -> None:
        with slots.slot(job), slots.slot(job):
            pass

    main_view.jobs.start(nest).failed.connect(errors.append)
    main_view.jobs.wait(_TIMEOUT)

    assert len(errors) == 1
    assert "already holds or waits for a slot" in str(errors[0])


def test_a_job_waiting_for_a_slot_can_t_ask_for_a_second_one(
    runs: Callable[[int], _Runs],
) -> None:
    line = runs(1)
    line.start("a")
    line.wait_until(lambda: line.entered == ["a"])
    left = threading.Event()
    errors: list[Exception] = []

    def ask_twice(job: Job[None]) -> None:
        def ask_again(_place: int) -> None:
            with line.slots.slot(job):
                pass

        try:
            with line.slots.slot(job, on_wait=ask_again):
                pass
        finally:
            left.set()

    line.main_view.jobs.start(ask_twice).failed.connect(errors.append)
    # "a" holds the slot until then: without the check, the job would wait behind itself
    assert left.wait(_TIMEOUT)
    line.end()

    assert len(errors) == 1
    assert "already holds or waits for a slot" in str(errors[0])


def test_a_slot_is_taken_only_in_its_job_s_thread() -> None:
    slots = JobSlots(1)
    main_view = MainView()
    job = main_view.jobs.start(lambda _job: None)
    main_view.jobs.wait(_TIMEOUT)

    with pytest.raises(RuntimeError, match="in its thread"), slots.slot(job):
        pass


def test_a_limit_below_one_is_refused() -> None:
    with pytest.raises(ValueError, match="1 or more"):
        JobSlots(0)

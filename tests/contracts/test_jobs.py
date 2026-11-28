"""The rules of the jobs on every backend: what the backend's main thread runs for them."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import pytest

from composeui.core.view import MainView

if TYPE_CHECKING:
    from composeui.core.jobs import Job
    from tests.contracts.support import Driver


@pytest.mark.asyncio
async def test_a_repeating_task_runs_again_and_keeps_its_result_until_the_next_run(
    driver: Driver,
) -> None:
    main_view = MainView()
    runs: list[int] = []
    second_run, release = threading.Event(), threading.Event()

    def work(_job: Job[int], start: int) -> int:
        runs.append(start)  # one run at a time: in the order they ran
        if len(runs) == 2:
            second_run.set()
            assert release.wait(10)
        return start + len(runs)

    task = main_view.jobs.task(work, every=0.05)
    try:
        async with driver.open(main_view):
            async with driver.by_code():
                task.start(10)
            # the timer posts the next run to the backend's main thread, which starts it
            await driver.wait_until(second_run.is_set)

            assert task.is_running
            assert task.result == 11  # the run before's, until this one's outcome

            async with driver.by_code():
                release.set()
            await driver.wait_until(lambda: task.result == 12)
            async with driver.by_code():
                task.cancel()
            await driver.wait_until(lambda: not task.is_running)

            assert not task.is_repeating
            assert runs[:2] == [10, 10]  # again with its arguments
    finally:
        release.set()

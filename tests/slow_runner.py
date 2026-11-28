"""Run the tests as a slow CI runner would: what a test races comes late, every time.

A test that waits for another clock by a fixed count of pauses, or reads a value that later
work replaces, passes on a fast machine and fails now and then on a slow runner (Windows with
Python 3.9). `pytest --slow-runner=<lateness>` makes one side of the race late each time, so
such a test fails at once, on any machine (`make slow-test` runs each lateness in turn):

- ``steps``: the test itself, after each of its Textual pauses, while the app's threads and
  timers go on;
- ``threads``: every thread, which starts its work late, as a busy machine runs it;
- ``timers``: every Textual timer (the screen's refresh, a button's press, a typing delay).

Qt's own timers aren't slowed: Qt runs them in C++.
"""

from __future__ import annotations

import asyncio
import importlib.util
import threading
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pytest

#: how late each lateness makes its side of the race, in seconds: longer than the waits of a
#: fast machine, shorter than the tests' 10 s bounded waits
LATENESS = {"steps": 0.05, "threads": 0.3, "timers": 0.3}


def make_late(lateness: str, patch: pytest.MonkeyPatch) -> None:
    """Make the side of the race that `lateness` names late, until `patch` is undone."""
    delay = LATENESS[lateness]
    if lateness == "threads":
        start_work = threading.Thread.run

        def run(self: threading.Thread) -> None:
            time.sleep(delay)
            start_work(self)

        patch.setattr(threading.Thread, "run", run)
        return
    if importlib.util.find_spec("textual") is None:
        return  # no Textual test to slow: they skip without the extra
    from textual.pilot import Pilot  # noqa: PLC0415 (an optional dependency)
    from textual.timer import Timer  # noqa: PLC0415 (an optional dependency)

    if lateness == "steps":
        pause = Pilot.pause

        async def late_pause(self: Pilot[Any], wait: float | None = None) -> None:
            await pause(self, wait)
            await asyncio.sleep(delay)
            await pause(self)  # what the app's loop did meanwhile, handled

        patch.setattr(Pilot, "pause", late_pause)
    else:
        make_timer = Timer.__init__

        def late_timer(self: Timer, event_target: Any, interval: float, **kwargs: Any) -> None:
            make_timer(self, event_target, interval + delay, **kwargs)

        patch.setattr(Timer, "__init__", late_timer)

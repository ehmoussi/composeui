"""Settings shared by the tests."""

from __future__ import annotations

import gc
import os
from typing import TYPE_CHECKING

import pytest
from hypothesis import settings

if TYPE_CHECKING:
    from collections.abc import Iterator

# no time limit per example: a loaded or slow runner (`make test`'s workers, Windows CI on
# Python 3.9) takes longer than Hypothesis's 200 ms, which fails a correct property
settings.register_profile("composeui", settings.get_profile("default"), deadline=None)
# on CI, Hypothesis's own profile: the same examples each run (`derandomize`), without a
# time limit, so that a pull request fails for its change, not for a new random draw
settings.load_profile("ci" if os.environ.get("CI") else "composeui")


@pytest.fixture(autouse=True)
def collect_garbage_on_the_main_thread() -> Iterator[None]:
    """Collect once each test is over, here, and never on the thread of a job.

    PySide can crash when another thread collects a main view that a test dropped: a
    `QMainWindow` and its `QToolBar` are enough. It deletes them later, on the main thread, and
    a worker dies with a segmentation fault wherever that thread is. This was 1 run in 25.
    """
    gc.disable()
    yield
    gc.collect()

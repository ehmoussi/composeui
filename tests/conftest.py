"""Settings shared by the tests."""

from __future__ import annotations

import gc
import importlib.util
import os
from typing import TYPE_CHECKING, NoReturn

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

#: whether the pyside6 extra is installed: else pytest-qt can't start (run pytest with
#: `-p no:pytest-qt`), and no Qt test can run
HAS_QT = importlib.util.find_spec("PySide6") is not None
#: the folders whose every test needs an extra that isn't installed
collect_ignore_glob = [] if HAS_QT else ["qtcore/*"]

if not HAS_QT:

    @pytest.fixture
    def qtbot() -> NoReturn:
        """Skip a Qt test, as pytest-qt's own fixture would need Qt."""
        # ty misbinds pytest's decorated helpers; the public exception keeps the outcome
        reason = "Qt isn't installed: the pyside6 extra"
        raise pytest.skip.Exception(reason)


@pytest.fixture(autouse=True)
def collect_garbage_on_the_main_thread() -> Iterator[None]:
    """Collect once each test is over, here, and never on the thread of a job.

    PySide can crash when another thread collects a main view that a test dropped: a
    `QMainWindow` and its `QToolBar` are enough. It deletes them later, on the main thread, and
    a worker dies with a segmentation fault wherever that thread is. This was 1 run in 25.

    The objects left are frozen: the next collection skips them. A full collection of a worker's
    whole heap took about 450 ms, 70% of the suite's time; one of only the last test's objects
    takes a few milliseconds.
    """
    gc.disable()
    yield
    gc.collect()
    gc.freeze()

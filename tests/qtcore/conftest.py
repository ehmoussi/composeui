"""Fixtures shared by the Qt tests."""

from __future__ import annotations

import gc
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(autouse=True)
def _collect_between_tests() -> Iterator[None]:
    """Destroy the windows tests leave to the garbage collector only between tests.

    Collected while pyqtgraph paints (its items paint in Python, where a collection can
    run), a window's widgets die under a painter, which crashes.
    """
    gc.collect()
    gc.disable()
    yield
    gc.enable()
    gc.collect()

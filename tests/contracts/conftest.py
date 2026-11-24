"""The `driver` fixture: each test of this folder runs on each backend."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from tests.contracts.support import Driver


@pytest.fixture(params=["qt", "textual", "web"])
def driver(request: pytest.FixtureRequest) -> Driver:
    if request.param == "qt":
        pytest.importorskip("qtpy")
        from tests.contracts.qtdriver import QtDriver  # noqa: PLC0415 (its backend only)

        return QtDriver(request.getfixturevalue("qtbot"))
    if request.param == "textual":
        pytest.importorskip("textual")
        pytest.importorskip("textual_fspicker")
        from tests.contracts.textualdriver import TextualDriver  # noqa: PLC0415 (its backend only)

        return TextualDriver()
    pytest.importorskip("starlette")
    # Starlette's test client: httpx2, which needs Python 3.11, or httpx before it
    pytest.importorskip("httpx2" if sys.version_info >= (3, 11) else "httpx")
    from tests.contracts.webdriver import WebDriver  # noqa: PLC0415 (its backend only)

    return WebDriver()

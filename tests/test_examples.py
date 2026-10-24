"""Tests for the example apps as programs: each starts as the examples guide says."""

from __future__ import annotations

import importlib
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from composeui.core.application import BACKEND_VARIABLE
from composeui.core.registry import RendererType
from examples.webhello import HelloMainView

if TYPE_CHECKING:
    from collections.abc import Iterator

_GUIDE = Path(__file__).parent.parent / "docs" / "examples-guide.md"


def _guide_backends() -> Iterator[tuple[str, str]]:
    """Get each example's module and default backend, as the guide's overview lists them."""
    overview = _GUIDE.read_text(encoding="utf-8").split("## Overview", 1)[1].split("\n## ", 1)[0]
    for match in re.finditer(
        r"^\| \[`(\w+)\.py`\]\([^)]*\) \| ([\w ]+) \|", overview, re.MULTILINE
    ):
        yield match[1], match[2].removesuffix(" only")  # "web only": `WebApplication`


@pytest.mark.parametrize(("module", "backend"), list(_guide_backends()))
def test_each_example_starts_on_the_backend_the_examples_guide_lists(
    module: str, backend: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    started: list[tuple[str, Any]] = []
    for renderer_type in RendererType:
        applications = pytest.importorskip(renderer_type.value.applications)
        name = renderer_type.name.lower()
        for application in (applications.APPLICATION, applications.MODEL_APPLICATION):
            # the app's own loop is out of scope: which backend starts it is the point
            monkeypatch.setattr(
                application, "run", lambda app, name=name: started.append((name, app))
            )
    monkeypatch.setattr("sys.argv", [module])  # no --backend: the example's default
    monkeypatch.setenv(BACKEND_VARIABLE, "")
    monkeypatch.delenv(BACKEND_VARIABLE)

    importlib.import_module(f"examples.{module}").main()

    ((name, app),) = started
    model = getattr(app, "model", None)
    if model is not None:
        model.close()
    assert name == backend


def test_the_hello_app_s_age_may_be_left_empty() -> None:
    age = HelloMainView().form.age
    age.text = "12"
    age.run_validator()

    age.text = ""  # cleared by the user
    age.run_validator()

    assert age.log_message == ""

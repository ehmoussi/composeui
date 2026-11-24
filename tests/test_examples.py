"""Tests for the example apps as programs: each starts as the examples guide says."""

from __future__ import annotations

import importlib
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from composeui.core.application import BACKEND_VARIABLE, Application
from composeui.core.registry import RendererType
from examples.studyinputs import PATH, StudyInputsMainView

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
    hello = pytest.importorskip("examples.webhello")  # a web app: the web extra
    age = hello.HelloMainView().form.age
    age.value = 12.0
    age.run_validator()

    age.value = None  # cleared by the user
    age.run_validator()

    assert age.log_message == ""


def test_the_study_inputs_read_their_paths_from_the_study_on_the_command_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.argv", ["studyinputs", "--study", str(tmp_path)])
    app = Application(build_main_view=StudyInputsMainView)
    app.run()
    files = app.main_view.files
    widget = files.cell_widget(0, PATH)
    assert widget is not None
    assert widget.path(files.rows[0][PATH]) == tmp_path / "inputs" / "mesh.med"
    # without it: from the folder the app started in
    monkeypatch.chdir(tmp_path / "..")
    monkeypatch.setattr("sys.argv", ["studyinputs"])
    app = Application(build_main_view=StudyInputsMainView)
    app.run()
    files = app.main_view.files
    widget = files.cell_widget(0, PATH)
    assert widget is not None
    assert widget.start_folder() == Path.cwd()

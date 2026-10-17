"""Tests for `run`, starting an app on the backend the command line names."""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

import pytest

from composeui.core.application import BACKEND_VARIABLE, Application, run
from composeui.core.model import Model
from composeui.core.registry import RendererType
from composeui.core.view import MainView, define_view

if TYPE_CHECKING:
    import argparse
    from pathlib import Path


@define_view
class _CountMainView(MainView):
    app_title = "Count"
    extension = ".count"


@define_view
class _StartMainView(MainView):
    """An app with an option of its own: the count it starts from."""

    app_title = "Start"
    extension = ".start"

    start: int = 0
    #: the study's count when the option applied; -1 until then
    count_then: int = -1

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--start", type=int, default=1, help="Count from START.")

    def apply_arguments(self, args: argparse.Namespace) -> None:
        self.count_then = self.start
        self.start = args.start


@pytest.mark.parametrize(
    ("arguments", "default_backend", "backend", "rest"),
    [
        (
            ["--backend", "qt", "-f", "a.count"],
            RendererType.WEB,
            RendererType.QT,
            ["-f", "a.count"],
        ),
        (
            ["--language", "fr", "--backend=textual"],
            RendererType.WEB,
            RendererType.TEXTUAL,
            ["--language", "fr"],
        ),
        (["--port", "8001"], RendererType.WEB, RendererType.WEB, ["--port", "8001"]),
        ([], RendererType.TEXTUAL, RendererType.TEXTUAL, []),
    ],
)
def test_run_starts_the_backend_the_command_line_names(
    arguments: list[str],
    default_backend: RendererType,
    backend: RendererType,
    rest: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started: list[tuple[Application[_CountMainView], list[str]]] = []

    def record(app: Application[_CountMainView]) -> None:
        # what the app would parse
        started.append((app, sys.argv[1:]))

    applications = {
        renderer_type: pytest.importorskip(renderer_type.value.applications).MODEL_APPLICATION
        for renderer_type in RendererType
    }
    for application in applications.values():
        monkeypatch.setattr(application, "run", record)
    monkeypatch.setattr("sys.argv", ["count", *arguments])
    monkeypatch.delenv(BACKEND_VARIABLE, raising=False)

    run(_CountMainView, build_model=Model, default_backend=default_backend)

    ((app, app_arguments),) = started
    assert type(app) is applications[backend]
    assert app_arguments == rest
    # for a process the app starts again, e.g. the web's `--reload` server
    assert os.environ[BACKEND_VARIABLE] == backend.name.lower()


@pytest.mark.parametrize(
    ("arguments", "variable", "backend"),
    [
        # a process started again: the command line lost `--backend`
        (["--reload"], "web", RendererType.WEB),
        (["--backend", "textual"], "web", RendererType.TEXTUAL),  # the command line wins
        ([], "neither", RendererType.QT),  # not a backend: the default
    ],
)
def test_run_without_backend_starts_the_one_its_environment_names(
    arguments: list[str],
    variable: str,
    backend: RendererType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started: list[Application[_CountMainView]] = []

    def record(app: Application[_CountMainView]) -> None:
        started.append(app)

    applications = {
        renderer_type: pytest.importorskip(renderer_type.value.applications).APPLICATION
        for renderer_type in RendererType
    }
    for application in applications.values():
        monkeypatch.setattr(application, "run", record)
    monkeypatch.setattr("sys.argv", ["count", *arguments])
    monkeypatch.setenv(BACKEND_VARIABLE, variable)

    run(_CountMainView, default_backend=RendererType.QT)

    (app,) = started
    assert type(app) is applications[backend]


def test_an_app_s_own_options_apply_once_its_study_is_open(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    study = _StartMainView(start=7)
    state_file = tmp_path / "a.start"
    study.save_state(state_file)
    monkeypatch.setattr("sys.argv", ["start", "-f", str(state_file), "--start", "3"])
    app = Application(build_main_view=_StartMainView)

    app.run()

    assert (app.main_view.count_then, app.main_view.start) == (7, 3)


def test_an_app_s_own_options_are_in_its_help(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.argv", ["start", "--help"])
    with pytest.raises(SystemExit):
        Application(build_main_view=_StartMainView).run()
    help_text = capsys.readouterr().out
    assert "[--start START]" in help_text
    assert "Count from START." in help_text


def test_run_refuses_to_set_up_a_model_it_isn_t_given() -> None:
    with pytest.raises(ValueError, match="build_model"):
        run(_CountMainView, setup_model=lambda _main_view, _model: None)

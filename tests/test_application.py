"""Tests for `run`, starting an app on the backend the command line names."""

from __future__ import annotations

import sys

import pytest

from composeui.core.application import Application, run
from composeui.core.model import Model
from composeui.core.registry import RendererType
from composeui.core.view import MainView, define_view


@define_view
class _CountMainView(MainView):
    app_title = "Count"
    extension = ".count"


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

    run(_CountMainView, build_model=Model, default_backend=default_backend)

    ((app, app_arguments),) = started
    assert type(app) is applications[backend]
    assert app_arguments == rest


def test_run_refuses_to_set_up_a_model_it_isn_t_given() -> None:
    with pytest.raises(ValueError, match="build_model"):
        run(_CountMainView, setup_model=lambda _main_view, _model: None)

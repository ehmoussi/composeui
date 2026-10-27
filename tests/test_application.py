"""Tests for `run`, starting an app on the backend the command line names."""

from __future__ import annotations

import logging
import os
import sys
from typing import TYPE_CHECKING

import attrs
import pytest

from composeui.core.application import BACKEND_VARIABLE, Application, ModelApplication, run
from composeui.core.model import Model
from composeui.core.registry import RendererType
from composeui.core.study import save_study
from composeui.core.view import ButtonView, MainView, define_view

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


def test_run_without_its_backend_s_extra_names_the_extra(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    applications = pytest.importorskip(RendererType.WEB.value.applications).__name__
    # imported again, as in an environment without the extra
    monkeypatch.delitem(sys.modules, applications)
    monkeypatch.setitem(sys.modules, "uvicorn", None)
    monkeypatch.setattr("sys.argv", ["count", "--backend", "web"])
    monkeypatch.delenv(BACKEND_VARIABLE, raising=False)

    with pytest.raises(SystemExit) as stopped:
        run(_CountMainView)

    assert stopped.value.code == 2
    assert 'needs uvicorn, from the web extra: pip install "composeui[web]"' in (
        capsys.readouterr().err
    )


def test_run_shows_an_import_error_of_a_backend_whose_extra_is_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    applications = pytest.importorskip(RendererType.WEB.value.applications).__name__
    monkeypatch.delitem(sys.modules, applications)
    # e.g. a bug in the backend's own code
    monkeypatch.setitem(sys.modules, "composeui.webcore.session", None)
    monkeypatch.setattr("sys.argv", ["count", "--backend", "web"])
    monkeypatch.delenv(BACKEND_VARIABLE, raising=False)

    with pytest.raises(ImportError, match=r"composeui\.webcore\.session"):
        run(_CountMainView)


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


@pytest.mark.parametrize(
    ("option", "app_level", "signal_level"),
    [
        ("--log", logging.DEBUG, logging.INFO),
        ("--log-signals", logging.INFO, logging.DEBUG),
        ("--debug", logging.DEBUG, logging.DEBUG),
    ],
)
def test_the_log_options_show_the_app_s_or_the_signals_debug_messages(
    option: str, app_level: int, signal_level: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    loggers = [logging.getLogger("COMPOSEUI"), logging.getLogger("COMPOSEUI_SIGNAL")]
    for logger in loggers:
        monkeypatch.setattr(logger, "level", logger.level)  # for the other tests
    monkeypatch.setattr("sys.argv", ["count", option])

    Application(build_main_view=_CountMainView).run()

    assert [logger.level for logger in loggers] == [app_level, signal_level]


def test_a_file_of_another_app_is_refused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    other = tmp_path / "a.start"
    _StartMainView().save_state(other)
    monkeypatch.setattr("sys.argv", ["count", "-f", str(other)])

    with pytest.raises(ValueError, match=r"Invalid file extension: '\.start'"):
        Application(build_main_view=_CountMainView).run()


class _NotesModel(Model):
    """A model with data of its own, saved in the study beside the views' state."""

    data_name = "notes.txt"

    def __init__(self) -> None:
        self.notes = ""

    def save_data(self, path: Path) -> None:
        path.write_text(self.notes)

    def open_data(self, path: Path) -> None:
        self.notes = path.read_text()


def test_a_model_app_opens_the_model_s_data_of_its_study(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    model = _NotesModel()
    model.notes = "kept"
    study = tmp_path / "a.count"
    save_study(_CountMainView(), model, study)
    monkeypatch.setattr("sys.argv", ["count", "-f", str(study)])
    app = ModelApplication(build_main_view=_CountMainView, build_model=_NotesModel)

    app.run()

    assert app.model.notes == "kept"


@define_view
class _ButtonMainView(MainView):
    button: ButtonView = attrs.Factory(ButtonView)


def test_a_model_app_s_connect_gives_the_view_main_view_and_model_asked_for() -> None:
    app = ModelApplication(build_main_view=_ButtonMainView, build_model=Model)
    button = app.main_view.button
    given: list[tuple[object, ...]] = []

    @app.connect(view=button, signals=[button.clicked])
    def everything(*, view: ButtonView, main_view: _ButtonMainView, model: Model) -> None:
        given.append((view, main_view, model))

    @app.connect(view=button, signals=[button.clicked])
    def only_the_model(*, model: Model) -> None:
        given.append((model,))

    button.clicked.emit()

    assert [[id(value) for value in values] for values in given] == [
        [id(button), id(app.main_view), id(app.model)],
        [id(app.model)],
    ]


class _UnreadableCallback:
    """A callback whose signature can't be read, like some builtins'."""

    __signature__ = "unreadable"

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> None:
        self.calls += 1


@pytest.mark.parametrize("application", [Application, ModelApplication])
def test_a_callback_whose_signature_can_t_be_read_is_called_without_arguments(
    application: type[Application[_ButtonMainView]],
) -> None:
    app: Application[_ButtonMainView]
    if issubclass(application, ModelApplication):
        app = application(build_main_view=_ButtonMainView, build_model=Model)
    else:
        app = application(build_main_view=_ButtonMainView)
    button = app.main_view.button
    callback = _UnreadableCallback()
    app.connect(view=button, signals=[button.clicked])(callback)

    button.clicked.emit()

    assert callback.calls == 1

"""Tests for `run`, starting an app on the backend the command line names."""

from __future__ import annotations

import io
import logging
import os
import subprocess
import sys
import textwrap
from typing import TYPE_CHECKING

import attrs
import pytest

from composeui.core.application import (
    BACKEND_VARIABLE,
    Application,
    ModelApplication,
    _LogFile,
    check_writable,
    current_backend,
    get_logger,
    logs_in_file,
    renders,
    run,
)
from composeui.core.model import Model
from composeui.core.registry import RendererType
from composeui.core.study import save_study
from composeui.core.view import (
    ButtonView,
    FileView,
    LabelRowInputView,
    MainView,
    MapView,
    define_view,
)

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


@pytest.mark.parametrize("kind", ["APPLICATION", "MODEL_APPLICATION"])
@pytest.mark.parametrize("backend", list(RendererType))
def test_the_views_an_app_builds_see_its_backend_and_the_views_it_shows(
    backend: RendererType, kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    application = getattr(pytest.importorskip(backend.value.applications), kind)
    monkeypatch.setattr("composeui.core.application._Running.backend", None)
    seen: list[tuple[RendererType | None, bool, bool, bool]] = []

    def build_main_view() -> MainView:
        # as a main view's own fields are built
        seen.append(
            (current_backend(), renders(MapView), renders(LabelRowInputView), renders(FileView))
        )
        return MainView()

    if kind == "APPLICATION":
        application(build_main_view=build_main_view)
    else:
        application(build_main_view=build_main_view, build_model=Model)

    # a map on Qt and the web only; a form row everywhere; a file dialog's view nowhere
    assert seen == [(backend, backend is not RendererType.TEXTUAL, True, False)]


def test_before_an_app_is_built_there_is_no_backend_and_no_view_shows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("composeui.core.application._Running.backend", None)

    assert current_backend() is None
    assert not renders(LabelRowInputView)


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


@pytest.mark.parametrize("with_study", [False, True])
def test_an_app_emits_loaded_once_as_it_starts_with_or_without_a_study(
    with_study: bool, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    argv = ["start"]
    if with_study:
        state_file = tmp_path / "a.start"
        _StartMainView(start=7).save_state(state_file)
        argv += ["-f", str(state_file)]
    monkeypatch.setattr("sys.argv", argv)
    app = Application(build_main_view=_StartMainView)
    starts: list[int] = []
    app.main_view.loaded.connect(lambda: starts.append(app.main_view.start))

    app.run()

    assert starts == [7 if with_study else 0]  # once, with the study in place


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


@pytest.mark.parametrize(("options", "is_shown"), [(["--log"], True), ([], False)])
def test_an_app_s_logger_shows_its_debug_messages_with_the_log_option(
    options: list[str],
    is_shown: bool,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = logging.getLogger("COMPOSEUI")
    monkeypatch.setattr(logger, "level", logger.level)  # for the other tests
    monkeypatch.setattr("sys.argv", ["count", *options])
    Application(build_main_view=_CountMainView).run()

    get_logger("count").debug("The count is ready")

    assert ("The count is ready" in caplog.text) is is_shown


_LOGGING_TEXTUAL_APP = textwrap.dedent(
    """
    from composeui.core.application import get_logger
    from composeui.core.view import MainView, define_view
    from composeui.textualcore.textualapplication import TextualApplication

    LOGGER = get_logger("count")

    @define_view
    class CountMainView(MainView):
        app_title = "Count"

    class LoggingApplication(TextualApplication):
        def render(self, renderer_type):
            LOGGER.info("before the app")
            super().render(renderer_type)
            app = self.main_view.renderer.app
            def log_and_exit():
                LOGGER.info("while shown")
                app.exit()
            app.mounted_callbacks.append(log_and_exit)

    LoggingApplication(build_main_view=CountMainView).run()
    LOGGER.info("after the app")
    """
)


def _run_logging_textual_app(
    cwd: Path, *options: str, check: bool = True
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [sys.executable, "-c", _LOGGING_TEXTUAL_APP, *options],
        cwd=cwd,
        env={
            **os.environ,
            # no terminal here
            "TEXTUAL_DRIVER": "textual.drivers.headless_driver:HeadlessDriver",
        },
        capture_output=True,
        text=True,
        timeout=60,
        check=check,
    )


@pytest.mark.parametrize(
    ("options", "name"),
    [([], "composeui.log"), (["--log-file", "other.log"], "other.log")],
)
def test_a_textual_app_writes_its_log_to_a_file_only_while_it_is_shown(
    options: list[str], name: str, tmp_path: Path
) -> None:
    pytest.importorskip("textual")

    result = _run_logging_textual_app(tmp_path, *options)

    log = (tmp_path / name).read_text(encoding="utf-8")
    assert "while shown" in log
    assert "before the app" not in log
    assert "after the app" not in log
    assert "before the app" in result.stdout
    assert "while shown" not in result.stdout
    assert "after the app" in result.stdout
    assert f"Log messages written to {tmp_path / name}" in result.stdout


def test_a_log_file_is_created_and_named_only_after_a_first_message(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "app.log"

    with caplog.at_level(logging.INFO, logger="COMPOSEUI"), logs_in_file(path):
        pass

    assert not path.exists()
    assert "Log messages written" not in caplog.text


def test_a_log_file_keeps_only_its_previous_content_when_it_grows(tmp_path: Path) -> None:
    path = tmp_path / "app.log"
    logger = get_logger("count")

    with logs_in_file(path):
        for letter in "abc":
            logger.warning(letter * 6_000_000)

    assert "c" * 100 in path.read_text(encoding="utf-8")
    assert "b" * 100 in (tmp_path / "app.log.1").read_text(encoding="utf-8")
    assert not (tmp_path / "app.log.2").exists()


@pytest.mark.parametrize("name", ["COMPOSEUI", "COMPOSEUI_SIGNAL", "COMPOSEUI_VIEW"])
def test_each_composeui_log_goes_to_the_file_until_the_code_raises(
    name: str, tmp_path: Path
) -> None:
    logger = logging.getLogger(name)
    path = tmp_path / "app.log"

    def log_and_stop() -> None:
        with logs_in_file(path):
            logger.warning("inside the block")
            raise ValueError("stop")  # noqa: EM101

    with pytest.raises(ValueError, match="stop"):
        log_and_stop()
    logger.warning("after the block")

    log = path.read_text(encoding="utf-8")
    assert "inside the block" in log
    assert "after the block" not in log


def test_a_log_file_that_cannot_be_opened_does_not_stop_the_code_that_logs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with logs_in_file(tmp_path / "missing" / "app.log"):
        get_logger("count").warning("Nowhere to write")

    assert "Nowhere to write" in capsys.readouterr().err  # logging reports the failed message


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


def test_a_textual_app_refuses_a_log_file_it_cannot_write(tmp_path: Path) -> None:
    pytest.importorskip("textual")

    result = _run_logging_textual_app(tmp_path, "--log-file", "missing/app.log", check=False)

    assert result.returncode == 2
    assert "--log-file" in result.stderr
    assert "while shown" not in result.stdout


def test_a_textual_app_runs_and_warns_when_its_default_log_file_cannot_be_written(
    tmp_path: Path,
) -> None:
    pytest.importorskip("textual")
    (tmp_path / "composeui.log").mkdir()  # no file can be opened at this path

    result = _run_logging_textual_app(tmp_path)

    assert "No log file while the app is shown" in result.stdout
    assert "while shown" not in result.stdout.replace("No log file while the app is shown", "")
    assert "after the app" in result.stdout
    assert "Log messages written" not in result.stdout


def test_checking_a_log_file_leaves_no_new_file_and_keeps_an_existing_one(tmp_path: Path) -> None:
    new = tmp_path / "new.log"
    existing = tmp_path / "existing.log"
    existing.write_text("kept", encoding="utf-8")

    check_writable(new)
    check_writable(existing)

    assert not new.exists()
    assert existing.read_text(encoding="utf-8") == "kept"


def _log_record(message: str) -> logging.LogRecord:
    return logging.LogRecord("count", logging.WARNING, __file__, 0, message, None, None)


def test_a_message_logged_as_the_block_ends_goes_to_the_output_without_reopening_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    logger = logging.getLogger("COMPOSEUI")
    stream_handler = logger.handlers[0]
    output = io.StringIO()
    monkeypatch.setattr(stream_handler, "stream", output)
    path = tmp_path / "app.log"

    with logs_in_file(path):
        log_file = next(handler for handler in logger.handlers if handler is not stream_handler)
    log_file.handle(_log_record("late message"))  # as a thread past the handlers' list does

    assert "late message" in output.getvalue()
    assert not path.exists()


def _small_log_file(path: Path) -> _LogFile:
    return _LogFile(path, maxBytes=50, backupCount=1, encoding="utf-8", delay=True)


@pytest.mark.skipif(sys.platform == "win32", reason="Windows can't rename a file left open")
def test_two_apps_sharing_a_log_file_keep_each_other_s_messages_when_it_rotates(
    tmp_path: Path,
) -> None:
    path = tmp_path / "app.log"
    first, second = _small_log_file(path), _small_log_file(path)

    for number in range(4):
        first.handle(_log_record(f"A{number}{'x' * 20}"))
        second.handle(_log_record(f"B{number}{'x' * 20}"))
    first.close()
    second.close()

    def names(file: Path) -> list[str]:
        return [line[:2] for line in file.read_text(encoding="utf-8").split()]

    # which of the two files holds each one depends on the version of Python
    assert {"A2", "B2", "A3", "B3"} <= {*names(path), *names(tmp_path / "app.log.1")}


@pytest.mark.skipif(sys.platform == "win32", reason="Windows can't delete a file left open")
def test_a_log_file_deleted_while_in_use_is_created_again_when_it_is_full(tmp_path: Path) -> None:
    path = tmp_path / "app.log"
    log_file = _small_log_file(path)
    log_file.handle(_log_record("x" * 60))
    path.unlink()

    log_file.handle(_log_record("after the deletion"))
    log_file.close()

    assert "after the deletion" in path.read_text(encoding="utf-8")


def test_a_log_file_that_another_app_keeps_open_goes_on_without_rotating(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "app.log"
    log_file = _small_log_file(path)

    def refuse(_source: str, _destination: str) -> None:
        raise PermissionError  # what Windows does

    monkeypatch.setattr(log_file, "rotate", refuse)
    for message in ("first" + "x" * 60, "second"):
        log_file.handle(_log_record(message))
    log_file.close()

    log = path.read_text(encoding="utf-8")
    assert "first" in log
    assert "second" in log

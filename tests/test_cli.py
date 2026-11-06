"""Tests for the ``composeui`` command: ``composeui run app.py``."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from composeui.cli import main
from composeui.core.application import _Running, current_backend
from composeui.core.registry import RendererType
from composeui.core.reload import rerun_program

if TYPE_CHECKING:
    from collections.abc import Callable

#: seconds a test waits for a child process before failing
_TIMEOUT = 30.0

#: a file with one main view, and no `run`
_APP = textwrap.dedent(
    """
    from __future__ import annotations

    from composeui.core.view import LabelView, MainView, child, define_view

    @define_view
    class HelloMainView(MainView):
        label: LabelView = child(LabelView, text="version one")
    """
)


def _keep_the_process(monkeypatch: pytest.MonkeyPatch) -> None:
    """Restore, after the test, what `main` changes in this process."""
    monkeypatch.setitem(sys.modules, "__main__", sys.modules["__main__"])
    monkeypatch.setattr("sys.path", list(sys.path))
    monkeypatch.setattr(_Running, "backend", None)
    monkeypatch.delenv("COMPOSEUI_BACKEND", raising=False)
    monkeypatch.delenv("COMPOSEUI_APP_FILE", raising=False)


@pytest.fixture
def started(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, list[str]]]:
    """Record the web apps that `main` starts, from the test's directory."""
    web = pytest.importorskip("composeui.webcore.webapplication")
    monkeypatch.chdir(tmp_path)
    _keep_the_process(monkeypatch)
    apps: list[tuple[Any, list[str]]] = []

    def record(app: object) -> None:
        apps.append((app, list(sys.argv)))

    monkeypatch.setattr(web.WebApplication, "run", record)
    monkeypatch.setattr(web.WebModelApplication, "run", record)
    return apps


@pytest.fixture
def composeui(monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    """Get a function that runs the command with the arguments that it gets."""

    def run_command(*arguments: str) -> None:
        monkeypatch.setattr("sys.argv", ["composeui", *arguments])
        main()

    return run_command


@pytest.mark.parametrize(("options", "reload_options"), [([], ["--reload"]), (["--no-reload"], [])])
def test_a_file_without_run_starts_its_own_main_view_with_the_arguments_after_it(
    options: list[str],
    reload_options: list[str],
    started: list[tuple[Any, list[str]]],
    tmp_path: Path,
    composeui: Callable[..., None],
) -> None:
    # a view that the file imports, here from a file beside it, isn't the file's own
    (tmp_path / "_cli_neighbour.py").write_text(
        "from composeui.core.view import MainView, define_view\n"
        "@define_view\n"
        "class BaseMainView(MainView): ...\n"
    )
    app_file = tmp_path / "app.py"
    app_file.write_text(_APP + "from _cli_neighbour import BaseMainView\n")

    composeui("run", *options, "app.py", "--port", "8001")

    ((app, argv),) = started
    assert type(app.main_view).__name__ == "HelloMainView"
    assert app.main_view.label.text == "version one"
    assert argv == [str(app_file.resolve()), "--port", "8001", *reload_options]


def test_a_file_that_calls_run_starts_the_app_it_names_once(
    started: list[tuple[Any, list[str]]], tmp_path: Path, composeui: Callable[..., None]
) -> None:
    web = pytest.importorskip("composeui.webcore.webapplication")
    (tmp_path / "app.py").write_text(
        _APP
        + textwrap.dedent(
            """
            from composeui.core.application import run
            from composeui.core.model import Model

            @define_view
            class OtherMainView(MainView): ...

            if __name__ == "__main__":
                run(OtherMainView, build_model=Model)
            """
        )
    )

    composeui("run", "app.py")

    ((app, _),) = started
    assert type(app.main_view).__name__ == "OtherMainView"
    assert isinstance(app, web.WebModelApplication)


@pytest.mark.parametrize(
    ("code", "message"),
    [
        ("count = 1\n", "app.py defines no MainView class and starts no app"),
        (
            "from composeui.core.view import MainView, define_view\n"
            "@define_view\n"
            "class First(MainView): ...\n"
            "@define_view\n"
            "class Second(MainView): ...\n",
            "app.py defines several MainView classes (First, Second)",
        ),
    ],
)
def test_a_file_without_one_main_view_stops_the_command_and_says_why(
    code: str,
    message: str,
    started: list[tuple[Any, list[str]]],
    tmp_path: Path,
    composeui: Callable[..., None],
) -> None:
    (tmp_path / "app.py").write_text(code)

    with pytest.raises(SystemExit) as stopped:
        composeui("run", "app.py")

    assert message in str(stopped.value.code)  # `sys.exit` with the text, which Python prints
    assert started == []


def test_a_missing_file_stops_the_command_and_says_why(
    started: list[tuple[Any, list[str]]],
    composeui: Callable[..., None],
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        composeui("run", "app.py")

    assert "no such file: app.py" in capsys.readouterr().err
    assert started == []


def test_the_help_after_the_file_lists_the_app_s_options(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    composeui: Callable[..., None],
    capsys: pytest.CaptureFixture[str],
) -> None:
    pytest.importorskip("composeui.webcore.webapplication")
    _keep_the_process(monkeypatch)
    app_file = tmp_path / "app.py"
    app_file.write_text(_APP)

    with pytest.raises(SystemExit) as stopped:
        composeui("run", str(app_file), "--help")

    assert stopped.value.code == 0
    assert "--port" in capsys.readouterr().out  # an option of the web's app


def test_only_a_file_outside_the_current_directory_warns_that_it_won_t_reload(
    started: list[tuple[Any, list[str]]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    composeui: Callable[..., None],
    caplog: pytest.LogCaptureFixture,
) -> None:
    (tmp_path / "other").mkdir()
    app_file = tmp_path / "app.py"
    app_file.write_text(_APP)

    with caplog.at_level(logging.WARNING, logger="COMPOSEUI"):
        composeui("run", str(app_file))
        assert "it won't reload" not in caplog.text
        monkeypatch.chdir(tmp_path / "other")
        composeui("run", str(app_file))

    assert len(started) == 2
    assert "it won't reload" in caplog.text


def test_a_running_app_keeps_its_backend_when_the_changed_code_fails(
    started: list[tuple[Any, list[str]]], tmp_path: Path, composeui: Callable[..., None]
) -> None:
    app_file = tmp_path / "app.py"
    app_file.write_text(_APP)
    composeui("run", "app.py")
    assert len(started) == 1
    assert current_backend() is RendererType.WEB

    app_file.write_text("raise ValueError('the changed code')\n")
    with pytest.raises(ValueError, match="the changed code"):
        rerun_program()

    assert current_backend() is RendererType.WEB


def test_a_web_server_s_new_process_runs_the_file_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, composeui: Callable[..., None]
) -> None:
    pytest.importorskip("composeui.webcore.webapplication")
    testclient = pytest.importorskip("starlette.testclient")
    uvicorn_importer = pytest.importorskip("uvicorn.importer")
    monkeypatch.chdir(tmp_path)
    _keep_the_process(monkeypatch)
    for variable in (  # that `run` sets for the server's process
        "COMPOSEUI_WEB_ENTRY",
        "COMPOSEUI_WEB_SAVED_SESSIONS",
        "COMPOSEUI_WEB_COOKIE_SIGNING",
        "WATCHFILES_FORCE_POLLING",
    ):
        monkeypatch.setenv(variable, "")
    (tmp_path / "app.py").write_text(_APP)
    pages: list[str] = []

    def serve(app: str, **_: object) -> None:
        # what uvicorn's new process does with it, without spawning one
        with testclient.TestClient(uvicorn_importer.import_from_string(app)()) as client:
            pages.append(client.get("/").text)

    monkeypatch.setattr("composeui.webcore.webapplication.uvicorn.run", serve)

    composeui("run", "app.py")

    (page,) = pages
    assert "version one" in page
    assert 'id="cui-reload"' in page


#: a file without `run` that logs each main view it builds. Version 2 ends its process soon
#: after: `terminate` on Windows would end the supervisor alone
_LOGGED_APP = textwrap.dedent(
    """
    from __future__ import annotations

    import os
    import pathlib
    import threading

    from composeui.core.application import current_backend
    from composeui.core.view import MainView, define_view

    VERSION = 1

    @define_view
    class LoggedMainView(MainView):
        def __attrs_post_init__(self) -> None:
            super().__attrs_post_init__()
            with pathlib.Path(os.environ["RUNS_LOG"]).open("a") as log:
                log.write(f"{VERSION}|{current_backend().name}|{os.getpid()}\\n")
            if VERSION == 2:
                threading.Timer(1.0, os._exit, [0]).start()
    """
)


def _wait_for(condition: Callable[[], bool]) -> None:
    deadline = time.monotonic() + _TIMEOUT
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.05)


def _runs(log: Path) -> list[list[str]]:
    return [line.split("|") for line in log.read_text().splitlines()] if log.exists() else []


@pytest.mark.parametrize(
    ("backend", "package", "in_place"),
    [("qt", "qtpy.QtWidgets", True), ("textual", "textual", False)],
)
def test_the_command_shows_the_changed_code_of_a_file_without_run(
    backend: str,
    package: str,
    in_place: bool,
    tmp_path: Path,
) -> None:
    pytest.importorskip(package)
    command = shutil.which("composeui", path=str(Path(sys.executable).parent))
    assert command is not None  # the entry point of `pyproject.toml`
    log = tmp_path / "runs.log"
    app_file = tmp_path / "app.py"
    app_file.write_text(_LOGGED_APP)
    program = subprocess.Popen(  # noqa: S603
        [command, "run", "app.py", "--backend", backend],
        cwd=tmp_path,
        env={
            **os.environ,
            "QT_QPA_PLATFORM": "offscreen",
            # no terminal here
            "TEXTUAL_DRIVER": "textual.drivers.headless_driver:HeadlessDriver",
            "RUNS_LOG": str(log),
        },
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        # built by the supervisor, then by the app that it runs
        _wait_for(lambda: len(_runs(log)) >= 2)
        app_file.write_text(_LOGGED_APP.replace("VERSION = 1", "VERSION = 2"))
        assert program.wait(timeout=_TIMEOUT) == 0
    finally:
        if program.poll() is None:
            program.terminate()
            program.wait(timeout=_TIMEOUT)

    runs = _runs(log)
    # by their order, as `program.pid` on Windows is the launcher that starts the supervisor
    supervisor, first_app = runs[:2]
    changed = next(run for run in runs if run[0] == "2")
    assert first_app[2] != supervisor[2]
    assert first_app[:2] == ["1", backend.upper()]
    assert changed[1] == backend.upper()
    assert (changed[2] == first_app[2]) is in_place

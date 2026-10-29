"""Tests for ``--reload`` on the desktop: the app runs the changed code, or runs again."""

from __future__ import annotations

import importlib.util
import logging
import os
import platform
import subprocess
import sys
import textwrap
import time
import types
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

import composeui as composeui_package
from composeui.core.reload import (
    RELOADED_VARIABLE,
    can_reload_in_place,
    has_change_events,
    load_reloaded_state,
    program_command,
    rerun_program,
    run_reloading,
    save_reloaded_state,
    watch_changes,
)
from composeui.core.view import MainView, define_view

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

#: seconds a test waits for a child process before failing
_TIMEOUT = 30.0


def _wait_for(condition: Callable[[], bool]) -> None:
    deadline = time.monotonic() + _TIMEOUT
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.05)


def _stop(program: subprocess.Popen[bytes]) -> None:
    """Stop a supervisor that's still running, e.g. as a test failed, and so its app."""
    if program.poll() is None:
        program.terminate()  # not killed: then its app would go on
        try:
            program.wait(timeout=_TIMEOUT)
        except subprocess.TimeoutExpired:
            program.kill()


def _text(path: Path) -> str:
    return path.read_text() if path.exists() else ""


def _lines(log: Path) -> int:
    return len(log.read_text().splitlines()) if log.exists() else 0


def test_the_app_runs_the_changed_code_or_again_in_a_new_process_or_after_a_failure(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)  # the directory watched
    log = tmp_path / "runs.log"
    mode = tmp_path / "mode"
    mode.write_text("ack")
    # each run logs its start, then exits with the code `mode` holds, or else follows the
    # changes as an app does: it takes them and runs the changed code itself ("ack"),
    # slower than the supervisor waits for an app to take them ("slow"), or exits
    monkeypatch.setattr("composeui.core.reload._RELOAD_TIMEOUT", 0.3)
    program = textwrap.dedent(
        f"""
        import os, pathlib, sys, time
        log = pathlib.Path({str(log)!r})
        mode = pathlib.Path({str(mode)!r})
        with log.open("a") as file:
            file.write("start\\n")
        if mode.read_text() not in ("ack", "slow", "exit"):
            sys.exit(int(mode.read_text()))
        changes = pathlib.Path(os.environ["COMPOSEUI_RELOADED"], "changes")
        taken = changes.with_name("taken")
        while True:
            if changes.exists():
                if mode.read_text() not in ("ack", "slow"):
                    sys.exit(0)
                changes.replace(taken)
                if mode.read_text() == "slow":
                    time.sleep(1)
                with log.open("a") as file:
                    file.write("reloaded\\n")
                taken.unlink()
            time.sleep(0.05)
        """
    )
    changed = {tmp_path / "app.py"}

    def runs() -> list[str]:
        return log.read_text().splitlines() if log.exists() else []

    def changes() -> Iterator[set[Path]]:
        _wait_for(lambda: runs() == ["start"])
        yield set()  # nothing changed: the app keeps running
        yield changed
        _wait_for(lambda: runs() == ["start", "reloaded"])  # the same app runs on
        mode.write_text("slow")
        yield changed
        _wait_for(lambda: runs() == ["start", "reloaded", "reloaded"])  # waited for
        mode.write_text("exit")
        yield changed
        _wait_for(lambda: runs().count("start") == 2)  # a new app, as the app exited
        mode.write_text("1")
        yield changed
        deadline = time.monotonic() + _TIMEOUT
        while "waiting for a change" not in caplog.text:  # the failed app isn't run again
            assert time.monotonic() < deadline, "timed out"
            yield set()
        assert runs().count("start") == 3
        mode.write_text("0")
        yield changed
        while True:  # until the app exits by itself, without an error
            yield set()

    with caplog.at_level(logging.INFO, logger="COMPOSEUI"):
        assert run_reloading([sys.executable, "-c", program], changes()) == 0
    assert runs() == ["start", "reloaded", "reloaded", "start", "start", "start"]


@pytest.mark.parametrize(
    ("release", "directory", "has_events"),
    [
        ("6.18.54.1-microsoft-standard-WSL2", "/home/user/app", True),
        ("6.18.54.1-microsoft-standard-WSL2", "/mnt/c/Users/user/app", False),  # Windows'
        ("6.8.0-45-generic", "/mnt/data/app", True),  # not WSL: a Linux disk's mount
    ],
)
# a path resolves to a Windows one there, e.g. C:\mnt\c\...: not WSL's /mnt/c/...
@pytest.mark.skipif(sys.platform == "win32", reason="WSL's paths are Linux paths")
def test_only_a_windows_drive_s_files_under_wsl_are_polled(
    release: str, directory: str, has_events: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    uname = platform.uname()
    monkeypatch.setattr("platform.uname", lambda: uname._replace(system="Linux", release=release))

    assert has_change_events(Path(directory)) is has_events


@define_view
class _WordsMainView(MainView):
    count: str = "many"


@define_view
class _CountMainView(MainView):
    """`_WordsMainView` changed: its saved state no longer fits."""

    count: int = 0


def test_a_state_that_no_longer_fits_is_dropped_with_the_language_it_was_shown_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv(RELOADED_VARIABLE, str(tmp_path))
    previous = _WordsMainView()
    previous.set_language("fr")
    save_reloaded_state(previous, None)
    changed = _CountMainView()

    load_reloaded_state(changed, None)

    assert "is dropped" in caplog.text
    assert changed.language == "en"  # as the app starts
    assert changed.count == 0


def test_a_damaged_session_only_loses_what_the_study_doesn_t_hold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(RELOADED_VARIABLE, str(tmp_path))
    previous = _CountMainView(count=7, state_filepath=Path("mine.count"))
    previous.set_language("fr")
    save_reloaded_state(previous, None)
    (tmp_path / "session.json").write_text("{")  # e.g. cut short by a crash
    reloaded = _CountMainView()

    load_reloaded_state(reloaded, None)

    assert reloaded.count == 7
    assert reloaded.state_filepath is None
    assert reloaded.language == "en"


def test_only_composeui_s_own_code_needs_a_new_process(tmp_path: Path) -> None:
    composeui = Path(composeui_package.__file__).parent

    assert can_reload_in_place([tmp_path / "app.py", tmp_path / "views" / "form.py"])
    assert not can_reload_in_place([tmp_path / "app.py", composeui / "core" / "view.py"])


@pytest.mark.parametrize("watcher", ["watchfiles", "polling", "polling-without-events"])
def test_a_change_of_the_program_s_code_is_seen_but_not_of_another_file(
    watcher: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if watcher == "polling":
        monkeypatch.setitem(sys.modules, "watchfiles", None)  # not installed
    else:
        pytest.importorskip("watchfiles")
    if watcher == "polling-without-events":
        # watchfiles installed, but no events reported, e.g. a Windows drive on WSL
        monkeypatch.setattr("composeui.core.reload.has_change_events", lambda _directory: False)
    project = tmp_path / "project"
    app = project / "app.py"
    hidden = project / ".venv" / "lib.py"
    # a conda environment in the project: its standard library outside a `site-packages`
    environment = project / "env"
    standard = environment / "lib" / "python3.9" / "enum.py"
    monkeypatch.setattr("sys.prefix", str(environment))
    notes = project / "notes.txt"
    for path in (app, hidden, standard, notes):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")
    link = tmp_path / "link"
    try:
        link.symlink_to(project, target_is_directory=True)
    except OSError:  # Windows makes a link only in Developer Mode: the project itself
        link = project
    changes = watch_changes(link)  # watching from now on

    for path in (app, hidden, standard, notes):
        path.write_text("changed")
        os.utime(path, (time.time() + 10, time.time() + 10))  # a coarse clock still differs
    seen: set[Path] = set()
    deadline = time.monotonic() + _TIMEOUT
    while app not in seen:
        assert time.monotonic() < deadline, "timed out"
        seen |= next(changes)
    if watcher != "watchfiles":  # polled: a look, empty, at each step
        assert next(changes) == set()

    changes.close()

    assert seen == {app}  # its real path, not the link's


#: a Qt app logging what each main view shows. The first changes the state, the model's
#: data and the window, then waits for a change; the next closes its window
_QT_APP = textwrap.dedent(
    """
    import os, pathlib
    import attrs
    from qtpy.QtCore import QTimer
    from qtpy.QtWidgets import QApplication
    from composeui.core.sqlitemodel import SqliteModel, SqliteTable, table
    from composeui.core.view import IntInputView, MainView, define_view
    from composeui.qtcore.qtapplication import QtModelApplication

    VERSION = 1

    @define_view
    class CountMainView(MainView):
        count: IntInputView = attrs.Factory(IntInputView)

    class Notes(SqliteTable):
        create = "CREATE TABLE note (text TEXT NOT NULL);"

    class NotesModel(SqliteModel):
        notes = table(Notes)

    class LoggingApplication(QtModelApplication):
        def render(self, renderer_type):
            super().render(renderer_type)
            main_view = self.main_view
            window = main_view.renderer.qt_object
            fields = (
                "COMPOSEUI_RELOADED" in os.environ,
                os.getpid(),
                VERSION,
                main_view.count.value,
                main_view.state_filepath,
                main_view.language,
                self.model.notes.fetch_column("SELECT text FROM note"),
                window.objectName(),
            )
            with pathlib.Path(os.environ["RUNS_LOG"]).open("a") as log:
                log.write("|".join(map(str, fields)) + "\\n")
            if main_view.count.value is None:
                main_view.count.value = 7
                main_view.state_filepath = pathlib.Path("mine.count")
                main_view.set_language("fr")  # as from the Language menu
                with self.model.notes.connection() as db:
                    db.execute("INSERT INTO note VALUES ('kept')")
                window.setObjectName("kept")
            else:
                QTimer.singleShot(0, QApplication.quit)

    LoggingApplication(build_main_view=CountMainView, build_model=NotesModel).run()
    with pathlib.Path(os.environ["RUNS_LOG"]).open("a") as log:
        log.write("after run\\n")  # never, as the program ends at `run`
    """
)


def test_a_qt_app_with_reload_shows_the_changed_code_in_its_window_as_it_was_left(
    tmp_path: Path,
) -> None:
    pytest.importorskip("qtpy.QtWidgets")
    log = tmp_path / "runs.log"
    output = tmp_path / "output.log"
    script = tmp_path / "app.py"
    code = _QT_APP
    script.write_text(code)
    with output.open("w") as out:
        program = subprocess.Popen(  # noqa: S603
            [sys.executable, str(script), "--reload"],
            cwd=tmp_path,
            env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "RUNS_LOG": str(log)},
            stdout=out,
            stderr=subprocess.STDOUT,
        )
        try:
            _wait_for(lambda: _lines(log) == 1)
            script.write_text(code.replace("VERSION = 1", "VERSION = ("))  # a syntax error
            _wait_for(lambda: "The changed code fails" in output.read_text())
            script.write_text(code.replace("VERSION = 1", "VERSION = 2"))
            assert program.wait(timeout=_TIMEOUT) == 0
        finally:
            _stop(program)

    first, second = (line.split("|") for line in log.read_text().splitlines())
    # shown by the child alone, which didn't supervise a child of its own
    assert first == ["True", second[1], "1", "None", "None", "en", "[]", ""]
    # the same process and window, after the code that failed; the state and the model's
    # data the first code left, the user's study, not the scratch one saved, and the
    # language picked
    assert second[2:] == ["2", "7", "mine.count", "fr", "['kept']", "kept"]


def test_a_qt_app_saves_its_state_and_exits_for_a_new_process_when_composeui_changed(
    tmp_path: Path,
) -> None:
    pytest.importorskip("qtpy.QtWidgets")
    log = tmp_path / "runs.log"
    script = tmp_path / "app.py"
    script.write_text(_QT_APP)
    state = tmp_path / "state"
    state.mkdir()
    # as the supervisor runs it
    env = {
        **os.environ,
        "QT_QPA_PLATFORM": "offscreen",
        "RUNS_LOG": str(log),
        "COMPOSEUI_RELOADED": str(state),
    }
    first = subprocess.Popen([sys.executable, str(script)], cwd=tmp_path, env=env)  # noqa: S603
    try:
        _wait_for(lambda: _lines(log) == 1)
        view_module = Path(composeui_package.__file__).parent / "core" / "view.py"
        (state / "changes").write_text(f"{view_module}\n")
        assert first.wait(timeout=_TIMEOUT) == 0
    finally:
        first.kill()
    # taken, but not run in place: never acknowledged
    assert (state / "taken").exists()
    (state / "taken").unlink()  # as the supervisor cleans up

    # the supervisor runs it again
    subprocess.run(  # noqa: S603
        [sys.executable, str(script)], cwd=tmp_path, env=env, timeout=_TIMEOUT, check=True
    )

    before, after = (line.split("|") for line in log.read_text().splitlines())
    assert after[1] != before[1]  # a new process
    assert after[3:-1] == ["7", "mine.count", "fr", "['kept']"]


#: a Qt app logging each render and model's close, with its code's version, its process and
#: whether a supervisor runs it. Version 1 opens a modal dialog for a while, version 2 fails
#: to set up its model, and version 3 closes its window once shown
_LIFECYCLE_APP = textwrap.dedent(
    """
    import os, pathlib
    from qtpy.QtCore import QTimer
    from qtpy.QtWidgets import QApplication, QMessageBox
    from composeui.core.model import Model
    from composeui.core.view import MainView
    from composeui.qtcore.qtapplication import QtModelApplication

    VERSION = 1

    def log(event):
        supervised = "COMPOSEUI_RELOADED" in os.environ
        with pathlib.Path(os.environ["RUNS_LOG"]).open("a") as file:
            file.write(f"{event}|{VERSION}|{os.getpid()}|{supervised}\\n")

    class LoggedModel(Model):
        def close(self):
            log("close")

    def ask():
        log("dialog")
        box = QMessageBox()
        QTimer.singleShot(1500, box.accept)
        box.exec()  # as a callback's file dialog: its own event loop
        log("dialog closed")

    def setup(main_view, model):
        if VERSION == 2:
            raise RuntimeError("can't set up the model")

    class LoggingApplication(QtModelApplication):
        def render(self, renderer_type):
            super().render(renderer_type)
            log("render")
            if VERSION == 1:
                QTimer.singleShot(0, ask)
            if VERSION == 3:
                QTimer.singleShot(0, QApplication.quit)

    LoggingApplication(build_main_view=MainView, build_model=LoggedModel, setup_model=setup).run()
    """
)


def test_a_qt_app_with_reload_closes_every_model_it_built(tmp_path: Path) -> None:
    pytest.importorskip("qtpy.QtWidgets")
    log = tmp_path / "runs.log"
    script = tmp_path / "app.py"
    script.write_text(_LIFECYCLE_APP)
    program = subprocess.Popen(  # noqa: S603
        [sys.executable, str(script), "--reload"],
        cwd=tmp_path,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "RUNS_LOG": str(log)},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for(lambda: "dialog|1" in _text(log))
        script.write_text(_LIFECYCLE_APP.replace("VERSION = 1", "VERSION = 2"))
        _wait_for(lambda: "close|2" in _text(log))
        # the same size, likely within the second the previous code was compiled
        script.write_text(_LIFECYCLE_APP.replace("VERSION = 1", "VERSION = 3"))
        assert program.wait(timeout=_TIMEOUT) == 0
    finally:
        _stop(program)

    events = [line.split("|") for line in log.read_text().splitlines()]
    supervisor, app = events[0][2], events[1][2]
    # on Windows, a virtual environment's python.exe is a launcher, which runs the
    # supervisor as its child: `program` is the launcher
    if sys.platform != "win32":
        assert supervisor == str(program.pid)
    assert supervisor != app
    assert events == [
        ["close", "1", supervisor, "False"],  # the supervisor's, never shown
        ["render", "1", app, "True"],
        ["dialog", "1", app, "True"],
        ["dialog closed", "1", app, "True"],  # the reload waited for it
        ["close", "2", app, "True"],  # its setup failed: the window keeps version 1
        ["render", "3", app, "True"],
        ["close", "1", app, "True"],  # replaced
        ["close", "3", app, "True"],  # the window closed
    ]


def test_a_qt_app_without_reload_closes_its_model_once_its_window_is_closed(
    tmp_path: Path,
) -> None:
    pytest.importorskip("qtpy.QtWidgets")
    log = tmp_path / "runs.log"
    script = tmp_path / "app.py"
    script.write_text(_LIFECYCLE_APP.replace("VERSION = 1", "VERSION = 3"))
    subprocess.run(  # noqa: S603
        [sys.executable, str(script)],
        cwd=tmp_path,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "RUNS_LOG": str(log)},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=_TIMEOUT,
        check=True,
    )

    events = [line.split("|")[:2] for line in log.read_text().splitlines()]
    assert events == [["render", "3"], ["close", "3"]]  # one process, shown then closed


#: a Qt app logging each render and model's close, with its code's version and its process.
#: It has a model unless `WITHOUT_MODEL` is set. Its render fails once while the file
#: `FAIL_RENDER` names exists; version 2 closes its window once shown
_FAILING_RENDER_APP = textwrap.dedent(
    """
    import os, pathlib
    from qtpy.QtCore import QTimer
    from qtpy.QtWidgets import QApplication
    from composeui.core.model import Model
    from composeui.core.view import MainView
    from composeui.qtcore.qtapplication import QtApplication, QtModelApplication

    WITH_MODEL = "WITHOUT_MODEL" not in os.environ
    BASE = QtModelApplication if WITH_MODEL else QtApplication

    VERSION = 1

    def log(event):
        with pathlib.Path(os.environ["RUNS_LOG"]).open("a") as file:
            file.write(f"{event}|{VERSION}|{os.getpid()}\\n")

    class LoggedModel(Model):
        def close(self):
            log("close")

    class LoggingApplication(BASE):
        def render(self, renderer_type):
            failing = pathlib.Path(os.environ["FAIL_RENDER"])
            if failing.exists():
                failing.unlink()
                raise RuntimeError("can't show")
            super().render(renderer_type)
            log("render")
            if VERSION == 2:
                QTimer.singleShot(0, QApplication.quit)

    options = {"build_model": LoggedModel} if WITH_MODEL else {}
    LoggingApplication(build_main_view=MainView, **options).run()
    """
)


@pytest.mark.parametrize("with_model", [True, False])
def test_a_qt_app_whose_changed_code_can_t_show_runs_it_again_in_a_new_process(
    with_model: bool,
    tmp_path: Path,
) -> None:
    pytest.importorskip("qtpy.QtWidgets")
    log = tmp_path / "runs.log"
    failing = tmp_path / "fail-render"
    script = tmp_path / "app.py"
    script.write_text(_FAILING_RENDER_APP)
    program = subprocess.Popen(  # noqa: S603
        [sys.executable, str(script), "--reload"],
        cwd=tmp_path,
        env={
            **os.environ,
            "QT_QPA_PLATFORM": "offscreen",
            "RUNS_LOG": str(log),
            "FAIL_RENDER": str(failing),
            **({} if with_model else {"WITHOUT_MODEL": "1"}),
        },
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for(lambda: "render|1" in _text(log))
        failing.touch()
        script.write_text(_FAILING_RENDER_APP.replace("VERSION = 1", "VERSION = 2"))
        assert program.wait(timeout=_TIMEOUT) == 0
    finally:
        _stop(program)

    events = [line.split("|") for line in log.read_text().splitlines()]
    (first,) = {pid for event, version, pid in events if event == "render" and version == "1"}
    (second,) = {pid for event, version, pid in events if event == "render" and version == "2"}
    assert second != first  # a new process
    supervisor = events[0][2]
    # on Windows, `program` is the launcher of the virtual environment's python.exe (see
    # `test_a_qt_app_with_reload_closes_every_model_it_built`)
    if with_model and sys.platform != "win32":
        assert supervisor == str(program.pid)
    expected = [
        ["close", "1", supervisor],  # the supervisor's, never shown
        ["render", "1", first],
        ["close", "2", first],  # the changed code's, which failed to show
        ["close", "1", first],  # the window's, as its app exited
        ["render", "2", second],  # shown in the new process
        ["close", "2", second],
    ]
    assert events == [event for event in expected if with_model or event[0] != "close"]


#: a Qt app without a model logging each render, with its code's version and its process.
#: Version 2 closes its window once shown
_NO_MODEL_APP = textwrap.dedent(
    """
    import os, pathlib
    from qtpy.QtCore import QTimer
    from qtpy.QtWidgets import QApplication
    from composeui.core.view import MainView
    from composeui.qtcore.qtapplication import QtApplication

    VERSION = 1

    class LoggingApplication(QtApplication):
        def render(self, renderer_type):
            super().render(renderer_type)
            with pathlib.Path(os.environ["RUNS_LOG"]).open("a") as file:
                file.write(f"render|{VERSION}|{os.getpid()}\\n")
            if VERSION == 2:
                QTimer.singleShot(0, QApplication.quit)

    LoggingApplication(build_main_view=MainView).run()
    """
)


def test_a_qt_app_without_a_model_shows_the_changed_code_in_its_window(
    tmp_path: Path,
) -> None:
    pytest.importorskip("qtpy.QtWidgets")
    log = tmp_path / "runs.log"
    script = tmp_path / "app.py"
    script.write_text(_NO_MODEL_APP)
    program = subprocess.Popen(  # noqa: S603
        [sys.executable, str(script), "--reload"],
        cwd=tmp_path,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "RUNS_LOG": str(log)},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for(lambda: "render|1" in _text(log))
        script.write_text(_NO_MODEL_APP.replace("VERSION = 1", "VERSION = 2"))
        assert program.wait(timeout=_TIMEOUT) == 0
    finally:
        _stop(program)

    (_, _, app), changed = (line.split("|") for line in log.read_text().splitlines())
    assert app != str(program.pid)  # shown by the supervisor's child
    assert changed == ["render", "2", app]  # in the same window and process


#: a Textual app logging its process and what its main view shows. The first run changes
#: the state once mounted, then waits for a change; the next exits once mounted
_TEXTUAL_APP = textwrap.dedent(
    """
    import os, pathlib
    import attrs
    from composeui.core.view import IntInputView, MainView, define_view
    from composeui.textualcore.textualapplication import TextualApplication

    @define_view
    class CountMainView(MainView):
        count: IntInputView = attrs.Factory(IntInputView)

    class LoggingApplication(TextualApplication):
        def render(self, renderer_type):
            super().render(renderer_type)
            main_view = self.main_view
            app = main_view.renderer.app
            fields = (os.getpid(), main_view.count.value, main_view.language)
            with pathlib.Path(os.environ["RUNS_LOG"]).open("a") as log:
                log.write("|".join(map(str, fields)) + "\\n")
            if main_view.count.value is None:
                def change():
                    main_view.count.value = 7
                    main_view.set_language("fr")
                app.mounted_callbacks.append(change)
            else:
                app.mounted_callbacks.append(app.exit)

    LoggingApplication(build_main_view=CountMainView).run()
    """
)


def test_a_textual_app_with_reload_runs_again_in_a_new_process_as_it_was_left(
    tmp_path: Path,
) -> None:
    pytest.importorskip("textual")
    log = tmp_path / "runs.log"
    script = tmp_path / "app.py"
    script.write_text(_TEXTUAL_APP)
    program = subprocess.Popen(  # noqa: S603
        [sys.executable, str(script), "--reload"],
        cwd=tmp_path,
        env={
            **os.environ,
            # no terminal here
            "TEXTUAL_DRIVER": "textual.drivers.headless_driver:HeadlessDriver",
            "RUNS_LOG": str(log),
        },
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for(lambda: _lines(log) == 1)
        with script.open("a") as file:
            file.write("# changed\n")
        assert program.wait(timeout=_TIMEOUT) == 0
    finally:
        _stop(program)

    first, second = (line.split("|") for line in log.read_text().splitlines())
    assert first[1:] == ["None", "en"]
    assert second[0] != first[0]  # a new process
    assert second[1:] == ["7", "fr"]  # the state, and the language, the first left


#: a Textual app with a model logging each render and model's close, with its code's
#: version and its process. Version 1 logs once mounted for a while, then waits for a
#: change; version 2 exits once mounted
_TEXTUAL_MODEL_APP = textwrap.dedent(
    """
    import os, pathlib
    from composeui.core.model import Model
    from composeui.core.view import MainView
    from composeui.textualcore.textualapplication import TextualModelApplication

    VERSION = 1

    def log(event):
        with pathlib.Path(os.environ["RUNS_LOG"]).open("a") as file:
            file.write(f"{event}|{VERSION}|{os.getpid()}\\n")

    class LoggedModel(Model):
        def close(self):
            log("close")

    class LoggingApplication(TextualModelApplication):
        def render(self, renderer_type):
            super().render(renderer_type)
            log("render")
            app = self.main_view.renderer.app
            if VERSION == 1:
                # past a few looks at whether files changed, which find none
                waited = lambda: app.set_timer(0.5, lambda: log("waited"))
                app.mounted_callbacks.append(waited)
            else:
                app.mounted_callbacks.append(app.exit)

    LoggingApplication(build_main_view=MainView, build_model=LoggedModel).run()
    """
)


def test_a_textual_app_with_reload_closes_every_model_it_built(tmp_path: Path) -> None:
    pytest.importorskip("textual")
    log = tmp_path / "runs.log"
    script = tmp_path / "app.py"
    script.write_text(_TEXTUAL_MODEL_APP)
    program = subprocess.Popen(  # noqa: S603
        [sys.executable, str(script), "--reload"],
        cwd=tmp_path,
        env={
            **os.environ,
            "TEXTUAL_DRIVER": "textual.drivers.headless_driver:HeadlessDriver",
            "RUNS_LOG": str(log),
        },
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for(lambda: "waited|1" in _text(log))
        script.write_text(_TEXTUAL_MODEL_APP.replace("VERSION = 1", "VERSION = 2"))
        assert program.wait(timeout=_TIMEOUT) == 0
    finally:
        _stop(program)

    events = [line.split("|") for line in log.read_text().splitlines()]
    supervisor, first, second = events[0][2], events[1][2], events[4][2]
    assert second != first  # a new process
    # on Windows, `program` is the launcher of the virtual environment's python.exe (see
    # `test_a_qt_app_with_reload_closes_every_model_it_built`)
    if sys.platform != "win32":
        assert supervisor == str(program.pid)
    assert supervisor not in (first, second)
    assert events == [
        ["close", "1", supervisor],  # the supervisor's, never shown
        ["render", "1", first],
        ["waited", "1", first],
        ["close", "1", first],  # its app exited for the change
        ["render", "2", second],
        ["close", "2", second],  # the app exited
    ]


def test_a_textual_app_without_reload_closes_its_model_once_it_exits(tmp_path: Path) -> None:
    pytest.importorskip("textual")
    log = tmp_path / "runs.log"
    script = tmp_path / "app.py"
    script.write_text(_TEXTUAL_MODEL_APP.replace("VERSION = 1", "VERSION = 2"))
    subprocess.run(  # noqa: S603
        [sys.executable, str(script)],
        cwd=tmp_path,
        env={
            **os.environ,
            "TEXTUAL_DRIVER": "textual.drivers.headless_driver:HeadlessDriver",
            "RUNS_LOG": str(log),
        },
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=_TIMEOUT,
        check=True,
    )

    events = [line.split("|")[:2] for line in log.read_text().splitlines()]
    assert events == [["render", "2"], ["close", "2"]]  # one process, shown then closed


# `terminate` there ends the process at once, without a signal it could handle
@pytest.mark.skipif(sys.platform == "win32", reason="Windows has no SIGTERM")
def test_a_supervisor_told_to_stop_stops_its_app(tmp_path: Path) -> None:
    pid_file = tmp_path / "app.pid"
    app = (
        "import os, pathlib, time; "
        f"pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid())); time.sleep(60)"
    )
    supervisor = subprocess.Popen(  # noqa: S603
        [
            sys.executable,
            "-c",
            "import sys; from composeui.core.reload import run_reloading; "
            f"run_reloading([sys.executable, '-c', {app!r}])",
        ],
        cwd=tmp_path,
    )
    _wait_for(pid_file.exists)
    _wait_for(lambda: pid_file.read_text() != "")
    app_pid = int(pid_file.read_text())

    supervisor.terminate()  # SIGTERM, as `kill` sends
    supervisor.wait(timeout=_TIMEOUT)

    _wait_for(lambda: not _is_running(app_pid))


def _is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


@pytest.mark.parametrize(
    ("code", "error"),
    [
        ("import sys\nsys.exit(0)\n", "the program exited instead of running an app"),
        ("count = 1\n", "the program didn't run an app"),  # e.g. its `run` call removed
    ],
)
def test_a_program_run_again_without_an_app_leaves_the_previous_one(
    code: str, error: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)  # the program's code, imported again
    script = tmp_path / "app.py"
    script.write_text(code)
    program = types.ModuleType("__main__")
    program.__file__ = str(script)  # `python app.py`
    monkeypatch.setitem(sys.modules, "__main__", program)

    with pytest.raises(RuntimeError, match=error):
        rerun_program()

    assert sys.modules["__main__"] is program


def test_a_module_run_again_is_found_again_and_keeps_its_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    (tmp_path / "counter.py").write_text(
        "from composeui.core.reload import keep_rerun\nkeep_rerun('the app')\n"
    )
    program = types.ModuleType("__main__")
    program.__spec__ = importlib.util.find_spec("counter")  # `python -m counter`
    monkeypatch.setitem(sys.modules, "__main__", program)
    monkeypatch.setattr("sys.argv", ["counter", "--reload"])

    assert rerun_program() == "the app"
    assert program_command() == [sys.executable, "-m", "counter", "--reload"]


def test_a_program_neither_a_script_nor_a_module_can_t_run_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "__main__", types.ModuleType("__main__"))  # `python -c`

    with pytest.raises(RuntimeError, match="can't find the program to run it again"):
        rerun_program()
    with pytest.raises(ValueError, match="start it as a script or with -m"):
        program_command()


def test_a_state_dropped_keeps_the_language_it_was_shown_in_if_the_same(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv(RELOADED_VARIABLE, str(tmp_path))
    save_reloaded_state(_WordsMainView(), None)  # in English, as the app starts
    changed = _CountMainView()
    languages: list[str] = []
    monkeypatch.setattr(changed, "set_language", languages.append)

    load_reloaded_state(changed, None)

    assert "is dropped" in caplog.text
    assert languages == []  # no language to set back


#: an app logging each start, which never looks at the changes, and exits on its second
_DEAF_APP = textwrap.dedent(
    """
    import pathlib, sys, time
    log = pathlib.Path(sys.argv[1])
    with log.open("a") as file:
        file.write("start\\n")
    if log.read_text().count("start") == 2:
        sys.exit(0)
    while True:
        time.sleep(0.05)
    """
)


def test_an_app_not_taking_a_change_in_time_runs_again_in_a_new_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("composeui.core.reload._RELOAD_TIMEOUT", 0.3)
    log = tmp_path / "runs.log"

    def changes() -> Iterator[set[Path]]:
        _wait_for(lambda: _lines(log) == 1)
        yield {tmp_path / "app.py"}
        while True:  # until the second app exits by itself
            yield set()

    with caplog.at_level(logging.INFO, logger="COMPOSEUI"):
        code = run_reloading([sys.executable, "-c", _DEAF_APP, str(log)], changes())

    assert code == 0
    assert "The app didn't answer" in caplog.text
    assert _lines(log) == 2


class _OneLook:
    """The changes as an iterator, not a generator: one look, once `ready`, then no more."""

    def __init__(self, ready: Callable[[], bool]) -> None:
        self._ready = ready
        self._is_done = False

    def __iter__(self) -> _OneLook:
        return self

    def __next__(self) -> set[Path]:
        if self._is_done:
            raise StopIteration
        _wait_for(self._ready)
        self._is_done = True
        return set()


def test_an_app_running_the_changed_code_then_exiting_isn_t_run_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)  # the directory watched
    log = tmp_path / "runs.log"
    # it runs the changed code in place, acknowledging it, then is done at once, e.g. its
    # window closed: both while the supervisor waits between two looks at it
    app_code = textwrap.dedent(
        f"""
        import os, pathlib, time
        with pathlib.Path({str(log)!r}).open("a") as file:
            file.write("start\\n")
        changes = pathlib.Path(os.environ["COMPOSEUI_RELOADED"], "changes")
        while not changes.exists():
            time.sleep(0.01)
        taken = changes.with_name("taken")
        changes.replace(taken)
        taken.unlink()
        os._exit(0)
        """
    )
    app = tmp_path / "app.py"

    def changes() -> Iterator[set[Path]]:
        _wait_for(lambda: _lines(log) == 1)
        app.write_text("VERSION = 2\n")
        yield {app}
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:  # an app run again would start in that time
            yield set()

    assert run_reloading([sys.executable, "-c", app_code], changes()) == 0
    assert log.read_text().splitlines() == ["start"]


@pytest.mark.parametrize("ending", ["exhausted", "interrupted"])
def test_a_supervisor_whose_changes_end_stops_its_app(
    ending: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    log = tmp_path / "runs.log"

    def interrupted() -> Iterator[set[Path]]:
        _wait_for(lambda: _lines(log) == 1)
        raise KeyboardInterrupt  # Ctrl+C in the supervisor's terminal
        yield set()

    batches = interrupted() if ending == "interrupted" else _OneLook(lambda: _lines(log) == 1)

    assert run_reloading([sys.executable, "-c", _DEAF_APP, str(log)], batches) == 0
    assert _lines(log) == 1  # stopped, not run again


@pytest.mark.skipif(sys.platform == "win32", reason="Windows has no SIGTERM to ignore")
def test_an_app_ignoring_its_termination_is_killed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("composeui.core.reload._STOP_TIMEOUT", 0.3)
    started = tmp_path / "started"
    stubborn = (
        "import pathlib, signal, sys, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "pathlib.Path(sys.argv[1]).touch()\n"
        "while True:\n"
        "    time.sleep(0.05)\n"
    )

    begin = time.monotonic()
    command = [sys.executable, "-c", stubborn, str(started)]
    assert run_reloading(command, _OneLook(started.exists)) == 0
    assert time.monotonic() - begin < _TIMEOUT  # killed, not waited for


def test_the_changes_end_with_the_watcher_s(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    watchfiles = pytest.importorskip("watchfiles")
    app = tmp_path / "app.py"
    notes = tmp_path / "notes.txt"

    def watch(*_args: object, **_kwargs: object) -> Iterator[set[tuple[int, str]]]:
        yield set()  # the first, set up before the changes count
        yield {(2, str(app)), (2, str(notes))}  # then stopped, e.g. its directory removed

    monkeypatch.setattr(watchfiles, "watch", watch)
    monkeypatch.setattr("composeui.core.reload.has_change_events", lambda _directory: True)

    assert list(watch_changes(tmp_path)) == [{app.resolve()}]

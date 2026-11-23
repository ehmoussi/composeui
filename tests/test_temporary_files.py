"""The temporary files of a process that crashed, which an app's start removes."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import tempfile
import time
from typing import TYPE_CHECKING

import pytest

from composeui.core.application import Application
from composeui.core.sqlitemodel import DatabaseModel, SqliteDatabase, SqliteTable, per_session
from composeui.core.study import save_study
from composeui.core.view import MainView

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

# a program with a model, and a download being written beside `export.csv`, that crashes
_CRASHING_PROGRAM = """\
import os
import sys
import threading
from pathlib import Path
from composeui.core._views.files import save_download
from composeui.core.sqlitemodel import DatabaseModel, SqliteDatabase, SqliteTable, per_session
from composeui.core.view import MainView, StreamContent

class Runs(SqliteTable):
    create = "CREATE TABLE run(id INTEGER PRIMARY KEY, radius REAL NOT NULL);"

class RunsDatabase(SqliteDatabase):
    def __init__(self):
        super().__init__()
        self.runs = self.add_table(Runs)

class RunsModel(DatabaseModel):
    study = per_session(RunsDatabase)

model = RunsModel()
main_view = MainView()
writing = threading.Event()

def write(file):
    file.write(b"radius" * 100_000)
    file.flush()
    writing.set()
    threading.Event().wait()

save_download(main_view, Path(sys.argv[1]), StreamContent(write))
assert writing.wait(30)
os._exit(1)
"""

# a program with a model, which runs until its input closes
_RUNNING_PROGRAM = """\
import sys
from composeui.core.sqlitemodel import DatabaseModel, SqliteDatabase, SqliteTable, per_session

class Runs(SqliteTable):
    create = "CREATE TABLE run(id INTEGER PRIMARY KEY, radius REAL NOT NULL);"

class RunsDatabase(SqliteDatabase):
    def __init__(self):
        super().__init__()
        self.runs = self.add_table(Runs)

class RunsModel(DatabaseModel):
    study = per_session(RunsDatabase)

model = RunsModel()
print("running", flush=True)
sys.stdin.read()
"""


def _environment(temporary: Path) -> dict[str, str]:
    return {**os.environ, "TMPDIR": str(temporary), "TEMP": str(temporary), "TMP": str(temporary)}


def _crash(temporary: Path, target: Path) -> None:
    """Run `_CRASHING_PROGRAM`, which writes beside `target` as it crashes."""
    result = subprocess.run(  # noqa: S603 (the test's own program)
        [sys.executable, "-c", _CRASHING_PROGRAM, str(target)],
        env=_environment(temporary),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 1, result.stderr


def _age(folders: set[Path]) -> None:
    """Make `folders` older than a folder that its process may still be making."""
    old = time.time() - 3600
    for folder in folders:
        os.utime(folder, (old, old))


def test_an_app_s_start_removes_what_a_process_that_crashed_left(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    temporary, saved = tmp_path / "temporary", tmp_path / "saved"
    temporary.mkdir()
    saved.mkdir()
    target = saved / "export.csv"
    _crash(temporary, target)
    (root,) = temporary.iterdir()  # the user's folder of the processes' folders
    crashed = set(root.iterdir())
    _crash(temporary, target)
    recent = set(root.iterdir()) - crashed
    running = subprocess.Popen(  # noqa: S603 (the test's own program)
        [sys.executable, "-c", _RUNNING_PROGRAM],
        env=_environment(temporary),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert running.stdout is not None
        assert running.stdout.readline() == "running\n"
        alive = set(root.iterdir()) - crashed - recent
        # a folder made a moment ago may not have its lock yet: `recent` stays for a later start
        _age(crashed | alive)
        assert len(list(saved.iterdir())) == 2  # each crash's unfinished download
        monkeypatch.setattr(tempfile, "tempdir", str(temporary))

        Application(build_main_view=MainView)

        assert set(root.iterdir()) == alive | recent
        # the second crash's download only, never a file of the user's
        assert len(list(saved.iterdir())) == 1
        (folder,) = alive
        assert any(path.name.startswith("composeui-") for path in folder.iterdir())
    finally:
        running.communicate("", timeout=60)


class _Runs(SqliteTable):
    create = "CREATE TABLE run(id INTEGER PRIMARY KEY, radius REAL NOT NULL);"


class _RunsDatabase(SqliteDatabase):
    def __init__(self) -> None:
        super().__init__()
        self.runs = self.add_table(_Runs)


class _RunsModel(DatabaseModel):
    study = per_session(_RunsDatabase)


def _plant_a_writable_folder(root: Path) -> None:
    root.mkdir()
    root.chmod(0o777)


def _plant_a_file(root: Path) -> None:
    root.write_text("another user's", encoding="utf-8")


@pytest.mark.parametrize(
    "plant",
    [
        pytest.param(
            _plant_a_writable_folder,
            marks=pytest.mark.skipif(
                os.name != "posix", reason="Windows gives each user a temporary folder"
            ),
            id="writable-folder",
        ),
        # which `mkdir` refuses: it stopped every model, upload and save
        pytest.param(_plant_a_file, id="file"),
    ],
)
def test_an_app_doesn_t_put_its_files_where_another_user_can_change_them(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    plant: Callable[[Path], None],
) -> None:
    # as another user's, at the path of the user's folder
    name = f"composeui-scratch-{os.getuid()}" if os.name == "posix" else "composeui-scratch"
    root = tmp_path / name
    plant(root)
    before = sorted(root.rglob("*"))
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    with caplog.at_level(logging.WARNING, logger="COMPOSEUI"):
        Application(build_main_view=MainView)  # as an app starts
        model = _RunsModel()
        try:
            save_study(MainView(), model, tmp_path / "runs.study")
        finally:
            model.close()

    assert sorted(root.rglob("*")) == before
    assert (tmp_path / "runs.study").exists()
    assert caplog.messages.count(f"{root} isn't the user's own folder: a crash's files stay") == 1

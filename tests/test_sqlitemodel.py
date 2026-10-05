"""Tests for `SqliteModel` and the study files saving it with the views."""

from __future__ import annotations

import json
import zipfile
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Callable

import attrs
import pytest

from composeui.core.application import ModelApplication
from composeui.core.sqlitemodel import SqliteModel, SqliteTable
from examples.webhello import HelloMainView

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterator
    from pathlib import Path


@attrs.define
class Run:
    id: int
    radius: float


@attrs.define
class MeasuredRun:
    id: int
    radius: float
    stress: float


class Runs(SqliteTable):
    create = "CREATE TABLE run(id INTEGER PRIMARY KEY, radius REAL NOT NULL);"

    def add(self, radius: float) -> None:
        with self.connection() as db:
            db.execute("INSERT INTO run(radius) VALUES (?)", (radius,))

    def radii(self) -> list[float]:
        return [run.radius for run in self.fetch(Run, "SELECT * FROM run ORDER BY id")]


class RunsModel(SqliteModel):
    def __init__(self) -> None:
        super().__init__()
        self.runs = self.add_table(Runs)


class MeasuredRuns(SqliteTable):
    create = (
        "CREATE TABLE run(id INTEGER PRIMARY KEY, radius REAL NOT NULL,"
        " stress REAL NOT NULL DEFAULT 0);"
    )


def _add_stress(db: sqlite3.Connection) -> None:
    db.execute("ALTER TABLE run ADD COLUMN stress REAL NOT NULL DEFAULT 0")


class MeasuredRunsModel(SqliteModel):
    """`RunsModel`'s next version: its runs gained a stress."""

    schema_version = 2
    migrations = MappingProxyType({1: _add_stress})

    def __init__(self) -> None:
        super().__init__()
        self.runs = self.add_table(MeasuredRuns)


App = ModelApplication[HelloMainView, RunsModel]


@pytest.fixture
def app() -> Iterator[App]:
    app = App(main_view=HelloMainView(), model=RunsModel())
    yield app
    app.model.close()


def _save(app: ModelApplication[HelloMainView, Any], path: Path) -> None:
    """Save as the File menu does, `path` being the file the user picks."""
    app.main_view.file_view.filepath = path
    app.main_view.file_menu.save.triggered.emit()


def _open(app: ModelApplication[HelloMainView, Any], path: Path) -> None:
    app.main_view.file_view.filepath = path
    app.main_view.file_menu.open_file.triggered.emit()


def test_a_saved_study_opens_with_its_views_and_its_rows(app: App, tmp_path: Path) -> None:
    app.main_view.form.name.text = "Bob"
    app.model.runs.add(80.0)
    app.model.runs.add(50.0)
    path = tmp_path / "study.hello"
    _save(app, path)
    other = App(main_view=HelloMainView(), model=RunsModel())

    _open(other, path)

    assert other.model.runs.radii() == [80.0, 50.0]
    assert other.main_view.form.name.text == "Bob"
    assert other.main_view.state_filepath == path
    # the user's file is the study, not the scratch database the model works on
    app.model.runs.add(20.0)
    _open(other, path)
    assert other.model.runs.radii() == [80.0, 50.0]
    other.model.close()


def test_new_empties_the_tables_and_resets_the_views(app: App) -> None:
    app.main_view.form.name.text = "Bob"
    app.model.runs.add(80.0)
    changes: list[None] = []
    app.model.runs.changed.connect(lambda: changes.append(None))

    app.main_view.file_menu.new.triggered.emit()

    assert app.model.runs.radii() == []
    assert app.main_view.form.name.text == ""
    assert changes == [None]  # the views showing the runs refresh


def test_a_block_that_raises_writes_nothing(app: App) -> None:
    changes: list[None] = []
    app.model.runs.changed.connect(lambda: changes.append(None))

    def add_then_fail() -> None:
        with app.model.connection():
            app.model.runs.add(80.0)  # joins the outer block, so it's undone with it
            raise RuntimeError

    with pytest.raises(RuntimeError):
        add_then_fail()

    assert app.model.runs.radii() == []
    assert changes == []
    app.model.runs.add(50.0)
    assert app.model.runs.radii() == [50.0]
    assert changes == [None]


def test_a_study_of_an_older_version_is_brought_up_to_date(app: App, tmp_path: Path) -> None:
    app.model.runs.add(80.0)
    path = tmp_path / "study.hello"
    _save(app, path)
    newer = ModelApplication(main_view=HelloMainView(), model=MeasuredRunsModel())

    _open(newer, path)

    runs = newer.model.runs.fetch(MeasuredRun, "SELECT * FROM run")
    assert runs == [MeasuredRun(id=1, radius=80.0, stress=0.0)]
    newer.model.close()


def _newer_study(path: Path) -> None:
    newer = ModelApplication(main_view=HelloMainView(), model=MeasuredRunsModel())
    _save(newer, path)
    newer.model.close()


def _views_only(path: Path) -> None:
    HelloMainView().save_state(path)


def _archive(views: bytes, data: bytes) -> Callable[[Path], None]:
    def write(path: Path) -> None:
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("views.json", views)
            archive.writestr("data.sqlite", data)

    return write


@pytest.mark.parametrize(
    ("write", "reason"),
    [
        (_newer_study, "it was saved by a newer version of the application"),
        (_views_only, "it isn't a valid .hello file"),
        (lambda path: path.write_bytes(b"PK\x03\x04 damaged"), "it isn't a valid .hello file"),
        (_archive(b"{}", b"not a database"), "its data isn't a valid database"),
        (
            _archive(json.dumps({"form": {"age": {"value": "abc"}}}).encode(), b""),
            "it doesn't match this application",
        ),
    ],
)
def test_a_study_that_does_not_fit_changes_nothing_and_says_why(
    app: App, tmp_path: Path, write: Callable[[Path], None], reason: str
) -> None:
    app.main_view.form.name.text = "Bob"
    app.model.runs.add(80.0)
    path = tmp_path / "study.hello"
    write(path)

    _open(app, path)

    assert app.main_view.status_bar.message == f"Can't open 'study.hello': {reason}."
    assert app.model.runs.radii() == [80.0]
    assert app.main_view.form.name.text == "Bob"
    assert app.main_view.state_filepath is None


def test_a_failed_save_leaves_the_previous_study_whole(
    app: App, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app.model.runs.add(80.0)
    path = tmp_path / "study.hello"
    _save(app, path)
    saved = path.read_bytes()
    app.model.runs.add(50.0)

    def full_disk(*_: object) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(SqliteModel, "save_data", full_disk)

    with pytest.raises(OSError, match="No space left"):
        _save(app, path)

    assert path.read_bytes() == saved
    assert [file.name for file in tmp_path.iterdir()] == ["study.hello"]

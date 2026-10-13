"""Tests for `SqliteModel` and the study files saving it with the views."""

from __future__ import annotations

import json
import zipfile
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Callable, ClassVar

import attrs
import pytest
from attrs import Factory

from composeui.core.application import ModelApplication
from composeui.core.model import RefusedError
from composeui.core.sqlitemodel import SqliteModel, SqliteTable
from composeui.core.view import ButtonView, MainView, TableView, define_view
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
    # what a view refreshing from the rows would see of the views
    names_seen: list[str] = []
    other.model.runs.changed.connect(lambda: names_seen.append(other.main_view.form.name.text))

    _open(other, path)

    assert other.model.runs.radii() == [80.0, 50.0]
    assert other.main_view.form.name.text == "Bob"
    assert other.main_view.state_filepath == path
    assert names_seen == ["Bob"]  # told once the study's views are in place too
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


class Parts(SqliteTable):
    create = """
        CREATE TABLE part(id INTEGER PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE use(part_id INTEGER NOT NULL REFERENCES part(id));
        CREATE TABLE removed(name TEXT NOT NULL);
        CREATE TRIGGER part_removed AFTER DELETE ON part
        BEGIN INSERT INTO removed(name) VALUES (old.name); END;
    """


class PartsModel(SqliteModel):
    def __init__(self) -> None:
        super().__init__()
        self.parts = self.add_table(Parts)


def _started(model: PartsModel, tmp_path: Path) -> None:
    """Leave `model` on the database it's built with."""


def _new(model: PartsModel, _tmp_path: Path) -> None:
    model.new()


def _opened(model: PartsModel, tmp_path: Path) -> None:
    path = tmp_path / "data.sqlite"
    model.save_data(path)
    model.open_data(path)


@pytest.mark.parametrize("start", [_started, _new, _opened])
def test_every_database_keeps_the_models_settings(
    start: Callable[[PartsModel, Path], None], tmp_path: Path
) -> None:
    model = PartsModel()
    start(model, tmp_path)

    with pytest.raises(RefusedError), model.parts.connection() as db:
        db.execute("INSERT INTO use(part_id) VALUES (1)")  # foreign keys are enforced
    with model.parts.connection() as db:
        db.execute("INSERT INTO part(id, name) VALUES (1, 'bolt')")
        db.execute("INSERT OR REPLACE INTO part(id, name) VALUES (1, 'screw')")
        # the replaced row went through the delete trigger (recursive triggers are on)
        assert [row["name"] for row in db.execute("SELECT name FROM removed")] == ["bolt"]
    model.close()


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


class Tags(SqliteTable):
    create = """
        CREATE TABLE tag(
            name TEXT NOT NULL UNIQUE CONSTRAINT named CHECK (name != '')
        );
    """
    refusals: ClassVar[dict[str, str]] = {"named": "a tag needs a name"}

    def add(self, name: str) -> None:
        with self.connection() as db:
            db.execute("INSERT INTO tag(name) VALUES (?)", (name,))

    def rename(self, old_name: str, new_name: str) -> None:
        with self.connection() as db:
            db.execute("UPDATE tag SET name = ? WHERE name = ?", (new_name, old_name))

    def names(self) -> list[str]:
        with self.connection() as db:
            return [row["name"] for row in db.execute("SELECT name FROM tag ORDER BY name")]


class TagsModel(SqliteModel):
    def __init__(self) -> None:
        super().__init__()
        self.tags = self.add_table(Tags)


@define_view
class TagsMainView(MainView):
    add: ButtonView = Factory(ButtonView)
    table: TableView = Factory(TableView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self._init_app_info(title="Tags", extension=".tags")
        self.status_bar.timeout = 0
        self.table.editable_columns = [0]
        self.add.clicked.connect(self._add)
        self.table.cell_edited.connect(self._rename)

    def _add(self, model: TagsModel) -> None:
        with self.table.refusing(self.tr("Can't add the tag: {error}")):
            model.tags.add("")

    def _rename(self, row: int, column: int, text: str, model: TagsModel) -> None:
        with self.table.refusing(self.tr("Can't rename the tag: {error}")):
            model.tags.rename(self.table.rows[row][column], text)


TagsApp = ModelApplication[TagsMainView, TagsModel]


@pytest.fixture
def tags_app() -> Iterator[TagsApp]:
    app = TagsApp(main_view=TagsMainView(), model=TagsModel())
    app.model.tags.add("red")
    app.model.tags.add("blue")
    app.main_view.table.rows = [["blue"], ["red"]]
    yield app
    app.model.close()


def test_a_refusal_says_why_in_the_apps_language(
    tags_app: TagsApp, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog = {
        "Can't rename the tag: {error}": "Impossible de renommer l'étiquette : {error}",
        "a tag needs a name": "une étiquette doit avoir un nom",
    }
    (tmp_path / "fr.json").write_text(json.dumps(catalog), encoding="utf-8")
    monkeypatch.setattr(TagsMainView, "translations_dir", tmp_path)
    main_view = tags_app.main_view
    main_view.set_language("fr")

    main_view.table.emit_cell_edited(1, 0, "")

    assert main_view.status_bar.message == (
        "Impossible de renommer l'étiquette : une étiquette doit avoir un nom"
    )
    assert tags_app.model.tags.names() == ["blue", "red"]
    # the refusal's text follows the language too
    main_view.set_language("en")
    assert main_view.status_bar.message == "Can't rename the tag: a tag needs a name"


def test_a_refusal_no_key_names_shows_sqlites_message(tags_app: TagsApp) -> None:
    main_view = tags_app.main_view

    main_view.table.emit_cell_edited(1, 0, "blue")

    assert main_view.status_bar.message == (
        "Can't rename the tag: UNIQUE constraint failed: tag.name"
    )


def test_a_refusal_outside_an_edit_only_says_why(tags_app: TagsApp) -> None:
    main_view = tags_app.main_view

    main_view.add.clicked.emit()

    assert main_view.status_bar.message == "Can't add the tag: a tag needs a name"
    assert tags_app.model.tags.names() == ["blue", "red"]

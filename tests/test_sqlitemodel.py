"""Tests for `SqliteModel` and the study files saving it with the views."""

from __future__ import annotations

import contextlib
import json
import sqlite3
import struct
import threading
import tracemalloc
import zipfile
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Callable, ClassVar

import attrs
import pytest
from attrs import Factory

from composeui.core.application import ModelApplication
from composeui.core.model import RefusedError
from composeui.core.sqlitemodel import SqliteModel, SqliteTable, table, unique_name
from composeui.core.view import ButtonView, MainView, TableView, define_view
from examples.webhello import HelloMainView

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from composeui.core.jobs import Job


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
    app = App(build_main_view=HelloMainView, build_model=RunsModel)
    yield app
    app.model.close()


def _save(app: ModelApplication[HelloMainView, Any], path: Path) -> None:
    """Save as the File menu does, `path` being the file the user picks."""
    app.main_view.file_view.filepath = path
    app.main_view.file_menu.save.triggered.emit()


def test_save_as_saves_the_study_where_the_user_picks(app: App, tmp_path: Path) -> None:
    app.model.runs.add(80.0)
    path = tmp_path / "copy.hello"
    app.main_view.file_view.filepath = path

    app.main_view.file_menu.save_as.triggered.emit()

    other = App(build_main_view=HelloMainView, build_model=RunsModel)
    _open(other, path)
    assert other.model.runs.radii() == [80.0]
    other.model.close()


def _open(app: ModelApplication[HelloMainView, Any], path: Path) -> None:
    app.main_view.file_view.filepath = path
    app.main_view.file_menu.open_file.triggered.emit()


def test_a_saved_study_opens_with_its_views_and_its_rows(app: App, tmp_path: Path) -> None:
    app.main_view.form.name.text = "Bob"
    app.model.runs.add(80.0)
    app.model.runs.add(50.0)
    path = tmp_path / "study.hello"
    _save(app, path)
    other = App(build_main_view=HelloMainView, build_model=RunsModel)
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


def _opened_with_other_pages(model: PartsModel, tmp_path: Path) -> None:
    """Open a study's database as another tool may write it: its pages of 8 KiB."""
    path = tmp_path / "data.sqlite"
    model.save_data(path)
    other = sqlite3.connect(path)
    try:
        other.execute("PRAGMA page_size = 8192")
        other.execute("VACUUM")  # rewritten in pages of the new size
    finally:
        other.close()
    model.open_data(path)


@pytest.mark.parametrize("start", [_started, _new, _opened, _opened_with_other_pages])
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
        # trusted again once an opened database's schema is checked: the app's own
        (trusted,) = db.execute("PRAGMA trusted_schema").fetchone()
        assert trusted == 1
        # read apart during a write (`SqliteModel.reading`)
        assert tuple(db.execute("PRAGMA journal_mode").fetchone()) == ("wal",)
    model.close()


def test_closing_a_model_waits_for_no_write_running() -> None:
    model = PartsModel()
    writing, done = threading.Event(), threading.Event()

    def write() -> None:  # as a job's long write, e.g. filling a table
        with contextlib.suppress(sqlite3.Error), model.parts.connection():
            writing.set()
            done.wait(10)

    writer = threading.Thread(target=write)
    writer.start()
    assert writing.wait(5)
    closing = threading.Thread(target=model.close)  # as closing the app does
    closing.start()
    closing.join(2)
    is_closed = not closing.is_alive()
    done.set()
    writer.join(5)

    assert is_closed


def test_a_closed_model_reads_nothing_more_apart_as_its_connection() -> None:
    model = PartsModel()
    model.close()

    for connection in (model.parts.connection, model.parts.reading):
        with pytest.raises(sqlite3.ProgrammingError, match="closed database"), connection():
            pass


def test_a_saved_study_s_data_leaves_no_journal_beside_it(tmp_path: Path) -> None:
    model = PartsModel()
    path = tmp_path / "data.sqlite"
    model.save_data(path)
    model.close()

    saved = sqlite3.connect(path)
    try:
        assert saved.execute("PRAGMA journal_mode").fetchone() == ("delete",)
    finally:
        saved.close()
    assert [file.name for file in tmp_path.iterdir()] == ["data.sqlite"]


def test_a_study_of_an_older_version_is_brought_up_to_date(app: App, tmp_path: Path) -> None:
    app.model.runs.add(80.0)
    path = tmp_path / "study.hello"
    _save(app, path)
    newer = ModelApplication(build_main_view=HelloMainView, build_model=MeasuredRunsModel)

    _open(newer, path)

    runs = newer.model.runs.fetch(MeasuredRun, "SELECT * FROM run")
    assert runs == [MeasuredRun(id=1, radius=80.0, stress=0.0)]
    newer.model.close()


def _newer_study(path: Path) -> None:
    newer = ModelApplication(build_main_view=HelloMainView, build_model=MeasuredRunsModel)
    _save(newer, path)
    newer.model.close()


def _views_only(path: Path) -> None:
    HelloMainView().save_state(path)


def _archive(
    views: bytes, data: bytes, compression: int = zipfile.ZIP_STORED
) -> Callable[[Path], None]:
    def write(path: Path) -> None:
        with zipfile.ZipFile(path, "w", compression) as archive:
            archive.writestr("views.json", views)
            archive.writestr("data.sqlite", data)

    return write


def _forged(
    views: bytes, *, declared: int | None = None, method: int | None = None, flags: int = 0
) -> Callable[[Path], None]:
    """Write an archive whose `views.json` lies about its size, method or flags.

    Its entries say so twice, in its local header and in the central directory.
    """

    def write(path: Path) -> None:
        _archive(views, b"", zipfile.ZIP_DEFLATED)(path)
        data = bytearray(path.read_bytes())
        local, central = data.find(b"PK\x03\x04"), data.find(b"PK\x01\x02")
        if declared is not None:
            struct.pack_into("<I", data, local + 22, declared)
            struct.pack_into("<I", data, central + 24, declared)
        if method is not None:
            struct.pack_into("<H", data, local + 8, method)
            struct.pack_into("<H", data, central + 10, method)
        struct.pack_into("<H", data, local + 6, flags)
        struct.pack_into("<H", data, central + 8, flags)
        path.write_bytes(data)

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
        # a method `zipfile` unpacks whole (bzip2), or can't unpack (9, Deflate64)
        (_archive(b"{}", b"", zipfile.ZIP_BZIP2), "it isn't a valid .hello file"),
        (_forged(b"{}", method=9), "it isn't a valid .hello file"),
        (_forged(b"{}", flags=0x1), "it isn't a valid .hello file"),  # encrypted
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


def test_an_archive_lying_about_its_size_is_refused_before_it_is_unpacked(
    app: App, tmp_path: Path
) -> None:
    """A zip bomb: 64 MiB of views in a few kilobytes, said to be 2 bytes."""
    path = tmp_path / "study.hello"
    _forged(b" " * (64 * 1024 * 1024), declared=2)(path)
    assert path.stat().st_size < 1024 * 1024

    tracemalloc.start()
    try:
        _open(app, path)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()

    assert (
        app.main_view.status_bar.message
        == "Can't open 'study.hello': it isn't a valid .hello file."
    )
    assert peak < 8 * 1024 * 1024


#: a query that never ends: the numbers counted up from 1, none of them kept
_ENDLESS = (
    "WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM n) SELECT x FROM n WHERE x < 0"
)


def _study_with(app: App, path: Path, script: str, *, version: int = 1) -> None:
    """Save a study, its database changed by `script` as a forged file's would be."""
    _save(app, path)
    with zipfile.ZipFile(path) as archive:
        views = archive.read("views.json")
        data = path.with_suffix(".sqlite")
        data.write_bytes(archive.read("data.sqlite"))
    db = sqlite3.connect(data)
    db.executescript(f"{script}; PRAGMA user_version = {version};")
    db.close()
    _archive(views, data.read_bytes())(path)


@pytest.mark.parametrize(
    "script",
    [
        # a view that never ends, in place of the table the app queries
        f"DROP TABLE run; CREATE VIEW run(id, radius) AS {_ENDLESS}",
        f"CREATE VIEW forever AS {_ENDLESS}",  # an object the app doesn't have
        "CREATE TRIGGER rewrite AFTER INSERT ON run BEGIN UPDATE run SET radius = 0; END",
        "CREATE INDEX by_radius ON run(radius)",
        "ALTER TABLE run ADD COLUMN extra TEXT",
    ],
)
def test_a_database_not_made_as_a_new_one_is_refused(app: App, tmp_path: Path, script: str) -> None:
    app.model.runs.add(80.0)
    path = tmp_path / "study.hello"
    _study_with(app, path, script)

    _open(app, path)

    message = "Can't open 'study.hello': its data doesn't match this application."
    assert app.main_view.status_bar.message == message
    assert app.model.runs.radii() == [80.0]


class _SlowMigrationModel(RunsModel):
    """A model whose migration queries a view of the file, which may never end."""

    schema_version = 2
    migrations = MappingProxyType({1: lambda db: db.execute("SELECT count(*) FROM forever")})
    open_time_limit = 0.2


def test_opening_a_database_is_cut_after_its_time_limit(app: App, tmp_path: Path) -> None:
    path = tmp_path / "study.hello"
    _study_with(app, path, f"CREATE VIEW forever AS {_ENDLESS}")
    slow = ModelApplication(build_main_view=HelloMainView, build_model=_SlowMigrationModel)
    opening = threading.Thread(target=_open, args=(slow, path), daemon=True)

    opening.start()
    opening.join(10)

    assert not opening.is_alive()
    message = "Can't open 'study.hello': its data isn't a valid database."
    assert slow.main_view.status_bar.message == message
    slow.model.close()


def test_a_job_s_writes_are_told_on_the_main_thread(app: App) -> None:
    threads: list[threading.Thread] = []
    app.model.runs.changed.connect(lambda: threads.append(threading.current_thread()))

    def write(_job: Job[None], model: RunsModel) -> None:
        model.runs.add(80.0)
        model.runs.add(50.0)

    app.main_view.jobs.start(write, app.model)
    app.main_view.jobs.wait()

    assert app.model.runs.radii() == [80.0, 50.0]
    assert threads == [threading.current_thread()] * 2


def test_opening_a_study_drops_the_jobs_before_it_replaces_the_rows(
    app: App, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "study.hello"
    _save(app, path)
    jobs = app.main_view.jobs
    # a job writing to the model, as long as it isn't canceled
    jobs.start(lambda job: job.sleep(60))
    running_as_replaced: list[bool] = []
    open_data = RunsModel.open_data

    def replace_rows(model: RunsModel, data_path: Path) -> None:
        running_as_replaced.append(jobs.is_running)
        open_data(model, data_path)

    monkeypatch.setattr(RunsModel, "open_data", replace_rows)

    _open(app, path)

    assert running_as_replaced == [False]


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

    def add_unique(self, base: str) -> str:
        with self.connection() as db:
            name = unique_name(db, "tag", "name", base)
            db.execute("INSERT INTO tag(name) VALUES (?)", (name,))
        return name

    def names(self) -> list[str]:
        return self.fetch_column("SELECT name FROM tag ORDER BY name")


class TagsModel(SqliteModel):
    tags = table(Tags)


@define_view
class TagsMainView(MainView):
    app_title = "Tags"
    extension = ".tags"

    add: ButtonView = Factory(ButtonView)
    table: TableView = Factory(TableView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
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

    def show_tags(self, model: TagsModel) -> None:
        self.table.rows = [[name] for name in model.tags.names()]


TagsApp = ModelApplication[TagsMainView, TagsModel]


@pytest.fixture
def tags_app() -> Iterator[TagsApp]:
    app = TagsApp(build_main_view=TagsMainView, build_model=TagsModel)
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


def test_a_table_s_changed_signal_gives_a_view_s_method_the_model() -> None:
    def setup_model(main_view: TagsMainView, model: TagsModel) -> None:
        model.tags.add("red")
        # no lambda to hand it the model, nor a first call of its own
        model.tags.changed.connect(main_view.show_tags, now=True)

    app = TagsApp(build_main_view=TagsMainView, build_model=TagsModel, setup_model=setup_model)
    assert app.main_view.table.rows == [["red"]]
    app.model.tags.add("blue")
    assert app.main_view.table.rows == [["blue"], ["red"]]
    app.model.close()


def test_a_unique_name_numbers_the_base_past_the_names_taken_whatever_their_case() -> None:
    model = TagsModel()
    model.tags.add("Tag")
    model.tags.add("tag 2")

    assert [model.tags.add_unique("Tag") for _ in range(2)] == ["Tag 3", "Tag 4"]
    assert model.tags.add_unique("Label") == "Label"
    model.close()


class Notes(SqliteTable):
    create = "CREATE TABLE note(text TEXT NOT NULL);"


class NotedTagsModel(TagsModel):
    """Its tables declared by its class and its base's."""

    notes = table(Notes)


def test_each_model_builds_the_tables_its_classes_declare() -> None:
    model, other = NotedTagsModel(), NotedTagsModel()
    model.tags.add("red")

    assert (type(model.tags), type(model.notes)) == (Tags, Notes)
    assert other.tags.names() == []
    # a new study creates them again
    model.new()
    assert model.tags.names() == []
    assert model.notes.fetch_column("SELECT count(*) FROM note") == [0]
    model.close()
    other.close()

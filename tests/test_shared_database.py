"""Tests for the `shared` databases of a `DatabaseModel`: one per process, for every session."""

from __future__ import annotations

import gc
import logging
import re
import sqlite3
import subprocess
import sys
import textwrap
import threading
import time
import weakref
import zipfile
from contextlib import closing
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional, Union

import pytest
from attrs import Factory
from typing_extensions import override

from composeui.core import sqlitemodel
from composeui.core.application import ModelApplication
from composeui.core.jobs import Job
from composeui.core.model import InvalidStateError
from composeui.core.registry import RendererType
from composeui.core.sqlitemodel import (
    DatabaseModel,
    ReadOnlyDatabaseError,
    SqliteDatabase,
    SqliteTable,
    per_session,
    shared,
    table,
)
from composeui.core.view import LabelView, MainView, define_view

if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot

#: seconds a test waits at most for a thread or a process
_TIMEOUT = 30.0


class Names(SqliteTable):
    create = "CREATE TABLE name(text TEXT NOT NULL);"

    def add(self, text: str) -> None:
        with self.connection() as db:
            db.execute("INSERT INTO name VALUES (?)", (text,))

    def texts(self) -> list[str]:
        return self.fetch_column("SELECT text FROM name ORDER BY rowid")


class Book(SqliteDatabase):
    names = table(Names)


class Notes(SqliteDatabase):
    names = table(Names)


class _BookModel(DatabaseModel):
    study = per_session(Notes)
    book: Book


def _book_model(
    location: Union[Path, Callable[[], Path], None] = None,
) -> type[_BookModel]:
    """Get a model sharing a database of a class of its own: the process keeps one per class."""

    class OwnBook(Book):
        pass

    class BookModel(_BookModel):
        book = shared(OwnBook, location=location)

    return BookModel


class _PickupsModel(DatabaseModel):
    pickups: Book


def _pickups_model(
    fill: Callable[[Book, Job[None, Any]], None],
    *,
    location: Optional[Path] = None,
    read_only: bool = False,
) -> type[_PickupsModel]:
    """Get a model sharing a database that `fill` fills, of a class of its own."""

    class Pickups(Book):
        @override
        def fill(self, job: Job[None, Any]) -> None:
            fill(self, job)

    class PickupsModel(_PickupsModel):
        pickups = shared(Pickups, location=location, read_only=read_only)

    return PickupsModel


class _Seen:
    """What a session's views would show at each notice, for a test to wait on."""

    def __init__(self, model: _BookModel) -> None:
        self._model = model
        self._condition = threading.Condition()
        self.texts: list[list[str]] = []
        model.book.names.changed.connect(self._told)

    def _told(self) -> None:
        texts = self._model.book.names.texts()
        with self._condition:
            self.texts.append(texts)
            self._condition.notify_all()

    def wait_for(self, text: str) -> None:
        """Wait until a notice shows `text`: the notices taken before it are over."""
        with self._condition:
            assert self._condition.wait_for(
                lambda: any(text in texts for texts in self.texts), _TIMEOUT
            )


def _wait_for_notices(database: SqliteDatabase) -> None:
    """Wait until the sessions are told of the changes made so far: their threads are over."""
    name = f"composeui-{type(database).__name__}-notices"
    for thread in threading.enumerate():
        if thread.name == name:
            thread.join(_TIMEOUT)
            assert not thread.is_alive()


def test_a_write_in_one_session_is_read_and_told_in_the_other_on_another_thread() -> None:
    model_type = _book_model()
    with closing(model_type()) as alice, closing(model_type()) as bob:
        told: list[tuple[str, bool]] = []
        alice.book.names.changed.connect(
            lambda: told.append(("alice", threading.current_thread() is threading.main_thread()))
        )
        bob.book.names.changed.connect(
            lambda: told.append(("bob", threading.current_thread() is threading.main_thread()))
        )
        seen = _Seen(bob)

        alice.book.names.add("Ada")
        alice.study.names.add("mine")
        assert bob.book.names.texts() == ["Ada"]
        assert bob.study.names.texts() == []  # each session's own database stays its own
        seen.wait_for("Ada")
        alice.book.names.add("Bob")  # in a later notice: the first one is over
        seen.wait_for("Bob")

        # the writer at once, in its thread, and once; the other on a thread holding no lock
        assert told == [("alice", True), ("bob", False)] * 2


def test_a_closed_session_is_no_longer_told_nor_kept() -> None:
    model_type = _book_model()
    with closing(model_type()) as alice, closing(model_type()) as carol:
        bob = model_type()
        bob_told, bob_released = threading.Event(), threading.Event()
        bob_calls: list[None] = []
        seen = _Seen(carol)

        def tell_bob() -> None:  # holds the notices back while the test closes bob
            bob_calls.append(None)
            bob_told.set()
            assert bob_released.wait(_TIMEOUT)

        bob.book.names.changed.connect(tell_bob)

        alice.book.names.add("first")
        assert bob_told.wait(_TIMEOUT)
        alice.book.names.add("pending")  # to tell bob once the first notice is over
        bob.close()
        bob_released.set()
        alice.book.names.add("after")  # tells bob no more
        seen.wait_for("after")
        _wait_for_notices(alice.book)  # bob's pending one included

        assert len(bob_calls) == 1
        with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
            bob.book.names.texts()
        with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
            bob.book.ready(Job(lambda _job, callback: callback()))
        # a session dropped unclosed goes too: the shared database doesn't hold it
        dropped = weakref.ref(model_type())
        gc.collect()
        assert dropped() is None


def test_a_session_busy_with_a_notice_holds_back_no_other_session_s() -> None:
    model_type = _book_model()
    with closing(model_type()) as alice, closing(model_type()) as bob:
        carol = model_type()
        bob_busy, bob_released = threading.Event(), threading.Event()

        def busy() -> None:  # e.g. a web session whose lock a long request holds
            bob_busy.set()
            assert bob_released.wait(_TIMEOUT)

        bob.book.names.changed.connect(busy)
        seen = _Seen(carol)
        try:
            alice.book.names.add("first")
            assert bob_busy.wait(_TIMEOUT)
            alice.book.names.add("second")  # while bob is still busy with the first
            seen.wait_for("second")
        finally:
            bob_released.set()
            carol.close()
            _wait_for_notices(alice.book)


def test_a_notice_whose_thread_can_t_start_leaves_the_write_done_and_the_next_one_told(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    model_type = _book_model()
    app, _ = _book_app(model_type)
    bob = app.model
    with closing(model_type()) as alice, closing(bob):
        start = threading.Thread.start

        def fail(_thread: threading.Thread) -> None:
            msg = "can't start new thread"
            raise RuntimeError(msg)

        monkeypatch.setattr(threading.Thread, "start", fail)
        with caplog.at_level(logging.ERROR, logger="COMPOSEUI"):
            alice.book.names.add("committed")  # raises nothing: the write is done
        monkeypatch.setattr(threading.Thread, "start", start)
        assert bob.book.names.texts() == ["committed"]
        assert [record.getMessage() for record in caplog.records] == [
            "Telling a session of a change failed"
        ]

        alice.book.names.add("next")
        app.main_view.jobs.wait()  # expects no notice of the thread that didn't start
        assert app.main_view.summary.text == "committed, next"


def test_a_session_whose_callback_fails_is_still_told_of_the_next_changes(
    caplog: pytest.LogCaptureFixture,
) -> None:
    model_type = _book_model()
    with closing(model_type()) as alice, closing(model_type()) as bob:
        bob_calls = threading.Semaphore(0)

        def fail() -> None:
            bob_calls.release()
            msg = "a callback's bug"
            raise RuntimeError(msg)

        bob.book.names.changed.connect(fail)

        with caplog.at_level(logging.ERROR, logger="COMPOSEUI"):
            for text in ("first", "second"):
                alice.book.names.add(text)
                assert bob_calls.acquire(timeout=_TIMEOUT)
            _wait_for_notices(alice.book)  # its second failure logged

        failures = [record for record in caplog.records if record.exc_info is not None]
        assert [record.getMessage() for record in failures] == [
            "Telling a session of a change failed"
        ] * 2


@define_view
class _SummaryMainView(MainView):
    """A main view whose summary shows what the model shares."""

    summary: LabelView = Factory(LabelView)


def _save(app: ModelApplication[_SummaryMainView, Any], path: Path) -> None:
    app.main_view.file_view.filepath = path
    app.main_view.file_menu.save.triggered.emit()


def _open(app: ModelApplication[_SummaryMainView, Any], path: Path) -> None:
    app.main_view.file_view.filepath = path
    app.main_view.file_menu.open_file.triggered.emit()


def test_a_study_leaves_the_shared_database_out(tmp_path: Path) -> None:
    app = ModelApplication(build_main_view=_SummaryMainView, build_model=_book_model())
    model = app.model
    try:
        main_view = app.main_view
        main_view._mark_saved()  # noqa: SLF001 (as the app's start does)
        model.book.names.add("everyone's")
        assert not main_view.has_unsaved_changes()
        for database in (model.study, model.book):  # neither has a fill to wait for
            database.ready(Job(lambda _job, callback: callback()))
        model.study.names.add("mine")
        assert main_view.has_unsaved_changes()
        path = tmp_path / "study.hello"
        _save(app, path)
        with zipfile.ZipFile(path) as archive:
            assert sorted(archive.namelist()) == ["study.sqlite", "views.json"]

        main_view.file_menu.new.triggered.emit()
        assert (model.study.names.texts(), model.book.names.texts()) == ([], ["everyone's"])
        model.book.names.add("after New")
        _open(app, path)
        assert (model.study.names.texts(), model.book.names.texts()) == (
            ["mine"],
            ["everyone's", "after New"],
        )
    finally:
        model.close()


_RUN = textwrap.dedent(
    """
    import sys
    from pathlib import Path

    from composeui.core.sqlitemodel import DatabaseModel, SqliteDatabase, SqliteTable, shared
    from composeui.core.sqlitemodel import table

    path, version = Path(sys.argv[1]), int(sys.argv[2])
    migrated = []


    def add_email(db):
        migrated.append(1)
        db.execute("ALTER TABLE customer ADD COLUMN email TEXT")


    class Customers(SqliteTable):
        create = (
            "CREATE TABLE customer(name TEXT NOT NULL);"
            if version == 1
            else "CREATE TABLE customer(name TEXT NOT NULL, email TEXT);"
        )


    class Crm(SqliteDatabase):
        schema_version = version
        migrations = {1: add_email}
        customers = table(Customers)


    class CrmModel(DatabaseModel):
        crm = shared(Crm, location=path)


    models = [CrmModel() for _ in range(3)]
    with models[0].crm.customers.connection() as db:
        db.execute("INSERT INTO customer(name) VALUES (?)", (f"run {version}",))
    print(models[1].crm.customers.fetch_column("SELECT name FROM customer"), len(migrated))
    for model in models:
        model.close()
    """
)


def test_a_kept_file_is_made_once_then_reopened_and_brought_up_to_date_once(
    tmp_path: Path,
) -> None:
    """A run of the server, then a newer one: each a process, whose shared database is its own."""
    path = tmp_path / "crm.sqlite"

    def run(version: int) -> str:
        done = subprocess.run(  # noqa: S603 (a command the code builds, no user input)
            [sys.executable, "-c", _RUN, str(path), str(version)],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
            check=False,
        )
        assert done.returncode == 0, done.stderr
        return done.stdout.strip()

    assert run(1) == "['run 1'] 0"
    assert sorted(file.name for file in tmp_path.iterdir()) == ["crm.sqlite"]
    assert run(2) == "['run 1', 'run 2'] 1"  # one migration for its three sessions


@pytest.mark.parametrize(
    ("read_only", "reason"),
    [
        (False, "it was saved by a newer version of the application"),
        (True, r"its version \(2\) isn't 1, and a read-only database can't be brought up to date"),
    ],
)
def test_a_kept_file_of_another_version_is_refused(
    tmp_path: Path, *, read_only: bool, reason: str
) -> None:
    path = tmp_path / "book.sqlite"
    db = sqlite3.connect(path)
    db.executescript(f"{Names.create} PRAGMA user_version = 2;")
    db.close()

    class OwnBook(Book):
        pass

    class BookModel(DatabaseModel):
        study = per_session(Notes)
        book = shared(OwnBook, location=path, read_only=read_only)

    with pytest.raises(InvalidStateError, match=f"{re.escape(str(path))}: {reason}"):
        BookModel()


def test_a_kept_read_only_file_is_read_without_a_write(tmp_path: Path) -> None:
    """E.g. reference data that ships with the app, where it may not be written."""
    path = tmp_path / "materials.sqlite"
    db = sqlite3.connect(path)
    db.executescript(Names.create)
    db.execute("INSERT INTO name VALUES ('steel')")
    db.execute("PRAGMA user_version = 1")
    db.commit()
    db.close()
    path.chmod(0o444)
    saved = path.read_bytes()

    class Materials(Book):
        pass

    class LabModel(DatabaseModel):
        materials = shared(Materials, location=path, read_only=True)

    try:
        with closing(LabModel()) as model:
            assert model.materials.names.texts() == ["steel"]
    finally:
        path.chmod(0o644)

    assert path.read_bytes() == saved
    assert [file.name for file in tmp_path.iterdir()] == ["materials.sqlite"]


@pytest.mark.parametrize("filled", [False, True])
def test_a_kept_file_is_closed_once_no_session_holds_it_and_opened_again_without_a_fill(
    tmp_path: Path, *, filled: bool
) -> None:
    """E.g. a test per state folder: a process holds no file that no session reads."""
    path = tmp_path / "book.sqlite"
    fills: list[None] = []

    def fill(database: Book, _job: Job[None, Any]) -> None:
        fills.append(None)
        database.names.add("filled")

    model_type = _pickups_model(fill, location=path) if filled else _book_model(path)
    main_view = MainView()

    def opened() -> tuple[DatabaseModel, Book]:
        model = model_type()
        book: Book = model.pickups if isinstance(model, _PickupsModel) else model.book
        main_view.jobs.start(book.ready)
        main_view.jobs.wait()
        return model, book

    alice, alice_book = opened()
    bob, _ = opened()
    alice_book.names.add("Ada")
    alice.close()
    assert (tmp_path / "book.sqlite-wal").exists()  # bob still holds it
    bob.close()
    # SQLite removes its -wal and -shm files as the file's last connection closes
    assert [file.name for file in tmp_path.iterdir()] == ["book.sqlite"]

    carol, carol_book = opened()
    with closing(carol):
        assert carol_book.names.texts() == (["filled", "Ada"] if filled else ["Ada"])
        assert len(fills) == (1 if filled else 0)


def test_a_callable_location_gives_each_model_the_file_of_its_time(tmp_path: Path) -> None:
    """E.g. a state folder that the app reads as it starts, and that each test sets."""
    for name in ("first", "second"):
        (tmp_path / name).mkdir()
    folder = tmp_path / "first"
    model_type = _book_model(lambda: folder / "book.sqlite")
    alice = model_type()
    alice.book.names.add("Ada")
    folder = tmp_path / "second"
    with closing(model_type()) as bob:
        bob.book.names.add("Bob")
        alice.book.names.add("Alan")  # alice keeps the file she was built with
        assert bob.book.names.texts() == ["Bob"]
    alice.close()

    folder = tmp_path / "first"
    with closing(model_type()) as carol:
        assert carol.book.names.texts() == ["Ada", "Alan"]


def test_a_kept_file_opened_again_waits_for_no_late_write_and_is_told_of_it(
    tmp_path: Path,
) -> None:
    """E.g. a job of a web session that expired, ending after its file was opened again."""
    model_type = _book_model(tmp_path / "book.sqlite")
    alice = model_type()
    writing, release = threading.Event(), threading.Event()

    def write() -> None:
        with alice.book.names.connection() as db:
            db.execute("INSERT INTO name VALUES ('late')")
            writing.set()
            assert release.wait(_TIMEOUT)

    writer = threading.Thread(target=write)
    writer.start()
    try:
        assert writing.wait(_TIMEOUT)
        alice.close()  # its last session: the file closes once the write ends
        with closing(model_type()) as bob:
            assert writer.is_alive()  # opened while the write is held, not once it gave up
            seen = _Seen(bob)
            release.set()
            writer.join(_TIMEOUT)
            seen.wait_for("late")
    finally:
        release.set()
        writer.join(_TIMEOUT)


def test_a_fill_runs_once_for_every_session_one_closed_meanwhile_included() -> None:
    entered, release = threading.Event(), threading.Event()
    fills: list[None] = []

    def fill(database: Book, _job: Job[None, Any]) -> None:
        fills.append(None)
        entered.set()
        assert release.wait(_TIMEOUT)
        database.names.add("filled")

    model_type = _pickups_model(fill)
    main_view = MainView()
    with closing(model_type()) as alice, closing(model_type()) as bob:
        with pytest.raises(RuntimeError, match="isn't filled yet: call its ready"):
            alice.pickups.names.texts()
        main_view.jobs.start(alice.pickups.ready)
        assert entered.wait(_TIMEOUT)
        main_view.jobs.start(bob.pickups.ready)
        alice.close()  # its ready gets the file, which another session keeps
        release.set()
        main_view.jobs.wait()

        assert bob.pickups.names.texts() == ["filled"]
        with closing(model_type()) as carol:
            main_view.jobs.start(carol.pickups.ready)
            main_view.jobs.wait()
            assert carol.pickups.names.texts() == ["filled"]
        assert len(fills) == 1


@pytest.mark.parametrize(("outcome", "kept"), [("canceled", True), ("failed", False)])
def test_a_fill_that_stops_leaves_no_file_and_the_next_ready_fills_again(
    tmp_path: Path, outcome: str, *, kept: bool
) -> None:
    entered, release = threading.Event(), threading.Event()
    attempts: list[None] = []

    def fill(database: Book, job: Job[None, Any]) -> None:
        attempts.append(None)
        if len(attempts) > 1:
            database.names.add("whole")
            return
        database.names.add("half")
        entered.set()
        if outcome == "canceled":
            assert not job.sleep(_TIMEOUT)  # until its last session stops waiting
            return  # early, without raising, as a fill may
        assert release.wait(_TIMEOUT)
        msg = "the network went down"
        raise OSError(msg)

    path = tmp_path / "pickups.sqlite"
    model_type = _pickups_model(fill, location=path if kept else None)
    main_view = MainView()
    with closing(model_type()) as model:
        failures: list[Exception] = []
        job = main_view.jobs.start(model.pickups.ready)
        job.failed.connect(failures.append)
        assert entered.wait(_TIMEOUT)
        if outcome == "canceled":
            job.cancel()  # its last session stops waiting: the fill no longer counts
        release.set()
        main_view.jobs.wait()
        if outcome == "failed":  # each session waiting gets the fill's error
            assert [type(error) for error in failures] == [OSError]
        assert not path.exists()

        main_view.jobs.start(model.pickups.ready)
        main_view.jobs.wait()

        assert model.pickups.names.texts() == ["whole"]
        assert len(attempts) == 2
    # the canceled fill's thread ends on its own, once it has removed its file
    deadline = time.monotonic() + _TIMEOUT
    while any(".partial" in file.name for file in tmp_path.iterdir()):
        assert time.monotonic() < deadline, list(tmp_path.iterdir())
        time.sleep(0.05)


def _file_of(database: SqliteDatabase) -> Path:
    with database.reading() as db:
        (_, _, name) = db.execute("PRAGMA database_list").fetchone()
    return Path(name)


def test_forget_fills_a_new_file_for_the_next_sessions_and_deletes_the_old_after_use() -> None:
    fills: list[None] = []

    def fill(database: Book, _job: Job[None, Any]) -> None:
        fills.append(None)
        database.names.add(f"fill {len(fills)}")

    model_type = _pickups_model(fill)
    main_view = MainView()
    alice = model_type()
    main_view.jobs.start(alice.pickups.ready)
    main_view.jobs.wait()
    first_file = _file_of(alice.pickups)

    alice.pickups.forget()
    with closing(model_type()) as bob, closing(model_type()) as carol:
        main_view.jobs.start(bob.pickups.ready)
        main_view.jobs.wait()
        main_view.jobs.start(carol.pickups.ready)
        main_view.jobs.wait()

        assert alice.pickups.names.texts() == ["fill 1"]
        assert bob.pickups.names.texts() == carol.pickups.names.texts() == ["fill 2"]
        assert first_file.exists()
        alice.close()
        assert not first_file.exists()


def test_a_session_whose_fill_was_forgotten_and_closed_before_it_got_the_file_fills_again() -> None:
    """A fill forgotten as it runs is kept by no session but those that got it."""
    entered, release = threading.Event(), threading.Event()
    fills: list[None] = []

    def fill(database: Book, job: Job[None, Any]) -> None:
        fills.append(None)
        job.report_progress(0)
        if len(fills) == 1:
            entered.set()
            assert release.wait(_TIMEOUT)
        database.names.add(f"fill {len(fills)}")
        job.report_progress(1)

    bob_waits, bob_held, bob_resumed = threading.Event(), threading.Event(), threading.Event()
    bob_reports: list[None] = []

    def hand_over_to_bob(_job: Job[Any, Any], callback: Callable[[], None]) -> None:
        callback()
        bob_reports.append(None)
        if len(bob_reports) == 1:  # the fill's first progress: bob waits for it
            bob_waits.set()
        elif len(bob_reports) == 2:  # its last: the fill is over, bob hasn't got its file
            bob_held.set()
            assert bob_resumed.wait(_TIMEOUT)

    model_type = _pickups_model(fill)
    with closing(model_type()) as alice, closing(model_type()) as bob:
        alice_ready = threading.Thread(
            target=alice.pickups.ready, args=(Job(lambda _job, callback: callback()),)
        )
        bob_ready = threading.Thread(target=bob.pickups.ready, args=(Job(hand_over_to_bob),))
        try:
            alice_ready.start()
            assert entered.wait(_TIMEOUT)
            bob_ready.start()
            assert bob_waits.wait(_TIMEOUT)
            alice.pickups.forget()  # the file filling is no longer the next sessions'
            release.set()
            alice_ready.join(_TIMEOUT)
            assert bob_held.wait(_TIMEOUT)
            alice.close()  # its last session: the file goes
        finally:
            release.set()
            bob_resumed.set()
            alice_ready.join(_TIMEOUT)
            bob_ready.join(_TIMEOUT)

        assert bob.pickups.names.texts() == ["fill 2"]
        assert len(fills) == 2


def test_forget_gives_the_next_sessions_a_new_database_without_a_fill_too() -> None:
    model_type = _book_model()
    with closing(model_type()) as alice:
        alice.book.forget()  # none yet but its own: the next session's is new
        alice.book.names.add("Ada")
        alice.book.forget()
        with closing(model_type()) as bob:
            bob.book.names.add("Bob")

            assert (alice.book.names.texts(), bob.book.names.texts()) == (["Ada"], ["Bob"])


def test_a_read_only_database_refuses_a_session_s_write_but_not_its_fill() -> None:
    def fill(database: Book, _job: Job[None, Any]) -> None:
        database.names.add("filled")

    model_type = _pickups_model(fill, read_only=True)
    main_view = MainView()
    with closing(model_type()) as model:
        main_view.jobs.start(model.pickups.ready)
        main_view.jobs.wait()

        with pytest.raises(ReadOnlyDatabaseError, match="is shared read-only"):
            model.pickups.names.add("written")
        with pytest.raises(ReadOnlyDatabaseError), model.pickups.reading() as db:
            db.execute("DELETE FROM name")
        # another error is the query's own
        with pytest.raises(sqlite3.OperationalError) as caught, model.pickups.connection() as db:
            db.execute("SELECT * FROM nowhere")
        assert not isinstance(caught.value, ReadOnlyDatabaseError)
        assert model.pickups.names.texts() == ["filled"]
        with model.pickups.reading() as db:  # e.g. a large table's rows
            assert db.execute("SELECT text FROM name").fetchall() == [("filled",)]
            assert not db.in_transaction  # the reader a refused write used, reused


class _Filled(Book):
    @override
    def fill(self, job: Job[None, Any]) -> None:
        self.names.add("filled")


def _refused_per_session_fill(_tmp_path: Path) -> None:
    type("Refused", (DatabaseModel,), {"study": per_session(_Filled)})


def _refused_twice_shared(tmp_path: Path) -> None:
    path = tmp_path / "book.sqlite"
    fields = {"one": shared(Book, location=path), "other": shared(Book, location=lambda: path)}
    type("Refused", (DatabaseModel,), fields)()


def _refused_shared_file(tmp_path: Path) -> None:
    class OtherBook(Book):
        pass

    first = type("First", (DatabaseModel,), {"book": shared(Book, location=tmp_path / "a")})
    second = type("Second", (DatabaseModel,), {"book": shared(OtherBook, location=tmp_path / "a")})
    with closing(first()):
        second()


def _refused_shared_table(_tmp_path: Path) -> None:
    with closing(_book_model()()) as model:
        model.book.add_table(Names)


def _refused_per_session_forget(_tmp_path: Path) -> None:
    with closing(_book_model()()) as model:
        model.study.forget()


def _refused_kept_forget(tmp_path: Path) -> None:
    with closing(_book_model(tmp_path / "book.sqlite")()) as model:
        model.book.forget()


@pytest.mark.parametrize(
    ("act", "error", "message"),
    [
        (_refused_per_session_fill, TypeError, "is a per_session database with a fill"),
        (_refused_twice_shared, TypeError, r"in several fields \(one, other\): one is enough"),
        (_refused_shared_file, ValueError, "is shared already, by another class"),
        (_refused_shared_table, TypeError, "is shared: its tables are created once"),
        (_refused_per_session_forget, TypeError, "A per_session database forgets nothing"),
        (_refused_kept_forget, TypeError, "only a shared database in a temporary file"),
    ],
)
def test_a_misuse_of_a_shared_database_is_refused_with_why(
    tmp_path: Path, act: Callable[[Path], None], error: type[Exception], message: str
) -> None:
    with pytest.raises(error, match=message):
        act(tmp_path)


def _book_app(
    model_type: type[_BookModel],
) -> tuple[ModelApplication[_SummaryMainView, _BookModel], list[threading.Thread]]:
    """Get an app whose summary shows the shared names, and the threads that showed them."""
    threads: list[threading.Thread] = []

    def show_names(main_view: _SummaryMainView, model: _BookModel) -> None:
        def show() -> None:
            main_view.summary.text = ", ".join(model.book.names.texts())
            threads.append(threading.current_thread())

        model.book.names.changed.connect(show)

    app = ModelApplication(
        build_main_view=_SummaryMainView, build_model=model_type, setup_model=show_names
    )
    return app, threads


def test_jobs_wait_emits_another_session_s_write_with_no_job_running() -> None:
    """E.g. a test checking that a page shows another session's write: no toolkit runs."""
    model_type = _book_model()
    app, threads = _book_app(model_type)
    main_view = app.main_view
    with closing(model_type()) as writer:
        try:
            writer.book.names.add("Ada")
            main_view.jobs.wait()
            assert main_view.summary.text == "Ada"
            assert threads == [threading.main_thread()]
        finally:
            app.model.close()


@pytest.mark.parametrize("closed", [False, True])
def test_jobs_wait_waits_for_a_notice_on_its_way_as_the_jobs_end(
    monkeypatch: pytest.MonkeyPatch, *, closed: bool
) -> None:
    """The notice is still on its way once the last job's result is emitted.

    Closed meanwhile, the session is told no more: the wait ends without it.
    """
    model_type = _book_model()
    app, _ = _book_app(model_type)
    main_view = app.main_view
    held, released = threading.Event(), threading.Event()
    deliver = sqlitemodel._deliver  # noqa: SLF001 (holds the notice before it is posted)

    def held_deliver(handle: Any, indices: set[int]) -> None:
        held.set()
        assert released.wait(_TIMEOUT)
        deliver(handle, indices)

    monkeypatch.setattr(sqlitemodel, "_deliver", held_deliver)

    def release() -> None:
        if closed:
            app.model.close()
        released.set()

    shown = main_view.summary.text
    with closing(model_type()) as writer:
        try:
            writer.book.names.add("Ada")
            job = main_view.jobs.start(lambda _job: held.wait(_TIMEOUT))
            job.finished.connect(release)
            main_view.jobs.wait()
            assert released.is_set()  # by the job's callback: the notice was on its way
            assert main_view.summary.text == (shown if closed else "Ada")
        finally:
            released.set()
            app.model.close()


def test_on_qt_another_session_s_write_shows_on_the_main_thread_once_rendered(
    qtbot: QtBot,
) -> None:
    pytest.importorskip("qtpy")
    model_type = _book_model()
    app, threads = _book_app(model_type)
    main_view = app.main_view
    with closing(model_type()) as writer, closing(model_type()) as witness:
        seen = _Seen(witness)
        shown = main_view.summary.text
        try:
            # told before the window shows: it waits, as a job's result does
            writer.book.names.add("Ada")
            seen.wait_for("Ada")
            writer.book.names.add("Bob")
            seen.wait_for("Bob")
            _wait_for_notices(writer.book)  # the app's too, which wait for the window
            assert main_view.summary.text == shown
            main_view.render(RendererType.QT)
            qtbot.waitUntil(lambda: main_view.summary.text == "Ada, Bob")
            writer.book.names.add("Cy")
            qtbot.waitUntil(lambda: main_view.summary.text == "Ada, Bob, Cy")
            assert set(threads) == {threading.main_thread()}
        finally:
            app.model.close()


@pytest.mark.asyncio
async def test_on_textual_another_session_s_write_shows_on_the_app_s_thread() -> None:
    pytest.importorskip("textual")
    model_type = _book_model()
    app_views, threads = _book_app(model_type)
    main_view = app_views.main_view
    main_view.render(RendererType.TEXTUAL)
    textual_app = getattr(main_view.renderer, "app", None)
    assert textual_app is not None
    with closing(model_type()) as writer:
        try:
            async with textual_app.run_test() as pilot:
                await pilot.pause()
                writer.book.names.add("Ada")
                for _ in range(200):  # the store's thread hands it over, then the app runs it
                    await pilot.pause(0.05)
                    if main_view.summary.text == "Ada":
                        break
                assert main_view.summary.text == "Ada"
                assert set(threads) == {threading.main_thread()}
        finally:
            app_views.model.close()

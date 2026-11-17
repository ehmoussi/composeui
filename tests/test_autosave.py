"""Tests for the autosave of Qt and Textual apps (`composeui.core.autosave`)."""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import subprocess
import sys
import textwrap
import threading
import time
import types
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Optional

import attrs
import pytest

from composeui.core import autosave
from composeui.core.application import Application, ModelApplication
from composeui.core.autosave import (
    DIRECTORY_VARIABLE,
    Autosave,
    app_folder_name,
    data_directory,
)
from composeui.core.model import Model
from composeui.core.reload import RELOADED_VARIABLE
from composeui.core.sqlitemodel import SqliteModel, SqliteTable, table
from composeui.core.study import save_study
from composeui.core.view import InputView, MainView, define_view

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from composeui.core.jobs import Job

#: seconds a test waits at most for a thread or a process
_TIMEOUT = 30.0


class Notes(SqliteTable):
    create = "CREATE TABLE notes (text TEXT NOT NULL)"


class NotesModel(SqliteModel):
    notes = table(Notes)

    def add(self, text: str) -> None:
        with self.connection(changing=self.notes) as db:
            db.execute("INSERT INTO notes VALUES (?)", (text,))

    def texts(self) -> list[str]:
        with self.reading() as db:
            return [text for (text,) in db.execute("SELECT text FROM notes ORDER BY rowid")]


@define_view
class NotesMainView(MainView):
    extension = ".notes"
    autosave = True
    app_id: ClassVar[Optional[str]] = "notes"
    # ticked by the tests themselves
    autosave_interval = 3600.0

    note: InputView = attrs.Factory(InputView)
    title_input: InputView = attrs.Factory(InputView)


@define_view
class _UnnamedNotesMainView(NotesMainView):
    """The notes' main view without an `app_id`: its folder is named after it."""

    app_id = None


class _AutosavingApplication(ModelApplication[NotesMainView, NotesModel]):
    """The app as a backend runs it, without a window: the tests tick it."""

    can_autosave = True


class _AutosavingViewsApplication(Application[NotesMainView]):
    can_autosave = True


#: whether the tests' apps answer Restore to the question as they start, as the user would
_ANSWERS_RESTORE = True


@pytest.fixture
def asking(monkeypatch: pytest.MonkeyPatch) -> None:
    """Leave the question about the work left open, for the test to answer."""
    monkeypatch.setattr(sys.modules[__name__], "_ANSWERS_RESTORE", False)


@pytest.fixture(autouse=True)
def autosaves(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Keep every autosave in the test's own folder, never the user's; release each at the end.

    Released, as the system does at a crash: Windows deletes no folder whose lock is open.
    The apps answer Restore to the question about the work left, unless the test is `asking`.
    """
    folder = tmp_path / "autosaves"
    monkeypatch.setenv(DIRECTORY_VARIABLE, str(folder))
    monkeypatch.setattr("sys.argv", ["notes"])
    started: list[Autosave] = []
    start = Autosave.start.__func__  # type: ignore[attr-defined]

    def start_kept(
        cls: type[Autosave], main_view: MainView, model: Model | None, *, restores: bool
    ) -> Autosave | None:
        autosave = start(cls, main_view, model, restores=restores)
        if autosave is not None:
            started.append(autosave)
        return autosave

    start_app = Application._start  # noqa: SLF001 (what each backend's run calls)

    def start_and_ask(app: Application[MainView]) -> None:
        start_app(app)
        autosave = app.main_view._autosave  # noqa: SLF001
        if autosave is not None:
            autosave.ask_restore()  # as a backend does, once it shows the main view
            if _ANSWERS_RESTORE:  # ignored unless it asked
                app.main_view.restore_work.accept()

    monkeypatch.setattr(Autosave, "start", classmethod(start_kept))
    monkeypatch.setattr(Application, "_start", start_and_ask)
    yield folder
    for kept in started:
        kept.close(clean=False)


@pytest.fixture
def apps() -> Iterator[Callable[[], _AutosavingApplication]]:
    """Start apps, as many as the test runs; each one's model is closed at the end."""
    started: list[_AutosavingApplication] = []

    def start() -> _AutosavingApplication:
        app = _AutosavingApplication(build_main_view=NotesMainView, build_model=NotesModel)
        started.append(app)
        app.run()
        return app

    yield start
    for app in started:
        _autosave_of(app.main_view).wait()
        app.model.close()


def _autosave_of(main_view: MainView) -> Autosave:
    autosave = main_view._autosave  # noqa: SLF001 (the app's start took it)
    assert autosave is not None
    return autosave


def _tick(main_view: MainView) -> None:
    """Tick the autosave, and wait for the snapshot it writes."""
    autosave = _autosave_of(main_view)
    autosave.tick()
    autosave.wait()


def _crash(app: Application[NotesMainView]) -> None:
    """End the app as a crash does: the folder stays, its lock released by the system."""
    _autosave_of(app.main_view).close(clean=False)


def _folder_of(main_view: MainView) -> Path:
    """Get the folder of the app's own instance."""
    return _autosave_of(main_view)._folder.path  # noqa: SLF001


def _instances(folder: Path) -> list[Path]:
    """Get the instances' folders of the notes app, left or running."""
    return sorted(path for path in (folder / "notes").iterdir() if path.is_dir())


@pytest.fixture
def held_copy(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[threading.Event, threading.Event]]:
    """Hold the autosave's thread as it starts writing: (it started, let it go on)."""
    started, go_on = threading.Event(), threading.Event()
    write = autosave._write_synced  # noqa: SLF001

    def held_write(path: Path, content: bytes) -> None:
        if path.name.startswith("views-"):
            started.set()
            assert go_on.wait(_TIMEOUT)
        write(path, content)

    monkeypatch.setattr(autosave, "_write_synced", held_write)
    try:
        yield started, go_on
    finally:
        go_on.set()


def test_an_unclean_end_restores_the_unsaved_views_and_data_at_the_next_start(
    apps: Callable[[], _AutosavingApplication], tmp_path: Path
) -> None:
    first = apps()
    study = tmp_path / "mine.notes"
    save_study(first.main_view, first.model, study)
    first.main_view.note.text = "draft"
    first.model.add("first")
    _tick(first.main_view)

    assert first.main_view.has_unsaved_changes()  # an autosave is not the user's save
    assert first.main_view.state_filepath == study
    _crash(first)
    second = apps()

    assert second.main_view.note.text == "draft"
    assert second.model.texts() == ["first"]
    assert second.main_view.has_unsaved_changes()  # New, Open and Exit ask
    assert second.main_view.state_filepath == study  # the user's file, not the autosave
    question = second.main_view.restore_work.text  # answered Restore
    assert question.startswith("The app closed without saving. Restore the unsaved work of ")


def _show_title(job: Job[str]) -> str:
    """Read a title, as a job started with the app reads what the next start reads again."""
    del job
    return "read at the start"


def _build_titled_main_view() -> NotesMainView:
    main_view = NotesMainView()

    def start_reading() -> None:
        job = main_view.jobs.start(_show_title)
        job.finished.connect(lambda title: setattr(main_view.title_input, "text", title))

    main_view.loaded.connect(start_reading)
    return main_view


@pytest.mark.parametrize("is_changed", [False, True])
def test_save_after_a_restore_asks_before_it_replaces_a_file_changed_on_disk(
    apps: Callable[[], _AutosavingApplication], tmp_path: Path, is_changed: bool
) -> None:
    first = apps()
    study = tmp_path / "mine.notes"
    save_study(first.main_view, first.model, study)
    first.main_view.note.text = "draft"
    _tick(first.main_view)
    _crash(first)
    if is_changed:  # e.g. saved by another app since
        stat = study.stat()
        os.utime(study, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
    second = apps()

    second.main_view.file_menu.save.triggered.emit()

    assert second.main_view.replace_file.is_visible is is_changed
    assert second.main_view.has_unsaved_changes() is is_changed  # else saved into its file


def test_the_app_s_start_jobs_leave_the_restored_work_unsaved_and_autosaved() -> None:
    first = _AutosavingViewsApplication(build_main_view=_build_titled_main_view)
    first.run()
    first.main_view.jobs.wait()
    assert not first.main_view.has_unsaved_changes()  # the start's own result
    first.main_view.note.text = "draft"
    _tick(first.main_view)
    _crash(first)
    second = _AutosavingViewsApplication(build_main_view=_build_titled_main_view)
    second.run()
    second.main_view.jobs.wait()

    assert second.main_view.title_input.text == "read at the start"
    assert second.main_view.has_unsaved_changes()  # restored: still the user's to save
    _crash(second)  # without a tick: the restored snapshot is still there
    third = _AutosavingViewsApplication(build_main_view=_build_titled_main_view)
    third.run()
    assert third.main_view.note.text == "draft"


def test_a_snapshot_copies_what_a_job_started_with_the_study_wrote_since_the_last_one(
    apps: Callable[[], _AutosavingApplication],
) -> None:
    gate = threading.Event()

    def import_later(job: Job[None], model: NotesModel) -> None:
        del job
        assert gate.wait(_TIMEOUT)
        model.add("imported")

    def setup_model(main_view: NotesMainView, model: NotesModel) -> None:
        def start_import() -> None:
            main_view.jobs.start(import_later, model)

        main_view.loaded.connect(start_import)

    first = _AutosavingApplication(
        build_main_view=NotesMainView, build_model=NotesModel, setup_model=setup_model
    )
    try:
        first.run()
        first.main_view.note.text = "draft"
        _tick(first.main_view)  # without the import
        gate.set()
        first.main_view.jobs.wait()
        assert first.model.data_version == 0  # not a change of the user's
        _tick(first.main_view)
        _crash(first)
    finally:
        gate.set()
        first.model.close()
    second = apps()

    assert (second.main_view.note.text, second.model.texts()) == ("draft", ["imported"])


def test_each_snapshot_holds_the_views_and_the_data_of_the_same_moment(
    apps: Callable[[], _AutosavingApplication], caplog: pytest.LogCaptureFixture
) -> None:
    first = apps()
    folder = _folder_of(first.main_view)
    first.model.add("first")
    with caplog.at_level(logging.INFO, logger="COMPOSEUI"):
        _tick(first.main_view)
        first.main_view.note.text = "views only"  # the data copy of the previous snapshot stays
        _tick(first.main_view)
    _crash(first)

    assert [record.getMessage() for record in caplog.records] == [
        f"Autosaved the unsaved work in {folder}, the model's data included",
        f"Autosaved the unsaved work in {folder}",
    ]
    second = apps()

    assert (second.main_view.note.text, second.model.texts()) == ("views only", ["first"])
    second.model.add("second")
    _tick(second.main_view)
    _crash(second)
    third = apps()

    assert (third.main_view.note.text, third.model.texts()) == (
        "views only",
        ["first", "second"],
    )


def test_a_snapshot_copies_the_rows_of_its_tick_while_the_model_goes_on_writing(
    apps: Callable[[], _AutosavingApplication],
    held_copy: tuple[threading.Event, threading.Event],
) -> None:
    first = apps()
    first.model.add("at the tick")
    autosave = _autosave_of(first.main_view)
    started, go_on = held_copy
    autosave.tick()
    assert started.wait(_TIMEOUT)

    first.model.add("after the tick")  # not blocked by the snapshot being written
    first.main_view.note.text = "after the tick"
    autosave.tick()  # skipped: one snapshot at a time
    go_on.set()
    autosave.wait()
    _crash(first)
    second = apps()

    assert second.model.texts() == ["at the tick"]
    assert second.main_view.note.text == ""


@pytest.mark.parametrize("is_tick_after", [False, True])
def test_a_save_while_a_snapshot_is_written_leaves_no_work_to_restore(
    apps: Callable[[], _AutosavingApplication],
    held_copy: tuple[threading.Event, threading.Event],
    tmp_path: Path,
    is_tick_after: bool,
) -> None:
    first = apps()
    first.main_view.note.text = "draft"
    autosave = _autosave_of(first.main_view)
    started, go_on = held_copy
    autosave.tick()
    assert started.wait(_TIMEOUT)

    save_study(first.main_view, first.model, tmp_path / "mine.notes")
    go_on.set()
    autosave.wait()
    if is_tick_after:  # the study saved has no unsaved changes: nothing to write
        _tick(first.main_view)
    _crash(first)
    second = apps()

    assert second.main_view.note.text == ""
    assert not second.main_view.has_unsaved_changes()


def test_a_change_undone_deletes_the_snapshot_and_an_unchanged_study_writes_none(
    apps: Callable[[], _AutosavingApplication], autosaves: Path
) -> None:
    first = apps()
    folder = _folder_of(first.main_view)
    _tick(first.main_view)
    assert [path for path in folder.iterdir() if not path.name.startswith("lock.")] == []

    first.main_view.note.text = "draft"
    _tick(first.main_view)
    written = sorted(folder.iterdir())
    _tick(first.main_view)
    assert sorted(folder.iterdir()) == written  # no change since: nothing written
    first.main_view.note.text = ""
    _tick(first.main_view)
    _crash(first)
    second = apps()

    assert not second.main_view.has_unsaved_changes()
    # the folder left without a snapshot is deleted
    assert _instances(autosaves) == [_folder_of(second.main_view)]


def test_a_close_waits_for_the_snapshot_being_written_then_deletes_the_folder(
    apps: Callable[[], _AutosavingApplication],
    held_copy: tuple[threading.Event, threading.Event],
    autosaves: Path,
) -> None:
    first = apps()
    first.main_view.note.text = "draft"
    autosave = _autosave_of(first.main_view)
    started, go_on = held_copy
    autosave.tick()
    assert started.wait(_TIMEOUT)

    closing = threading.Thread(target=autosave.close, kwargs={"clean": True})
    closing.start()
    closing.join(0.1)
    assert closing.is_alive()  # waits for the snapshot
    assert _folder_of(first.main_view).exists()
    go_on.set()
    closing.join(_TIMEOUT)

    assert not closing.is_alive()
    assert _instances(autosaves) == []
    second = apps()
    assert second.main_view.note.text == ""


def test_a_failed_snapshot_keeps_the_previous_one_says_so_and_the_next_tick_tries_again(
    apps: Callable[[], _AutosavingApplication], monkeypatch: pytest.MonkeyPatch
) -> None:
    first = apps()
    first.main_view.note.text = "kept"
    _tick(first.main_view)
    write = autosave._write_synced  # noqa: SLF001

    def full_disk(*_written: object) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(autosave, "_write_synced", full_disk)
    first.main_view.note.text = "lost"
    _tick(first.main_view)
    monkeypatch.setattr(autosave, "_write_synced", write)
    first.main_view.note.text = "written again"
    _tick(first.main_view)

    assert first.main_view.status_bar.message == (
        "Can't autosave the unsaved work: [Errno 28] No space left on device."
    )
    folder = _folder_of(first.main_view)
    assert len(list(folder.glob("views-*"))) == 1  # the failed one's files are deleted
    _crash(first)
    second = apps()
    assert second.main_view.note.text == "written again"


def test_a_failed_snapshot_keeps_the_previous_one_also_when_it_never_reaches_the_record(
    apps: Callable[[], _AutosavingApplication], monkeypatch: pytest.MonkeyPatch
) -> None:
    first = apps()
    first.main_view.note.text = "kept"
    _tick(first.main_view)
    write = autosave._write_synced  # noqa: SLF001

    def crash_before_the_record(path: Path, content: bytes) -> None:
        if path.name.endswith(".partial"):
            raise OSError(5, "Input/output error")
        write(path, content)

    monkeypatch.setattr(autosave, "_write_synced", crash_before_the_record)
    first.main_view.note.text = "lost"
    _tick(first.main_view)
    _crash(first)
    second = apps()

    assert second.main_view.note.text == "kept"


class _UncountedJsonModel(Model):
    """A model with data of its own that can't be pinned, and doesn't count its changes."""

    data_name: ClassVar[Optional[str]] = "data.json"

    def __init__(self) -> None:
        self.texts: list[str] = []
        self.fails = False

    def save_data(self, path: Path) -> None:
        if self.fails:
            raise OSError(28, "No space left on device")
        path.write_text(json.dumps(self.texts))

    def open_data(self, path: Path) -> None:
        self.texts = json.loads(path.read_text())


class _JsonModel(_UncountedJsonModel):
    """A model with data that can't be pinned, copied on the main thread when it changed."""

    def __init__(self) -> None:
        super().__init__()
        self.version = 0

    @property
    def data_version(self) -> int:
        return self.version


class _JsonApplication(ModelApplication[NotesMainView, _UncountedJsonModel]):
    can_autosave = True


def test_a_model_s_data_that_can_t_be_pinned_is_copied_at_the_tick() -> None:
    model = _JsonModel()
    first = _JsonApplication(build_main_view=NotesMainView, build_model=lambda: model)
    first.run()
    model.texts, model.version = ["first"], 1
    first.model.fails = True
    _tick(first.main_view)
    assert first.main_view.status_bar.message == ""  # shown at the next tick
    first.model.fails = False
    _tick(first.main_view)
    assert first.main_view.status_bar.message == (
        "Can't autosave the unsaved work: [Errno 28] No space left on device."
    )
    _crash(first)
    second = _JsonApplication(build_main_view=NotesMainView, build_model=_JsonModel)
    second.run()

    assert second.model.texts == ["first"]


def test_a_model_that_doesn_t_count_its_changes_is_copied_at_each_snapshot() -> None:
    first = _JsonApplication(build_main_view=NotesMainView, build_model=_UncountedJsonModel)
    first.run()
    for text in ("first", "second"):
        first.model.texts.append(text)
        first.main_view.note.text = text  # a change Save sees
        _tick(first.main_view)
    _crash(first)
    second = _JsonApplication(build_main_view=NotesMainView, build_model=_UncountedJsonModel)
    second.run()

    assert second.model.texts == ["first", "second"]


def _crashed_with_draft() -> Path:
    """Run an app that ends as a crash does, with a snapshot of a draft; get its folder."""
    app = _AutosavingViewsApplication(build_main_view=NotesMainView)
    app.run()
    app.main_view.note.text = "draft"
    _tick(app.main_view)
    _crash(app)
    return _folder_of(app.main_view)


def _started() -> _AutosavingViewsApplication:
    app = _AutosavingViewsApplication(build_main_view=NotesMainView)
    app.run()
    return app


@pytest.mark.usefixtures("asking")
def test_the_work_of_a_crash_is_asked_about_and_discard_deletes_it(autosaves: Path) -> None:
    left = _crashed_with_draft()
    second = _started()
    question = second.main_view.restore_work

    assert question.is_visible
    assert second.main_view.note.text == ""  # nothing restored before the answer
    question.reject()  # Discard
    assert second.main_view.note.text == ""
    assert not question.is_visible
    assert _instances(autosaves) == [left]  # this app's own now, without the work
    _crash(second)
    assert not _started().main_view.restore_work.is_visible


@pytest.mark.usefixtures("asking")
def test_closing_the_question_keeps_the_work_for_the_next_start(autosaves: Path) -> None:
    left = _crashed_with_draft()
    second = _started()

    second.main_view.restore_work.dismiss()  # e.g. Escape
    second.main_view.note.text = "second's own"
    _tick(second.main_view)
    _autosave_of(second.main_view).close(clean=True)

    assert _instances(autosaves) == [left]
    third = _started()
    third.main_view.restore_work.accept()
    assert third.main_view.note.text == "draft"


@pytest.mark.usefixtures("asking")
def test_nothing_is_written_nor_deleted_until_the_question_is_answered() -> None:
    left = _crashed_with_draft()
    files = sorted(left.iterdir())
    second = _started()

    second.main_view.note.text = "before the answer"
    _tick(second.main_view)
    _autosave_of(second.main_view).close(clean=True)  # e.g. the window closed

    assert sorted(left.iterdir()) == files
    third = _started()
    third.main_view.restore_work.accept()
    assert third.main_view.note.text == "draft"


class _ReloadingApplication(_AutosavingViewsApplication):
    """The app with the backends' ``--reload`` option."""

    def __init__(self, *, build_main_view: Callable[[], NotesMainView]) -> None:
        super().__init__(build_main_view=build_main_view)
        self._parser.add_argument("--reload", action="store_true")


@pytest.mark.parametrize("process", ["supervisor", "reloaded app"])
def test_an_app_under_reload_doesn_t_autosave_nor_touch_the_work_left(
    process: str, autosaves: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    left = _crashed_with_draft()
    files = sorted(left.iterdir())
    if process == "supervisor":
        monkeypatch.setattr("sys.argv", ["notes", "--reload"])
    else:  # the process the supervisor runs, which saves the study between two runs itself
        monkeypatch.setenv(RELOADED_VARIABLE, str(autosaves.parent))
    app = _ReloadingApplication(build_main_view=NotesMainView)

    app.run()

    assert app.main_view._autosave is None  # noqa: SLF001
    assert not app.main_view.restore_work.is_visible
    assert _instances(autosaves) == [left]
    assert sorted(left.iterdir()) == files


def test_an_app_closed_before_it_asked_about_the_work_left_keeps_it(autosaves: Path) -> None:
    left = _crashed_with_draft()
    main_view = NotesMainView()
    autosave = Autosave.start(main_view, None, restores=True)  # e.g. Textual, not yet mounted
    assert autosave is not None

    autosave.close(clean=True)

    assert _instances(autosaves) == [left]
    third = _started()
    assert third.main_view.note.text == "draft"


def test_a_folder_whose_lock_isn_t_a_database_is_left_alone() -> None:
    damaged = _crashed_with_draft()
    (damaged / "lock.sqlite").write_bytes(b"not a database, e.g. cut by a full disk" * 100)
    files = sorted(damaged.iterdir())
    app = _started()

    assert app.main_view.note.text == ""  # not taken: as if its app ran
    app.main_view.note.text = "own"
    _tick(app.main_view)
    assert _folder_of(app.main_view) != damaged
    assert sorted(damaged.iterdir()) == files


def test_a_running_app_s_folder_is_never_restored_by_another_one() -> None:
    first = _AutosavingViewsApplication(build_main_view=NotesMainView)
    first.run()
    first.main_view.note.text = "first's"
    _tick(first.main_view)
    second = _AutosavingViewsApplication(build_main_view=NotesMainView)
    second.run()

    assert second.main_view.note.text == ""
    assert _folder_of(second.main_view) != _folder_of(first.main_view)
    _crash(first)
    third = _AutosavingViewsApplication(build_main_view=NotesMainView)
    third.run()
    assert third.main_view.note.text == "first's"


def test_of_several_folders_left_the_newest_opens_and_the_next_start_opens_the_other() -> None:
    texts = ["older", "newer"]
    running = []
    for text in texts:  # both running, then both ended
        app = _AutosavingViewsApplication(build_main_view=NotesMainView)
        app.run()
        app.main_view.note.text = text
        _tick(app.main_view)
        running.append(app)
    for stamp, app in enumerate(running, start=int(time.time())):
        _crash(app)
        # a second apart: the file systems' times may be that coarse
        os.utime(_folder_of(app.main_view) / "record.json", (stamp, stamp))

    restored = []
    for _ in texts:
        app = _AutosavingViewsApplication(build_main_view=NotesMainView)
        app.run()
        restored.append(app.main_view.note.text)
        _autosave_of(app.main_view).close(clean=True)

    assert restored == ["newer", "older"]


@pytest.mark.parametrize(
    ("file_name", "content"),
    [
        ("views", "not json"),
        ("views", json.dumps({"composeui": {"format": 99}, "app": {"version": 1}, "views": {}})),
        ("record.json", "not json"),
        ("record.json", "[]"),
        # a name out of the folder, whose file would open
        ("record.json", json.dumps({"views": "../views.json", "data": "DATA", "study": None})),
        # without the model's data
        ("record.json", json.dumps({"views": "views.json", "data": None, "study": None})),
    ],
)
def test_work_that_doesn_t_open_is_moved_aside_and_the_app_starts_a_new_study(
    apps: Callable[[], _AutosavingApplication], autosaves: Path, file_name: str, content: str
) -> None:
    first = apps()
    first.main_view.note.text = "draft"
    _tick(first.main_view)
    folder = _folder_of(first.main_view)
    _crash(first)
    (views,) = folder.glob("views-*")
    (data,) = folder.glob("data-*")
    (folder.parent / "views.json").write_bytes(views.read_bytes())
    path = views if file_name == "views" else folder / file_name
    path.write_text(content.replace("DATA", data.name))
    second = apps()

    assert second.main_view.note.text == ""
    assert second.main_view.status_bar.message.startswith("Can't restore the unsaved work: ")
    assert not second.main_view.has_unsaved_changes()
    (aside,) = (autosaves / "notes").glob(f"{folder.name}.invalid-*")
    assert path.name in {p.name for p in aside.iterdir()}
    assert _instances(autosaves) == sorted([aside, _folder_of(second.main_view)])
    second.main_view.note.text = "next"
    _tick(second.main_view)
    _crash(second)
    assert apps().main_view.note.text == "next"  # its own new folder


@pytest.mark.parametrize("cause", ["held too long", "not a file"])
def test_an_app_that_can_t_take_its_folder_runs_without_autosave(
    autosaves: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, cause: str
) -> None:
    app_folder = autosaves / "notes"
    app_folder.mkdir(parents=True)
    starting = None
    if cause == "held too long":  # another app looking for folders
        starting = sqlite3.connect(str(app_folder / ".lock.sqlite"), isolation_level=None)
        starting.execute("BEGIN EXCLUSIVE")
        monkeypatch.setattr(autosave, "_APP_LOCK_WAIT", 0.0)
    else:
        (app_folder / ".lock.sqlite").mkdir()
    try:
        app = _AutosavingViewsApplication(build_main_view=NotesMainView)
        app.run()
    finally:
        if starting is not None:
            starting.close()

    assert app.main_view._autosave is None  # noqa: SLF001
    assert "The app doesn't autosave: " in caplog.text


def test_work_that_doesn_t_open_nor_move_aside_waits_for_the_next_start(
    apps: Callable[[], _AutosavingApplication],
    autosaves: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    first = apps()
    first.main_view.note.text = "draft"
    _tick(first.main_view)
    folder = _folder_of(first.main_view)
    _crash(first)
    (views,) = folder.glob("views-*")
    views.write_text("not json")
    replace = Path.replace

    def refused(path: Path, target: Path) -> Path:
        if ".invalid-" in Path(target).name:
            raise PermissionError(13, "Permission denied")
        return replace(path, target)

    monkeypatch.setattr(Path, "replace", refused)
    second = apps()
    second.main_view.note.text = "not autosaved"
    _tick(second.main_view)
    _autosave_of(second.main_view).close(clean=True)

    assert second.main_view.note.text == "not autosaved"
    assert "The app doesn't autosave: [Errno 13] Permission denied" in caplog.text
    assert _instances(autosaves) == [folder]  # as it was
    assert views.read_text() == "not json"
    monkeypatch.setattr(Path, "replace", replace)
    third = apps()
    assert third.main_view.note.text == ""
    assert any(p.name.startswith(f"{folder.name}.invalid-") for p in _instances(autosaves))


@pytest.mark.usefixtures("asking")
def test_f_opens_its_file_and_the_next_start_asks_about_the_work_left(
    apps: Callable[[], _AutosavingApplication], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = apps()
    study = tmp_path / "mine.notes"
    first.main_view.note.text = "saved"
    save_study(first.main_view, first.model, study)
    first.main_view.note.text = "draft"
    _tick(first.main_view)
    _crash(first)
    monkeypatch.setattr("sys.argv", ["notes", "-f", str(study)])
    for _ in range(2):  # each start with a file asks nothing
        with_file = apps()
        assert with_file.main_view.note.text == "saved"
        assert not with_file.main_view.restore_work.is_visible
        with_file.main_view.note.text = "edited"
        _tick(with_file.main_view)
        _autosave_of(with_file.main_view).close(clean=True)
    monkeypatch.setattr("sys.argv", ["notes"])
    third = apps()

    assert third.main_view.restore_work.is_visible
    third.main_view.restore_work.accept()
    assert third.main_view.note.text == "draft"


def test_an_app_starting_as_another_closes_cleanly_restores_nothing_of_it(
    apps: Callable[[], _AutosavingApplication], monkeypatch: pytest.MonkeyPatch
) -> None:
    first = apps()
    first.main_view.note.text = "discarded"
    _tick(first.main_view)
    starting: list[_AutosavingApplication] = []
    rmtree = autosave.shutil.rmtree

    def start_another_first(path: Path, *, ignore_errors: bool) -> None:
        # once: the folder's lock released, the folder not deleted yet
        monkeypatch.setattr(autosave.shutil, "rmtree", rmtree)
        starting.append(apps())
        rmtree(path, ignore_errors=ignore_errors)

    monkeypatch.setattr(autosave.shutil, "rmtree", start_another_first)
    _autosave_of(first.main_view).close(clean=True)

    (second,) = starting
    assert second.main_view.note.text == ""
    assert not second.main_view.has_unsaved_changes()


class ScriptMainView(MainView):
    """A main view of a script: its module is `__main__`, which any script's is."""

    __module__ = "__main__"


def test_a_script_s_folder_is_named_after_its_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def name_in(file: Path | None) -> str | None:
        script = types.ModuleType("__main__")
        if file is not None:
            script.__file__ = str(file)
        monkeypatch.setitem(sys.modules, "__main__", script)
        return app_folder_name(ScriptMainView)

    first = name_in(tmp_path / "app.py")
    assert first is not None
    assert first == name_in(tmp_path / "app.py")  # the next start finds it
    assert first != name_in(tmp_path / "other" / "app.py")  # another script's own
    assert re.fullmatch(r"ScriptMainView-[0-9a-f]{8}", first)
    assert name_in(None) is None  # e.g. python -c


def test_a_script_without_a_file_runs_without_autosave(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(_UnnamedNotesMainView, "__module__", "__main__")
    monkeypatch.setitem(sys.modules, "__main__", types.ModuleType("__main__"))  # e.g. python -c
    app = _AutosavingViewsApplication(build_main_view=_UnnamedNotesMainView)
    app.run()

    assert app.main_view._autosave is None  # noqa: SLF001
    assert "set its main view's app_id" in caplog.text


def test_an_app_id_names_the_folder_and_a_class_names_it_else() -> None:
    class OutOfFolderMainView(ScriptMainView):
        app_id = "../notes"

    class NamedMainView(ScriptMainView):
        app_id = "my-notes.2"

    class LocalMainView(MainView):  # in a function: `<locals>` in its name
        pass

    with pytest.raises(ValueError, match="can't name a folder"):
        app_folder_name(OutOfFolderMainView)
    assert app_folder_name(NamedMainView) == "my-notes.2"
    name = app_folder_name(LocalMainView)
    assert name is not None
    assert name.startswith(f"{__name__}.test_an_app_id_names_the_folder")
    assert re.fullmatch(r"[A-Za-z0-9._-]+", name)


@pytest.mark.parametrize(
    ("platform", "environ", "expected"),
    [
        ("linux", {}, Path.home() / ".local" / "share" / "composeui"),
        ("linux", {"XDG_DATA_HOME": "/data"}, Path("/data/composeui")),
        (
            "win32",
            {"LOCALAPPDATA": "C:/Users/me/AppData/Local"},
            Path("C:/Users/me/AppData/Local/composeui"),
        ),
        ("win32", {}, Path.home() / "AppData" / "Local" / "composeui"),
        (
            "darwin",
            {"XDG_DATA_HOME": "/data"},
            Path.home() / "Library" / "Application Support" / "composeui",
        ),
        ("darwin", {DIRECTORY_VARIABLE: "/tests"}, Path("/tests")),  # as it is
    ],
)
def test_the_folder_of_the_autosaves_is_the_user_s_data_directory(
    platform: str, environ: dict[str, str], expected: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.platform", platform)
    for variable in (DIRECTORY_VARIABLE, "XDG_DATA_HOME", "LOCALAPPDATA"):
        monkeypatch.delenv(variable, raising=False)
    for variable, value in environ.items():
        monkeypatch.setenv(variable, value)

    assert data_directory() == expected


@pytest.mark.asyncio
async def test_textual_doesn_t_tick_while_a_file_action_may_be_replacing_the_study() -> None:
    pytest.importorskip("textual_fspicker")
    from composeui.core.registry import RendererType  # noqa: PLC0415
    from composeui.textualcore._renderers.navigation import TextualMainRenderer  # noqa: PLC0415

    application = _AutosavingViewsApplication(build_main_view=NotesMainView)
    application.run()
    main_view = application.main_view
    main_view.note.text = "draft"
    main_view.render(RendererType.TEXTUAL)
    assert isinstance(main_view.renderer, TextualMainRenderer)
    app = main_view.renderer.app
    assert app is not None
    folder = _folder_of(main_view)

    async with app.run_test() as pilot:
        await pilot.press("ctrl+o")  # Open's worker waits for the picker
        for _ in range(100):
            await pilot.pause(0.05)
            if len(app.screen_stack) == 2:
                break
        assert len(app.screen_stack) == 2
        app.tick_autosave()
        _autosave_of(main_view).wait()
        assert not (folder / "record.json").exists()

        await pilot.press("escape")
        await app.workers.wait_for_complete()
        app.tick_autosave()
        _autosave_of(main_view).wait()
        assert (folder / "record.json").exists()


#: an app run as a script, without an `app_id`, autosaving every 50 ms, on the backend `BACKEND`
#: names. Without a question to answer, it writes a note, and ends once its snapshot is written,
#: as a crash does. Asked whether to restore the work left, it logs the question shown, answers
#: Restore, logs the note restored and closes cleanly
_APP = textwrap.dedent(
    """
    import os, pathlib
    import attrs
    from composeui.core.view import InputView, MainView, define_view

    @define_view
    class NotesMainView(MainView):
        extension = ".notes"
        autosave = True
        autosave_interval = 0.05
        note: InputView = attrs.Factory(InputView)

    autosaves = pathlib.Path(os.environ["COMPOSEUI_AUTOSAVE_DIR"])
    is_asked = any(autosaves.glob("*/*/record.json"))  # the work of a crash, left

    def log(text):
        with pathlib.Path(os.environ["RUNS_LOG"]).open("a") as file:
            file.write(f"{text}\\n")

    def crash_once_written():
        if any(autosaves.glob("*/*/record.json")):
            os._exit(3)

    if os.environ["BACKEND"] == "qt":
        from qtpy.QtCore import QTimer
        from qtpy.QtWidgets import QApplication, QMessageBox
        from composeui.qtcore.qtapplication import QtApplication as Base
    else:
        from composeui.textualcore.textualapplication import TextualApplication as Base

    class NotesApplication(Base):
        def render(self, renderer_type):
            super().render(renderer_type)
            main_view = self.main_view
            if os.environ["BACKEND"] == "qt":
                if not is_asked:
                    main_view.note.text = "draft"
                    self.timer = QTimer()
                    self.timer.timeout.connect(crash_once_written)
                    self.timer.start(20)
                    return

                def answer():
                    boxes = [
                        w for w in QApplication.topLevelWidgets()
                        if isinstance(w, QMessageBox) and w.isVisible()
                    ]
                    if not boxes:
                        return  # not shown yet
                    self.timer.stop()
                    (box,) = boxes
                    log(box.text())
                    (restore,) = [b for b in box.buttons() if b.text() == "Restore"]
                    restore.click()
                    log(main_view.note.text)
                    main_view.close()

                self.timer = QTimer()
                self.timer.timeout.connect(answer)
                self.timer.start(20)
            else:
                app = main_view.renderer.app
                if not is_asked:
                    def write():
                        main_view.note.text = "draft"
                        app.set_interval(0.02, crash_once_written)
                    app.mounted_callbacks.append(write)
                    return

                def answer():
                    if len(app.screen_stack) < 2 or not main_view.restore_work.is_visible:
                        return  # not shown yet, or answered
                    log(main_view.restore_work.text)
                    main_view.restore_work.accept()
                    log(main_view.note.text)
                    main_view.close()

                app.mounted_callbacks.append(lambda: app.set_interval(0.02, answer))

    NotesApplication(build_main_view=NotesMainView).run()
    """
)


@pytest.mark.parametrize("backend", ["qt", "textual"])
def test_a_desktop_app_ended_by_a_crash_opens_its_unsaved_work_at_the_next_start(
    backend: str, tmp_path: Path, autosaves: Path
) -> None:
    pytest.importorskip("qtpy.QtWidgets" if backend == "qt" else "textual")
    log = tmp_path / "runs.log"
    script = tmp_path / "app.py"
    script.write_text(_APP)
    env = {
        **os.environ,
        "BACKEND": backend,
        "RUNS_LOG": str(log),
        "QT_QPA_PLATFORM": "offscreen",
        # no terminal here
        "TEXTUAL_DRIVER": "textual.drivers.headless_driver:HeadlessDriver",
    }

    def run() -> int:
        return subprocess.run(  # noqa: S603
            [sys.executable, str(script)],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            timeout=_TIMEOUT,
            check=False,
        ).returncode

    assert run() == 3  # the crash
    assert run() == 0

    question, restored = log.read_text().splitlines()
    assert question.startswith("The app closed without saving. Restore the unsaved work of ")
    assert restored == "draft"
    (app_folder,) = autosaves.iterdir()  # the script's, named after its file
    assert app_folder.name.startswith("NotesMainView-")
    assert [path for path in app_folder.iterdir() if path.is_dir()] == []  # a clean close

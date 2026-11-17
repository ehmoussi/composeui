"""Crash cleanup preserves live owners, completed saves, and recovery snapshots."""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from composeui.core import _files
from composeui.core.application import Application
from composeui.core.model import Model
from composeui.core.sqlitemodel import SqliteModel
from composeui.core.study import open_study, save_study
from composeui.core.view import MainView
from composeui.webcore.files import SessionFiles

if TYPE_CHECKING:
    from collections.abc import Generator

    from composeui.core.jobs import Job

_WRITER = """
import json, os, pathlib, sys
from composeui.core.application import Application
from composeui.core.model import Model
from composeui.core.sqlitemodel import SqliteModel
from composeui.core.study import save_study
from composeui.core.view import (
    DOWNLOAD_CHUNK_SIZE, MainView, SourceTableView, StreamContent, save_download,
)

target = pathlib.Path(os.environ["TARGET"])
ready = pathlib.Path(os.environ["READY"])
scratch_paths = []

def pause(paths=()):
    announcing = ready.with_suffix(".announcing")
    announcing.write_text(json.dumps([str(path) for path in paths]))
    announcing.replace(ready)
    assert sys.stdin.readline() == "\\n"

class SlowView(MainView):
    def file_data(self):
        pause(scratch_paths)
        return super().file_data()

class SlowModel(Model):
    data_name = "data.txt"
    def save_data(self, path):
        path.write_text("new data")
        scratch_paths.append(path)

class SlowTable(SourceTableView):
    def csv_chunks(self):
        yield "new rows\\n"
        pause()
        yield "more rows\\n"

kind = sys.argv[1]
if kind == "sqlite":
    model = SqliteModel()
    with model.connection() as db:
        db.execute("CREATE TABLE draft(value)")
        db.execute("INSERT INTO draft VALUES ('unsaved')")
        path = pathlib.Path(db.execute("PRAGMA database_list").fetchone()[2])
        pause([path, pathlib.Path(str(path) + "-wal"), pathlib.Path(str(path) + "-shm")])
    model.close()
elif kind == "state":
    SlowView().save_state(target)
elif kind == "study":
    save_study(SlowView(), SlowModel(), target)
elif kind == "csv":
    SlowTable().export_csv(target)
elif kind == "reload-child":
    from composeui.core.reload import take_changes
    os.environ["COMPOSEUI_RELOADED"] = str(target)
    assert take_changes() is None
    pause([target])
else:
    view = MainView()
    def write(sink):
        sink.write(bytes(DOWNLOAD_CHUNK_SIZE))
        pause()
    save_download(view, target, StreamContent(write))
    view.jobs.wait(30)
"""

_WEB_WRITER = """
import asyncio, json, os, pathlib, sys
from starlette.requests import Request
from starlette.testclient import TestClient
from composeui.core.view import FilePathInputView, MainView, child, define_view
from composeui.webcore.session import SessionStore, Hibernation
from composeui.webcore.uploads import receive_upload
from composeui.webcore.webapplication import WebApplication

ready = pathlib.Path(os.environ["READY"])
def pause(paths):
    temporary = ready.with_suffix(".announcing")
    temporary.write_text(json.dumps([str(p) for p in paths]))
    temporary.replace(ready)
    assert sys.stdin.readline() == "\\n"

@define_view
class Main(MainView):
    file: FilePathInputView = child(FilePathInputView)

kind = sys.argv[1]
if kind == "web-body":
    body = (
        b"--boundary\\r\\nContent-Disposition: form-data; name=\\"file\\"; "
        b"filename=\\"draft.csv\\"\\r\\n\\r\\n" + b"x" * 400000
    )
    reads = 0
    async def receive():
        global reads
        reads += 1
        if reads == 1:
            return {"type": "http.request", "body": body, "more_body": True}
        roots = pathlib.Path(os.environ["TMPDIR"]).glob("composeui-scratch-*")
        paths = [p for root in roots for p in root.rglob("upload")]
        assert paths and all(p.stat().st_size > 0 for p in paths)
        pause(paths)
        return {"type": "http.request", "body": b"\\r\\n--boundary--\\r\\n", "more_body": False}
    async def run():
        request = Request(
            {
                "type": "http",
                "headers": [(b"content-type", b"multipart/form-data; boundary=boundary")],
            },
            receive,
        )
        async with receive_upload(request, 1000000):
            pass
    asyncio.run(run())
elif kind == "web-idle":
    store = SessionStore(
        lambda: (Main(), None), ttl=60, max_sessions=1, hibernation=Hibernation(0, 10)
    )
    session_id, session = store.get_or_create(None)
    session.main_view.file.text = "kept"
    store.hibernate_idle()
    assert not store.is_at_hand(session_id)
    pause([store._directory])
    assert store.get(session_id).main_view.file.text == "kept"
    store.close_all()
elif kind == "web-wake":
    saved = pathlib.Path(os.environ["TARGET"])
    store = SessionStore(lambda: (Main(), None), ttl=60, max_sessions=1, saved=saved)
    restored = [
        store.get(p.name) for p in saved.iterdir()
        if p.is_dir() and not p.name.startswith(".")
    ]
    assert len(restored) == 1
    assert restored[0].main_view.file.path.read_bytes() == b"kept upload"
    store.close_all()
else:
    views = []
    class App(WebApplication):
        def setup_session(self, view):
            views.append(view)
    app = App(build_main_view=Main)
    saved = pathlib.Path(os.environ["TARGET"]) if kind == "web-saved" else None
    web = app.create_starlette_app(saved_sessions=saved)
    with TestClient(web, headers={"Sec-Fetch-Site": "same-origin"}) as client:
        client.get("/")
        view = views[-1]
        if kind != "web-saved":
            view.file.text_changed.connect(lambda: pause([view.file.path]))
        client.post(
            "/widget/" + view.file.renderer.widget_id + "/file",
            files={"file": ("draft.csv", b"kept upload", "text/csv")},
        ).raise_for_status()
        path = view.file.path
    if kind == "web-saved":
        pause([path])
"""

_START = """
from composeui.core.application import Application
from composeui.core.view import MainView
Application(build_main_view=MainView)
"""


@pytest.fixture(autouse=True)
def scratch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "temporary"
    directory.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(directory))
    for variable in ("TMPDIR", "TEMP", "TMP"):
        monkeypatch.setenv(variable, str(directory))
    return directory


def _start_again() -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(  # noqa: S603
        [sys.executable, "-c", _START], check=True, capture_output=True, timeout=20
    )


@contextlib.contextmanager
def _writing(kind: str, target: Path, ready: Path) -> Generator[subprocess.Popen[str]]:
    process = subprocess.Popen(  # noqa: S603
        [sys.executable, "-c", _WEB_WRITER if kind.startswith("web-") else _WRITER, kind],
        env={**os.environ, "TARGET": str(target), "READY": str(ready)},
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 20
        while not ready.exists():
            assert process.poll() is None, process.communicate(timeout=5)
            assert time.monotonic() < deadline, "writer never reached the held write"
            time.sleep(0.01)
        yield process
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=20)


@pytest.mark.parametrize(
    "kind", ["sqlite", "state", "study", "stream", "csv", "web-body", "web-idle", "web-upload"]
)
def test_the_next_start_cleans_a_killed_writer_but_not_a_live_one(
    scratch: Path, tmp_path: Path, kind: str
) -> None:
    if kind.startswith("web-"):
        pytest.importorskip("starlette")
    target = tmp_path / "saved"
    target.write_text("previous save")
    ready = tmp_path / "ready"
    unrelated = scratch / "composeui-someone-else.partial"
    unrelated.write_text("not ours")
    recovery = scratch / "autosaves" / "record.json"
    recovery.parent.mkdir()
    recovery.write_text("recoverable work")
    with _writing(kind, target, ready) as process:
        paths = [Path(name) for name in json.loads(ready.read_text())]
        staging = list(tmp_path.glob(".composeui-*.partial"))
        assert staging or paths
        assert all(path.exists() for path in paths)
        _start_again()
        assert all(path.exists() for path in [*paths, *staging])
        process.kill()
        process.wait(timeout=20)
        _start_again()
        assert not any(path.exists() for path in [*paths, *staging])

    assert target.read_text() == "previous save"
    assert unrelated.read_text() == "not ours"
    assert recovery.read_text() == "recoverable work"


@pytest.mark.parametrize("kind", ["state", "study", "stream", "csv"])
def test_a_finished_save_survives_cleanup(scratch: Path, tmp_path: Path, kind: str) -> None:
    target = tmp_path / "saved"
    target.write_text("previous save")
    with _writing(kind, target, tmp_path / "ready") as process:
        assert process.stdin is not None
        process.stdin.write("\n")
        process.stdin.flush()
        assert process.wait(timeout=20) == 0, process.communicate(timeout=5)
    written = target.read_bytes()
    _start_again()
    assert target.read_bytes() == written
    assert written != b"previous save"
    assert list(tmp_path.glob(".composeui-*.partial")) == []
    (root,) = scratch.glob("composeui-scratch-*")
    assert not any(path.is_dir() for path in root.iterdir())


def test_closing_a_model_removes_its_scratch_directory() -> None:
    model = SqliteModel()
    with model.connection() as db:
        path = Path(db.execute("PRAGMA database_list").fetchone()[2])
    model.close()
    assert not path.parent.exists()


def test_releasing_an_owner_twice_never_deletes_a_replacement() -> None:
    owner = _files.ScratchDirectory()
    path = owner.path
    owner.cleanup()
    path.mkdir()
    (path / "important").write_text("not scratch")
    owner.cleanup()
    assert (path / "important").read_text() == "not scratch"


@pytest.mark.parametrize(
    "record", ["{", "[]", "{}", '{"parent": "relative", "device": 0, "inode": 0}']
)
def test_unrecognized_records_are_kept_for_inspection(record: str) -> None:
    owner = _files.ScratchDirectory()
    directory = owner.path
    (directory / "partial.json").write_text(record)
    owner.cleanup()
    restarted = _start_again()
    assert directory.exists()
    assert b"Kept an unrecognized scratch record" in restarted.stdout


@pytest.mark.parametrize(
    "change",
    [
        "symlink",
        "replace",
        "staging-replaced",
        "file",
        "record-link",
        "parent-link",
        "parent-loop",
        "parent-gone",
    ],
)
def test_cleanup_refuses_changed_paths(scratch: Path, tmp_path: Path, change: str) -> None:
    target = tmp_path / "output" / "saved"
    target.parent.mkdir()
    with _writing("state", target, tmp_path / "ready") as process:
        (partial,) = target.parent.glob(".composeui-*.partial")
        process.kill()
        process.wait(timeout=20)
        (root,) = scratch.glob("composeui-scratch-*")
        (owner,) = (path for path in root.iterdir() if path.is_dir())
        kept = tmp_path / "keep"
        kept.mkdir()
        (kept / "important").write_text("not scratch")
        if change == "symlink":
            shutil.rmtree(partial)
            partial.symlink_to(kept, target_is_directory=True)
        elif change == "replace":
            target.parent.rename(kept / "original")
            target.parent.mkdir()
            replacement = target.parent / partial.name
            replacement.mkdir()
            (replacement / "important").write_text("not scratch")
        elif change == "file":
            shutil.rmtree(partial)
            partial.write_text("not scratch")
        elif change == "staging-replaced":
            partial.rename(kept / "original")
            partial.mkdir()
            (partial / "important").write_text("not scratch")
        elif change == "record-link":
            record = owner / "partial.json"
            record.rename(kept / "record")
            record.symlink_to(kept / "record")
        elif change in {"parent-link", "parent-loop"}:
            target.parent.rename(kept / "original")
            destination = kept / "original" if change == "parent-link" else target.parent
            target.parent.symlink_to(destination, target_is_directory=True)
        else:
            shutil.rmtree(target.parent)
        _start_again()

    assert (kept / "important").read_text() == "not scratch"
    assert owner.exists() is (change != "parent-gone")
    protected = {
        "replace": target.parent / partial.name / "important",
        "file": partial,
        "staging-replaced": partial / "important",
    }
    if change in protected:
        assert protected[change].read_text() == "not scratch"


def test_an_unavailable_scratch_root_does_not_stop_an_app_without_files(
    caplog: pytest.LogCaptureFixture,
) -> None:
    owner = _files.ScratchDirectory()
    root = owner.path.parent
    owner.cleanup()
    (root / ".lock.sqlite").unlink()
    root.rmdir()
    root.write_text("not a directory")
    Application(build_main_view=MainView)
    assert root.read_text() == "not a directory"
    assert "Can't clean abandoned scratch files" in caplog.text


@pytest.mark.parametrize("kind", ["lock-link", "bad-lock", "unknown", "directory-link"])
def test_cleanup_leaves_unknown_or_unclaimable_resources(tmp_path: Path, kind: str) -> None:
    with _files.ScratchDirectory() as directory:
        root = directory.parent
    kept = tmp_path / "important"
    kept.mkdir()
    (kept / "data").write_text("not scratch")
    abandoned = root / ("b" * 32)
    if kind == "directory-link":
        abandoned.symlink_to(kept, target_is_directory=True)
    else:
        abandoned.mkdir()
        if kind == "lock-link":
            (abandoned / "lock.sqlite").symlink_to(kept / "data")
        elif kind == "bad-lock":
            (abandoned / "lock.sqlite").write_text("not a database")
        else:
            abandoned.rename(root / "unknown")
            abandoned = root / "unknown"
            (root / ("c" * 32)).write_text("not a directory")
    _start_again()
    assert abandoned.exists()
    assert (kept / "data").read_text() == "not scratch"


@pytest.mark.parametrize("kind", ["symlink", "permissions", "lock"])
def test_an_unsafe_or_unavailable_root_is_not_used(
    tmp_path: Path, kind: str, caplog: pytest.LogCaptureFixture
) -> None:
    with _files.ScratchDirectory() as directory:
        root = directory.parent
    if kind == "symlink":
        (root / ".lock.sqlite").unlink()
        root.rmdir()
        root.symlink_to(tmp_path, target_is_directory=True)
    elif kind == "permissions":
        if os.name != "posix":
            pytest.skip("POSIX directory permissions")
        root.chmod(0o777)
    else:
        (root / ".lock.sqlite").write_text("not a database")
    try:
        Application(build_main_view=MainView)
        assert "Can't clean abandoned scratch files" in caplog.text
    finally:
        if kind == "permissions":
            root.chmod(0o700)


@pytest.mark.parametrize("failure", ["connect", "read"])
def test_a_scratch_lock_failure_leaves_no_new_directory(
    scratch: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    connect = sqlite3.connect

    class FailedConnection(sqlite3.Connection):
        def execute(self, sql: str, *args: Any, **kwargs: Any) -> sqlite3.Cursor:
            msg = "disk full"
            raise sqlite3.OperationalError(msg)

    def failing(path: str, **kwargs: Any) -> sqlite3.Connection:
        if Path(path).name == "lock.sqlite":
            if failure == "connect":
                msg = "disk full"
                raise sqlite3.OperationalError(msg)
            return connect(path, factory=FailedConnection, **kwargs)
        return connect(path, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", failing)
    with pytest.raises(sqlite3.OperationalError, match="disk full"):
        SqliteModel()
    (root,) = scratch.glob("composeui-scratch-*")
    assert not any(path.is_dir() for path in root.iterdir())


@pytest.mark.parametrize("failure", ["connect", "pragma"])
def test_a_database_setup_failure_releases_its_scratch_directory(
    scratch: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    class FailedConnection(sqlite3.Connection):
        def execute(self, sql: str, *args: Any, **kwargs: Any) -> sqlite3.Cursor:
            msg = "database setup failed"
            raise sqlite3.OperationalError(msg)

    connect = sqlite3.connect

    def failing(path: str, **kwargs: Any) -> sqlite3.Connection:
        if Path(path).name == "data.sqlite":
            if failure == "connect":
                msg = "database setup failed"
                raise sqlite3.OperationalError(msg)
            return connect(path, factory=FailedConnection, **kwargs)
        return connect(path, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", failing)
    with pytest.raises(sqlite3.OperationalError, match="database setup failed"):
        SqliteModel()
    (root,) = scratch.glob("composeui-scratch-*")
    assert not any(path.is_dir() for path in root.iterdir())


def test_a_staging_name_collision_never_deletes_the_existing_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = uuid.uuid4()
    partial = tmp_path / f".composeui-{token.hex}.partial"
    partial.mkdir()
    (partial / "important").write_text("not scratch")
    monkeypatch.setattr(uuid, "uuid4", lambda: token)
    with pytest.raises(FileExistsError):
        MainView().save_state(tmp_path / "saved")
    assert (partial / "important").read_text() == "not scratch"


@pytest.mark.parametrize("failing_sync", [1, 2])
def test_a_save_starts_no_output_if_its_ownership_record_cannot_be_synced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failing_sync: int
) -> None:
    target = tmp_path / "saved"
    target.write_text("previous")

    sync = os.fsync
    calls = 0

    def fails(fd: int) -> None:
        nonlocal calls
        calls += 1
        if calls == failing_sync:
            msg = "disk full"
            raise OSError(msg)
        sync(fd)

    monkeypatch.setattr(os, "fsync", fails)
    with pytest.raises(OSError, match="disk full"):
        MainView().save_state(target)
    assert list(tmp_path.glob(".composeui-*.partial")) == []
    assert target.read_text() == "previous"


def test_concurrent_study_saves_keep_their_unfinished_archives_separate(tmp_path: Path) -> None:
    target = tmp_path / "saved"
    with (
        _writing("study", target, tmp_path / "first") as first,
        _writing("study", target, tmp_path / "second") as second,
    ):
        for writer in (first, second):
            assert writer.stdin is not None
            writer.stdin.write("\n")
            writer.stdin.flush()
            assert writer.wait(timeout=20) == 0, writer.communicate(timeout=5)
            with zipfile.ZipFile(target) as archive:
                assert archive.read("data.txt") == b"new data"
                assert "views" in json.loads(archive.read("views.json"))
    assert list(tmp_path.glob(".composeui-*.partial")) == []


@pytest.mark.parametrize("name", ["lock.sqlite", "partial.json", "data"])
def test_a_model_s_data_file_cannot_replace_cleanup_metadata(
    tmp_path: Path, scratch: Path, name: str
) -> None:
    class FileModel(Model):
        content = ""

        def save_data(self, path: Path) -> None:
            path.write_text(self.content)

        def open_data(self, path: Path) -> None:
            self.content = path.read_text()

    FileModel.data_name = name
    model = FileModel()
    model.content = "study data"
    target = tmp_path / "study"
    save_study(MainView(), model, target)
    model.content = ""
    open_study(MainView(), model, target)
    assert model.content == "study data"
    (root,) = scratch.glob("composeui-scratch-*")
    assert not any(path.is_dir() for path in root.iterdir())


@pytest.mark.parametrize("first_to_end", ["supervisor", "child"])
def test_a_reload_child_and_its_supervisor_both_own_the_saved_files(
    tmp_path: Path, first_to_end: str
) -> None:
    pytest.importorskip("starlette")
    owner = _files.ScratchDirectory()
    saved = owner.path / "sessions"
    saved.mkdir()
    ready = tmp_path / "ready"
    try:
        with _writing("web-saved", saved, ready) as child:
            (upload,) = (Path(name) for name in json.loads(ready.read_text()))
            if first_to_end == "supervisor":
                owner.cleanup()
            _start_again()
            assert upload.read_bytes() == b"kept upload"
            child.kill()
            child.wait(timeout=20)
            _start_again()
        if first_to_end == "supervisor":
            assert not saved.exists()
        else:
            assert upload.read_bytes() == b"kept upload"
            subprocess.run(  # noqa: S603
                [sys.executable, "-c", _WEB_WRITER, "web-wake"],
                env={**os.environ, "TARGET": str(saved), "READY": str(ready)},
                check=True,
                capture_output=True,
                timeout=20,
            )
            assert not upload.exists()
    finally:
        owner.cleanup()
    assert not saved.exists()


def test_a_shared_scratch_lease_refuses_an_unrecognized_owner(tmp_path: Path) -> None:
    with _files.ScratchDirectory() as directory:
        unrelated = directory.parent / "not-an-owner"
        unrelated.mkdir()
        with pytest.raises(OSError, match="Not an owned scratch directory"):
            _files.ScratchDirectory.borrow(unrelated)
        assert _files.ScratchDirectory.borrow(tmp_path) is None


@pytest.mark.parametrize("kind", ["web-body", "web-idle", "web-upload"])
def test_finished_web_work_leaves_no_temporary_payload(
    tmp_path: Path, scratch: Path, kind: str
) -> None:
    pytest.importorskip("starlette")
    ready = tmp_path / "ready"
    with _writing(kind, tmp_path / "unused", ready) as process:
        paths = [Path(name) for name in json.loads(ready.read_text())]
        assert process.stdin is not None
        process.stdin.write("\n")
        process.stdin.flush()
        assert process.wait(timeout=20) == 0, process.communicate(timeout=5)
    assert not any(path.exists() for path in paths)
    (root,) = scratch.glob("composeui-scratch-*")
    assert not any(path.is_dir() for path in root.iterdir())


def test_a_desktop_reload_child_keeps_its_supervisor_s_files_alive(tmp_path: Path) -> None:
    owner = _files.ScratchDirectory()
    directory = owner.path
    try:
        with _writing("reload-child", directory, tmp_path / "ready") as child:
            owner.cleanup()
            _start_again()
            assert directory.exists()
            child.kill()
            child.wait(timeout=20)
            _start_again()
            assert not directory.exists()
    finally:
        owner.cleanup()


def test_server_files_stay_until_a_worker_s_cleanup_has_finished() -> None:
    pytest.importorskip("starlette")

    files = SessionFiles()
    directory = files.upload_directory()
    (directory / "draft").write_text("kept")
    view = MainView()
    working, go, cleaning, finish, ended = (threading.Event() for _ in range(5))

    def work(_job: Job[None]) -> None:
        working.set()
        assert go.wait(20)

    def cleanup() -> None:
        cleaning.set()
        assert finish.wait(20)
        shutil.rmtree(directory)

    view.jobs.start(work)
    try:
        assert working.wait(20)
        files.after_workers(view.jobs, cleanup)
        view.jobs.after_workers(ended.set)
        files.close()
        go.set()
        assert cleaning.wait(20)
        _start_again()
        assert (directory / "draft").read_text() == "kept"
    finally:
        go.set()
        finish.set()
        view.jobs.wait(20)
        assert ended.wait(20)
    assert not directory.exists()


def test_a_caller_s_storage_is_not_removed_with_its_sessions(tmp_path: Path) -> None:
    pytest.importorskip("starlette")

    files = SessionFiles(tmp_path)
    directory = files.upload_directory()
    (tmp_path / "important").write_text("not scratch")
    files.after_workers(MainView().jobs, lambda: shutil.rmtree(directory))
    files.close()
    files.close()
    assert not directory.exists()
    assert (tmp_path / "important").read_text() == "not scratch"


def test_a_scratch_lease_recognizes_a_temporary_directory_s_alias(
    scratch: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    alias = tmp_path / "alias"
    alias.symlink_to(scratch, target_is_directory=True)
    monkeypatch.setattr(tempfile, "tempdir", str(alias))
    owner = _files.ScratchDirectory()
    borrowed = _files.ScratchDirectory.borrow(owner.path.resolve())
    assert borrowed is not None
    owner.cleanup()
    assert borrowed.path.is_dir()
    borrowed.cleanup()
    assert not owner.path.exists()

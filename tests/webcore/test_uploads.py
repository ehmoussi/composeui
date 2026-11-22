"""Tests of the web uploads: their limits, the disk, and the life of their files."""

from __future__ import annotations

import asyncio
import errno
import shutil
import sys
import tempfile
import threading
import types
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest import mock

import pytest
from typing_extensions import override

pytest.importorskip("starlette")
# Starlette's test client: httpx2, which needs Python 3.11, or httpx before it
pytest.importorskip("httpx2" if sys.version_info >= (3, 11) else "httpx")

from hypothesis import settings
from hypothesis.stateful import (
    Bundle,
    RuleBasedStateMachine,
    invariant,
    precondition,
    rule,
)
from starlette.requests import Request

from composeui.core.view import (
    FilePathInputView,
    MainView,
    child,
    define_view,
)
from composeui.webcore.limits import MAX_BODY_SIZE, max_upload_body_size
from composeui.webcore.session import SessionStore, WebSession
from composeui.webcore.uploads import (
    MAX_FIELD_SIZE,
    MAX_FIELDS,
    MAX_PART_HEADERS_SIZE,
    MAX_UPLOAD_FILES,
    UploadRefusal,
    receive_upload,
)
from composeui.webcore.webapplication import WebApplication
from examples.webhello import HelloMainView
from tests.datafiles import DataFileMainView

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator
    from typing import BinaryIO

    from starlette.testclient import TestClient

    from composeui.core.jobs import Job
    from tests.markdown import HelpMainView

from tests.webcore.support import _Browser, _part, _pick_file, _swapped, _widget_id


@define_view
class _UploadMainView(MainView):
    field: FilePathInputView = child(FilePathInputView)


@pytest.mark.parametrize("limit", [1024, 8 * 1024 * 1024])
def test_a_main_view_sets_the_largest_file_a_user_can_upload(
    monkeypatch: pytest.MonkeyPatch, limit: int
) -> None:
    """A limit above the default passes the body's limit too; one below refuses earlier."""
    monkeypatch.setattr(_UploadMainView, "max_upload_size", limit)
    views: list[_UploadMainView] = []

    class UploadApp(WebApplication[_UploadMainView]):
        @override
        def setup_session(self, main_view: _UploadMainView) -> None:
            main_view.status_bar.timeout = 0
            views.append(main_view)

    with _Browser(UploadApp(build_main_view=_UploadMainView).create_starlette_app()) as client:
        client.get("/")
        (main_view,) = views
        url = f"/widget/{_widget_id(main_view.field.renderer)}/file"

        client.post(url, files={"file": ("large.csv", b"#" * limit)})
        assert main_view.field.path is not None
        accepted = main_view.field.path
        assert (accepted.name, accepted.stat().st_size) == ("large.csv", limit)

        response = client.post(url, files={"file": ("over.csv", b"#" * (limit + 1))})
        status = _swapped(response.text, _widget_id(main_view.notification.renderer))
        assert "'over.csv': the file is larger than" in status.text
        assert main_view.field.path == accepted


def _receive(body: Iterable[bytes]) -> Request:
    chunks = iter(body)

    async def receive() -> dict[str, Any]:
        chunk = next(chunks, None)
        return {"type": "http.request", "body": chunk or b"", "more_body": chunk is not None}

    headers = [(b"content-type", b"multipart/form-data; boundary=b")]
    return Request({"type": "http", "headers": headers}, receive)


_FILE_PART = b'--b\r\nContent-Disposition: form-data; name="file"; filename="a.csv"\r\n\r\n'
#: after a part that its guard refuses: without it, a form with no file is refused anyway
_WHOLE_FILE = _FILE_PART + b"1\r\n--b--\r\n"


def test_an_upload_stops_going_to_the_disk_once_over_the_limit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    written: list[int] = []

    def body() -> Iterator[bytes]:
        yield _FILE_PART
        for _ in range(4):
            yield b"x" * 400_000  # past the file's buffer, 128 KiB on Python 3.14: on the disk
            written.extend(path.stat().st_size for path in tmp_path.rglob("upload-*"))
        yield b"\r\n--b--\r\n"

    async def receive() -> bool:
        async with receive_upload(_receive(body()), 1_000_000) as (upload, _fields):
            assert upload is not None
            return upload.refusal is UploadRefusal.TOO_LARGE

    assert asyncio.run(receive())
    assert 0 < max(written) <= 1_000_000
    assert list(tmp_path.iterdir()) == []  # the scratch folder is gone


def test_the_files_of_a_form_each_keep_their_own_bytes_and_share_one_limit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    second = _FILE_PART.replace(b"a.csv", b"b.csv")
    # one chunk ends a file and starts the next
    body = [_FILE_PART + b"12", b"3\r\n" + second + b"45", b"6\r\n--b--\r\n"]

    async def receive(limit: int) -> tuple[UploadRefusal | None, list[tuple[str, bytes]]]:
        async with receive_upload(_receive(body), limit) as (upload, _fields):
            assert upload is not None
            return upload.refusal, [(f.filename, f.path.read_bytes()) for f in upload.files]

    assert asyncio.run(receive(6)) == (None, [("a.csv", b"123"), ("b.csv", b"456")])
    # each under the limit, but not together
    assert asyncio.run(receive(5))[0] is UploadRefusal.TOO_LARGE
    assert list(tmp_path.iterdir()) == []


def _disk_with(*free: int) -> mock.Mock:
    """Get a stand-in for `shutil.disk_usage` that gives these free bytes, one per check."""
    return mock.Mock(side_effect=[types.SimpleNamespace(free=bytes_free) for bytes_free in free])


@pytest.mark.parametrize(
    "disk",
    [_disk_with(10**9, 10**9, 10), mock.Mock(side_effect=OSError("No space left on device"))],
    ids=["below the floor partway", "full"],
)
def test_an_upload_stops_going_to_the_disk_once_it_runs_short(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, disk: mock.Mock
) -> None:
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(shutil, "disk_usage", disk)
    sizes: list[int] = []

    def body() -> Iterator[bytes]:
        yield _FILE_PART
        for _ in range(6):
            yield b"x" * 600_000
            sizes.extend(path.stat().st_size for path in tmp_path.rglob("upload-*"))
        yield b"\r\n--b--\r\n"

    async def receive() -> UploadRefusal | None:
        async with receive_upload(_receive(body()), 10**9, 1000) as (upload, _fields):
            assert upload is not None
            return upload.refusal

    assert asyncio.run(receive()) is UploadRefusal.NO_ROOM
    assert sum(1 for size in sizes if size > 0) < 6  # it stopped, and its bytes are gone
    assert list(tmp_path.iterdir()) == []


class _BufferedTailFails:
    """A file whose last bytes find no room as it closes, as on a full disk."""

    def __init__(self, file: BinaryIO) -> None:
        self._file = file

    def write(self, data: bytes) -> int:
        return self._file.write(data)

    def close(self) -> None:
        self._file.close()
        raise OSError(errno.ENOSPC, "No space left on device")


def _scratch_file_opens_with(
    monkeypatch: pytest.MonkeyPatch, wrap: Callable[[BinaryIO], Any]
) -> None:
    real_open = Path.open

    def opening(path: Path, *args: Any, **kwargs: Any) -> Any:
        file = real_open(path, *args, **kwargs)
        return wrap(file) if path.name.startswith("upload-") else file

    monkeypatch.setattr(Path, "open", opening)


def _no_room_for_a_folder(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tempfile, "mkdtemp", mock.Mock(side_effect=OSError(errno.ENOSPC, "full")))


def _no_room_for_the_file(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(_file: BinaryIO) -> Any:
        raise OSError(errno.ENOSPC, "full")

    _scratch_file_opens_with(monkeypatch, refuse)


def _no_room_for_its_last_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    _scratch_file_opens_with(monkeypatch, _BufferedTailFails)


@pytest.mark.parametrize(
    "fill_the_disk", [_no_room_for_a_folder, _no_room_for_the_file, _no_room_for_its_last_bytes]
)
def test_a_full_disk_says_so_and_never_hands_over_a_cut_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fill_the_disk: Callable[[pytest.MonkeyPatch], None],
) -> None:
    monkeypatch.chdir(tmp_path)  # no scratch folder must not write the file here instead
    views: list[DataFileMainView] = []

    class DataApp(WebApplication[DataFileMainView]):
        @override
        def setup_session(self, main_view: DataFileMainView) -> None:
            main_view.status_bar.timeout = 0
            views.append(main_view)

    with _Browser(DataApp(build_main_view=DataFileMainView).create_starlette_app()) as client:
        client.get("/")
        (main_view,) = views
        dataset = main_view.form.dataset
        fill_the_disk(monkeypatch)

        response = client.post(
            f"/widget/{_part(dataset, 'field').widget_id}/file",
            files={"file": ("small.csv", b"1,2")},  # small: it all stays in the buffer
        )

        assert response.status_code == 200
        status = _swapped(response.text, _widget_id(main_view.notification.renderer))
        assert status.text == "Can't open 'small.csv': the server has no room for it right now."
        assert dataset.file is None
        assert list(tmp_path.iterdir()) == []


def test_a_file_that_would_fill_the_disk_is_refused_and_keeps_the_field_s_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    views: list[DataFileMainView] = []

    class DataApp(WebApplication[DataFileMainView]):
        @override
        def setup_session(self, main_view: DataFileMainView) -> None:
            main_view.status_bar.timeout = 0
            views.append(main_view)

    with _Browser(DataApp(build_main_view=DataFileMainView).create_starlette_app()) as client:
        client.get("/")
        (main_view,) = views
        dataset = main_view.form.dataset
        url = f"/widget/{_part(dataset, 'field').widget_id}/file"
        client.post(url, files={"file": ("kept.csv", b"1")})
        kept = dataset.file
        assert kept is not None

        # more than any disk holds: the check itself is real
        monkeypatch.setattr(DataFileMainView, "min_free_disk", 2**62)
        response = client.post(url, files={"file": ("new.csv", b"2")})

        status = _swapped(response.text, _widget_id(main_view.notification.renderer))
        assert status.text == "Can't open 'new.csv': the server has no room for it right now."
        assert dataset.file == kept
        assert kept.path.read_bytes() == b"1"


@pytest.mark.parametrize(
    "body",
    [
        _FILE_PART + b"cut short, without its end",
        # an action takes one file: its page never sends two
        _FILE_PART + b"1\r\n--b\r\n" + _FILE_PART[4:] + b"2\r\n--b--\r\n",
        b"".join(_FILE_PART + b"1\r\n" for _ in range(MAX_UPLOAD_FILES + 1)) + b"--b--\r\n",
        b'--b\r\nContent-Disposition: form-data; name="other"; filename="a"\r\n\r\n1\r\n--b--\r\n',
        b"--b\r\nContent-Disposition: form-data\r\n\r\n1\r\n" + _WHOLE_FILE,  # no name
        b'--b\r\nContent-Disposition: form-data; name="row"\r\n\r\n'
        + b"1" * (MAX_FIELD_SIZE + 1)
        + b"\r\n"
        + _WHOLE_FILE,
        b"".join(
            b'--b\r\nContent-Disposition: form-data; name="f%d"\r\n\r\n1\r\n' % index
            for index in range(MAX_FIELDS + 2)
        )
        + _WHOLE_FILE,
        # a few of 4 KB: a newer python-multipart itself refuses one large header, or over 8
        b'--b\r\nContent-Disposition: form-data; name="row"\r\n'
        + b"".join(
            b"X%d: %s\r\n" % (index, b"y" * 4000)
            for index in range(MAX_PART_HEADERS_SIZE // 4000 + 1)
        )
        + b"\r\n1\r\n"
        + _WHOLE_FILE,
        b"not the form it says it is",
    ],
    ids=[
        "cut",
        "two files",
        "too many files",
        "other name",
        "no name",
        "large field",
        "many fields",
        "large headers",
        "garbage",
    ],
)
def test_a_malformed_upload_hands_nothing_over_and_leaves_no_file(
    body: bytes,
    help_views: list[HelpMainView],
    help_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    help_client.get("/")
    (main_view,) = help_views
    action = main_view.help_menu.open_help
    picked: list[Path] = []
    action.file_picked.connect(picked.append)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))

    response = help_client.post(
        f"/widget/{_widget_id(action.renderer)}/file",
        content=body,
        headers={"Content-Type": "multipart/form-data; boundary=b"},
    )

    assert response.status_code == 400
    assert picked == []
    assert list(tmp_path.iterdir()) == []


def test_a_server_that_stops_removes_the_uploads_of_its_sessions() -> None:
    views: list[DataFileMainView] = []

    class DataApp(WebApplication[DataFileMainView]):
        @override
        def setup_session(self, main_view: DataFileMainView) -> None:
            views.append(main_view)

    with _Browser(DataApp(build_main_view=DataFileMainView).create_starlette_app()) as client:
        client.get("/")
        (main_view,) = views
        field = _part(main_view.form.dataset, "field")
        client.post(f"/widget/{field.widget_id}/file", files={"file": ("a.csv", b"1")})
        upload = main_view.form.dataset.file
        assert upload is not None
        assert upload.path.exists()

    assert not upload.path.exists()


def test_an_upload_that_arrives_after_its_session_ended_stays_nowhere(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    main_view = DataFileMainView()
    session = WebSession(main_view)
    measurements = main_view.form.measurements
    field = _part(measurements, "field")
    session.close()

    assert _pick_file(session, field.widget_id, "late.csv", b"1,2") is None

    assert measurements.path is None
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "filename",
    [
        "x" * 300 + ".csv",
        "x" + "." * 300 + ".csv",  # cut, it would start with a dot: a hidden file
        "NUL.csv",  # a device on Windows, not a file
        "com1.data.csv",
    ],
    ids=["long", "cut-to-a-dot", "device", "device-of-two-types"],
)
def test_an_uploaded_file_s_name_is_cut_keeps_its_type_and_names_a_shown_file(
    filename: str,
) -> None:
    main_view = DataFileMainView()
    session = WebSession(main_view)
    measurements = main_view.form.measurements
    field = _part(measurements, "field")

    _pick_file(session, field.widget_id, filename, b"1,2")

    path = measurements.path
    assert path is not None
    assert (path.suffix, path.read_bytes()) == (".csv", b"1,2")
    assert len(path.name) <= 200
    assert not path.name.startswith(".")
    assert path.name.split(".")[0].lower() not in ("nul", "com1")
    session.close()


def test_a_form_without_a_boundary_is_refused(
    help_views: list[HelpMainView], help_client: TestClient
) -> None:
    help_client.get("/")
    (main_view,) = help_views
    response = help_client.post(
        f"/widget/{_widget_id(main_view.help_menu.open_help.renderer)}/file",
        content=b"",
        headers={"Content-Type": "multipart/form-data"},
    )
    assert response.status_code == 400


def test_an_upload_is_one_file_on_the_disk_as_its_callbacks_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No second copy: not a spooled file, nor the scratch file it was moved from."""
    views: list[DataFileMainView] = []

    class DataApp(WebApplication[DataFileMainView]):
        @override
        def setup_session(self, main_view: DataFileMainView) -> None:
            views.append(main_view)

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    with _Browser(DataApp(build_main_view=DataFileMainView).create_starlette_app()) as client:
        client.get("/")
        (main_view,) = views
        dataset = main_view.form.dataset
        field = _part(dataset, "field")
        files: list[list[Path]] = []
        dataset.uploaded.connect(
            lambda _file: files.append([p for p in tmp_path.rglob("*") if p.is_file()])
        )
        url = f"/widget/{field.widget_id}/file"

        client.post(url, files={"file": ("é.csv", b"x" * (2 * 1024 * 1024), "text/csv")})

        assert dataset.file is not None
        assert dataset.file.name == "é.csv"
        assert dataset.file.media_type == "text/csv"
        assert files == [[dataset.file.path]]


def test_a_file_the_page_kept_for_its_size_is_refused_by_name(
    help_views: list[HelpMainView], help_client: TestClient
) -> None:
    help_client.get("/")
    (main_view,) = help_views
    action = main_view.help_menu.open_help
    picked: list[Path] = []
    action.file_picked.connect(picked.append)
    too_large = {"too_large": (None, "huge.md")}

    response = help_client.post(f"/widget/{_widget_id(action.renderer)}/file", files=too_large)

    status = _swapped(response.text, _widget_id(main_view.notification.renderer))
    assert status.text == "Can't open 'huge.md': the file is larger than 5 MiB."
    assert picked == []
    # a widget that takes no file has nothing to refuse
    status_id = _widget_id(main_view.status_bar.renderer)
    assert help_client.post(f"/widget/{status_id}/file", files=too_large).status_code == 404


def _store_of_data_files(saved: Path) -> SessionStore:
    return SessionStore(lambda: (DataFileMainView(), None), ttl=60.0, max_sessions=2, saved=saved)


def test_a_session_restored_by_a_reload_owns_its_uploads(tmp_path: Path) -> None:
    store = _store_of_data_files(tmp_path)
    created = store.get_or_create(None)
    assert created is not None
    session_id, session = created
    assert isinstance(session.main_view, DataFileMainView)
    measurements = session.main_view.form.measurements
    _pick_file(session, _part(measurements, "field").widget_id, "first.csv", b"first")
    path = measurements.path
    assert path is not None
    store.save_all()

    restored_store = _store_of_data_files(tmp_path)
    restored = restored_store.get(session_id)

    assert restored is not None
    assert isinstance(restored.main_view, DataFileMainView)
    assert restored.main_view.form.measurements.path == path
    assert path.read_bytes() == b"first"
    restored_store.drop(session_id)
    assert not path.exists()


def test_a_saved_session_naming_other_uploads_never_deletes_them(tmp_path: Path) -> None:
    store = _store_of_data_files(tmp_path)
    created = store.get_or_create(None)
    assert created is not None
    session_id, session = created
    assert isinstance(session.main_view, DataFileMainView)
    measurements = session.main_view.form.measurements
    _pick_file(session, _part(measurements, "field").widget_id, "first.csv", b"first")
    store.save_all()
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    (tmp_path / session_id / "uploads").write_text(str(unrelated))

    restored_store = _store_of_data_files(tmp_path)
    assert restored_store.get(session_id) is not None
    restored_store.drop(session_id)

    assert unrelated.is_dir()


@pytest.mark.parametrize("ending", ["dropped", "closed"])
def test_an_upload_stays_until_a_dropped_worker_that_may_read_it_has_ended(ending: str) -> None:
    main_view = DataFileMainView()
    session = WebSession(main_view)
    measurements = main_view.form.measurements
    field = _part(measurements, "field")
    _pick_file(session, field.widget_id, "first.csv", b"first")
    first = measurements.path
    assert first is not None
    started, release = threading.Event(), threading.Event()
    threads: list[threading.Thread] = []
    contents: list[bytes] = []

    def work(_job: Job[None, None]) -> None:
        threads.append(threading.current_thread())
        started.set()
        assert release.wait(30)
        contents.append(first.read_bytes())

    main_view.jobs.start(work)
    assert started.wait(30)  # running, not only started: a busy runner starts the thread late
    if ending == "closed":
        session.close()
    else:
        _pick_file(session, field.widget_id, "second.csv", b"second")
        main_view.jobs.drop()
        session.poll_jobs()  # what runs the cleanup
    assert first.read_bytes() == b"first"

    release.set()
    threads[0].join(30)

    assert contents == [b"first"]
    if ending == "closed":
        assert not first.exists()
    else:
        session.poll_jobs()
        assert not first.exists()
        session.close()


def test_two_sessions_upload_files_of_the_same_name_apart() -> None:
    views = [DataFileMainView(), DataFileMainView()]
    sessions = [WebSession(view) for view in views]
    for session, view, content in zip(sessions, views, (b"first", b"second")):
        field = _part(view.form.dataset, "field")
        _pick_file(session, field.widget_id, "data.csv", content)
    files = [view.form.dataset.file for view in views]
    assert files[0] is not None
    assert files[1] is not None
    assert files[0].path.read_bytes() == b"first"
    assert files[1].path.read_bytes() == b"second"
    sessions[0].close()
    assert files[1].path.exists()
    sessions[1].close()


class _WorkerRun:
    """A job of `_SessionUploadsMachine`, whose thread waits for `may_end`."""

    def __init__(self) -> None:
        self.started, self.may_end = threading.Event(), threading.Event()
        self.thread: threading.Thread | None = None
        self.called: list[str] = []
        self.has_ended = self.should_report = False


class _SessionUploadsMachine(RuleBasedStateMachine):
    """A session's uploads and jobs: uploads, clears, drops, polls and its close, in any order.

    What each file should be, as the session must keep it: `current` the field's, `stale` those
    replaced or cleared, kept while a worker may read them, and `deleted`.
    """

    runs = Bundle("runs")

    def __init__(self) -> None:
        super().__init__()
        self.main_view = DataFileMainView()
        self.session = WebSession(self.main_view)
        self.dataset = self.main_view.form.dataset
        self.field_id = _part(self.dataset, "field").widget_id
        self.current: Path | None = None
        self.stale: list[Path] = []
        self.deleted: list[Path] = []
        self.all_runs: list[_WorkerRun] = []
        self.is_closed = False

    @property
    def _has_threads(self) -> bool:
        return not all(run.has_ended for run in self.all_runs)

    def _clean_up(self) -> None:
        """Delete what the session no longer needs, as each request does: once no worker runs."""
        if not self._has_threads:
            self.deleted += self.stale
            self.stale = []

    @rule()
    def upload(self) -> None:
        answer = _pick_file(self.session, self.field_id, "data.csv", b"data")
        if self.is_closed:
            assert answer is None
            return
        assert self.dataset.file is not None
        if self.current is not None:
            self.stale.append(self.current)
        self.current = self.dataset.file.path
        self._clean_up()

    @precondition(lambda machine: not machine.is_closed)
    @rule()
    def clear(self) -> None:
        self.dataset.clear()
        if self.current is not None:
            self.stale.append(self.current)
        self.current = None

    @precondition(lambda machine: not machine.is_closed)
    @rule()
    def poll(self) -> None:
        self.session.poll_jobs()
        self._clean_up()

    @precondition(lambda machine: not machine.is_closed)
    @rule(target=runs)
    def start(self) -> _WorkerRun:
        run = _WorkerRun()

        def work(_job: Job[None, int]) -> None:
            run.thread = threading.current_thread()
            run.started.set()
            assert run.may_end.wait(30)
            job.report_progress(1)

        job = self.main_view.jobs.start(work)
        job.progress.connect(lambda _value: run.called.append("progress"))
        job.finished.connect(lambda _result: run.called.append("finished"))
        assert run.started.wait(30)
        run.should_report = True
        self.all_runs.append(run)
        return run

    @rule(run=runs)
    def end(self, run: _WorkerRun) -> None:
        if run.has_ended:
            return
        run.may_end.set()
        assert run.thread is not None
        run.thread.join(30)
        assert not run.thread.is_alive()
        run.has_ended = True
        if self.is_closed:
            self._clean_up()

    @precondition(lambda machine: not machine.is_closed)
    @rule()
    def drop(self) -> None:
        self.main_view.jobs.drop()
        for run in self.all_runs:
            run.should_report = run.should_report and run.has_ended

    @precondition(lambda machine: not machine.is_closed)
    @rule()
    def close(self) -> None:
        self.session.close()
        self.is_closed = True
        for run in self.all_runs:
            run.should_report = run.should_report and run.has_ended
        if self.current is not None:
            self.stale.append(self.current)
            self.current = None
        self._clean_up()

    @invariant()
    def a_file_stays_until_no_worker_can_read_it(self) -> None:
        for path in ([] if self.current is None else [self.current]) + self.stale:
            assert path.exists()
        for path in self.deleted:
            assert not path.exists()

    @invariant()
    def a_job_reports_only_while_it_counts(self) -> None:
        for run in self.all_runs:
            expected = ["progress", "finished"] if run.has_ended and run.should_report else []
            assert run.called == expected

    @override
    def teardown(self) -> None:
        for run in self.all_runs:
            run.may_end.set()
            assert run.thread is not None
            run.thread.join(30)
        if not self.is_closed:
            self.session.close()


TestASessionsUploadsInAnyOrder = _SessionUploadsMachine.TestCase
TestASessionsUploadsInAnyOrder.settings = settings(max_examples=100, stateful_step_count=20)


@pytest.mark.parametrize("chunked", [False, True])
def test_a_body_larger_than_any_upload_is_refused_before_it_is_read(
    main_view: HelloMainView, client: TestClient, chunked: bool
) -> None:
    """Starlette would spool it whole to a temporary file: no limit until the route's."""
    body = b"x" * (MAX_BODY_SIZE + 1)
    headers = {"Content-Type": "multipart/form-data; boundary=b"}
    # without a length (chunked), the body is cut once it passes the limit
    content = iter([body[:1024], body[1024:]]) if chunked else body

    response = client.post("/state", content=content, headers=headers)

    assert response.status_code == 413
    assert main_view.notification.message == ""  # the route never ran


@pytest.mark.parametrize("path", ["/state", "/widget/{}", "/state/download"])
def test_the_app_s_upload_limit_reaches_no_other_route(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, path: str
) -> None:
    """Their form parser would keep the body, under no limit of the disk."""
    monkeypatch.setattr(HelloMainView, "max_upload_size", 100 * 1024 * 1024)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    views: list[HelloMainView] = []

    class HelloApp(WebApplication[HelloMainView]):
        @override
        def setup_session(self, main_view: HelloMainView) -> None:
            views.append(main_view)

    with _Browser(HelloApp(build_main_view=HelloMainView).create_starlette_app()) as client:
        client.get("/")
        address = path.format(_widget_id(views[0].status_bar.renderer))
        over = max_upload_body_size(1) + MAX_BODY_SIZE
        headers = {"Content-Type": "multipart/form-data; boundary=b"}
        assert client.post(address, content=b"x" * over, headers=headers).status_code == 413

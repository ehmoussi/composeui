"""Tests of the web file uploads and file, folder and save paths."""

from __future__ import annotations

import contextlib
import errno
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest import mock

import pytest
from typing_extensions import override

pytest.importorskip("starlette")
# Starlette's test client: httpx2, which needs Python 3.11, or httpx before it
pytest.importorskip("httpx2" if sys.version_info >= (3, 11) else "httpx")

from hypothesis import example, given, settings
from hypothesis import strategies as st

from composeui.core.registry import RendererType
from composeui.core.view import (
    CellWidget,
    MainView,
    UploadedFile,
)
from composeui.webcore import serverfiles
from composeui.webcore._renderers.files import WebFilePathInputRenderer
from composeui.webcore._renderers.forms import WebFormLabelRenderer
from composeui.webcore.session import WebSession
from composeui.webcore.uploads import (
    ReceivedFile,
)
from composeui.webcore.webapplication import WebApplication
from composeui.webcore.webrenderer import (
    UnsupportedEventError,
    WebRenderer,
    handle_event,
)
from tests.datafiles import DataFileMainView
from tests.studyfiles import StudyFileMainView
from tests.tables import (
    DataFilesTableMainView,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from starlette.testclient import TestClient

    from composeui.core.jobs import Job

from tests.webcore.support import (
    _Browser,
    _Element,
    _element,
    _find,
    _listed,
    _part,
    _pick_cell_file,
    _pick_file,
    _shows_files,
    _swapped,
    _widget_id,
)


def test_a_file_upload_holds_its_file_until_the_next_one_or_the_session_s_end() -> None:
    main_view = DataFileMainView()
    main_view.status_bar.timeout = 0
    session = WebSession(main_view)
    dataset = main_view.form.dataset
    field = _part(dataset, "field")
    uploads: list[UploadedFile] = []
    dataset.uploaded.connect(uploads.append)
    element = _element(field.to_html(), field.widget_id)
    assert element.text == "Choose a fileNo file chosen"
    (picker,) = [a for tag, a in element.descendants if tag == "input"]
    assert (picker["accept"], picker["hx-post"]) == (".csv", f"/widget/{field.widget_id}/file")

    name = "<b>a & b.csv"
    result = _pick_file(session, field.widget_id, name, b"1,2", "text/csv")
    assert result is not None
    (first,) = uploads
    assert dataset.file == first
    assert (first.name, first.size, first.media_type) == (name, 3, "text/csv")
    assert (first.path.read_bytes(), first.is_temporary) == (b"1,2", True)
    # only the name is swapped, as text: the button keeps the focus
    assert f'id="{field.widget_id}"' not in result[0]
    assert _swapped(result[0], f"{field.widget_id}-name").text == name

    # the next upload replaces the copy; a file of another type leaves it alone
    _pick_file(session, field.widget_id, "b.csv", b"3")
    second = uploads[-1]
    assert (second.name, second.path.exists(), first.path.exists()) == ("b.csv", True, False)
    _pick_file(session, field.widget_id, "c.txt", b"4")
    assert (dataset.file, len(uploads)) == (second, 2)

    # while disabled, the user can't replace it
    dataset.is_enabled = False
    with pytest.raises(UnsupportedEventError):
        _pick_file(session, field.widget_id, "d.csv", b"5")
    assert (dataset.file, second.path.read_bytes()) == (second, b"3")
    dataset.is_enabled = True

    dataset.clear()
    assert (dataset.file, second.path.exists()) == (None, True)
    session.poll_jobs()  # the next request, with no job running
    assert not second.path.exists()
    _pick_file(session, field.widget_id, "e.csv", b"6")
    third = uploads[-1]
    session.close()
    assert not third.path.exists()


@contextlib.contextmanager
def _data_files_app() -> Generator[tuple[TestClient, DataFileMainView], None, None]:
    """Serve the file fields' main view, and give the one session's view."""
    views: list[DataFileMainView] = []

    class DataApp(WebApplication[DataFileMainView]):
        @override
        def setup_session(self, main_view: DataFileMainView) -> None:
            main_view.status_bar.timeout = 0
            views.append(main_view)

    with _Browser(DataApp(build_main_view=DataFileMainView).create_starlette_app()) as client:
        client.get("/")
        (main_view,) = views
        yield client, main_view


def test_files_given_together_are_kept_in_one_folder_under_their_own_names() -> None:
    with _data_files_app() as (client, main_view):
        shapes = main_view.form.shapes
        field = _part(shapes, "field")
        given: list[tuple[UploadedFile, ...]] = []
        shapes.files_uploaded.connect(given.append)
        (picker,) = [
            a for tag, a in _element(field.to_html(), field.widget_id).descendants if tag == "input"
        ]
        assert ("multiple" in picker, picker["accept"]) == (True, ".shp,.shx,.dbf")
        url = f"/widget/{field.widget_id}/file"

        response = client.post(
            url,
            files=[
                ("file", ("my roads.shp", b"1", "application/x-shp")),
                ("file", ("my roads.dbf", b"22")),
                # a crafted post: the browser sends no folder
                ("file", ("../../my roads.shx", b"333")),
            ],
        )

        (first,) = given
        assert [(file.name, file.size, file.path.name) for file in first] == [
            ("my roads.shp", 1, "my roads.shp"),
            ("my roads.dbf", 2, "my roads.dbf"),
            ("my roads.shx", 3, "my roads.shx"),
        ]
        assert [file.path.read_bytes() for file in first] == [b"1", b"22", b"333"]
        assert len({file.path.parent for file in first}) == 1
        assert (first[0].media_type, all(file.is_temporary for file in first)) == (
            "application/x-shp",
            True,
        )
        assert _swapped(response.text, f"{field.widget_id}-name").text == "3 files"

        # the next choice replaces them, as a single file does
        client.post(url, files=[("file", ("rivers.shp", b"4"))])
        assert [file.name for file in shapes.files] == ["rivers.shp"]
        assert not first[0].path.parent.exists()

        # a field without `multiple` takes one file: its page never sends two; nor a field
        # disabled, nor what isn't a widget
        two = [("file", ("a.shp", b"1")), ("file", ("b.shp", b"2"))]
        dataset_url = f"/widget/{_part(main_view.form.dataset, 'field').widget_id}/file"
        assert client.post(dataset_url, files=two).status_code == 400
        assert main_view.form.dataset.file is None
        shapes.is_enabled = False
        assert client.post(url, files=two).status_code == 400
        assert [file.name for file in shapes.files] == ["rivers.shp"]
        assert client.post("/widget/cui-0/file", files=two).status_code == 404


@pytest.mark.parametrize(
    ("name", "kept"),
    [
        ("rôutes de l'été .shp", "rôutes de l'été .shp"),
        ("C:\\gis\\roads.shp", "roads.shp"),
        # what some system can't hold, or hides: the name every upload gets
        ("a:b.shp", "a-b.shp"),
        (".roads.shp", "roads.shp"),
        ("NUL.shp", "upload-NUL.shp"),
        ("COM¹.shp", "COM-.shp"),
        ("CONIN$.shp", "CONIN-.shp"),
        ("tab\t.shp", "tab-.shp"),
        ("r" * 250 + ".shp", "r" * 196 + ".shp"),
    ],
)
def test_a_file_given_with_others_keeps_its_name_where_every_system_can_hold_it(
    name: str, kept: str
) -> None:
    with _data_files_app() as (client, main_view):
        shapes = main_view.form.shapes
        # as sent, which the test client would encode
        part = 'Content-Disposition: form-data; name="file"; filename="{}"'.format(
            name.replace("\\", "\\\\")
        )
        client.post(
            f"/widget/{_part(shapes, 'field').widget_id}/file",
            content=f"--b\r\n{part}\r\n\r\n1\r\n--b--\r\n".encode(),
            headers={"Content-Type": "multipart/form-data; boundary=b"},
        )
        assert shapes.file is not None
        assert (shapes.file.path.name, shapes.file.name) == (kept, name.rsplit("\\", 1)[-1])


#: pieces of names that some system can't hold, or holds as something else
_SHAPE_NAME_PIECES = [
    *("roads", "é", "e\u0301", " ", ".", "..", "-", "$"),
    *("/", "\\", ":", '"', "*", "|", "\t", "\0", "\x7f"),
    *("NUL", "com1", "COM¹", "lpt³", "CONIN$", "x" * 120),
]
#: every system's devices, as Windows names them: a file of such a name, with any type, isn't
#: a file
_WINDOWS_DEVICES = {
    *("con", "prn", "aux", "nul", "conin$", "conout$"),
    *(f"{port}{digit}" for port in ("com", "lpt") for digit in "123456789¹²³"),
}


def test_a_file_given_with_others_keeps_a_name_that_every_system_holds_as_that_file() -> None:
    main_view = DataFileMainView()
    main_view.form.shapes.extensions = {}  # any name: a type of its own may end it
    session = WebSession(main_view)
    widget_id = _part(main_view.form.shapes, "field").widget_id

    @given(
        st.lists(st.sampled_from(_SHAPE_NAME_PIECES), min_size=1, max_size=6).map("".join),
        st.sampled_from([".shp", ".SHP", "", ".", " "]),
    )
    @example("x" * 250, ".shp")
    @example("//roads/", ".shp")  # read as a network path by `Path` on Windows
    @settings(max_examples=300)  # cheap: one small file each
    def give(stem: str, end: str) -> None:
        name = stem + end
        with tempfile.TemporaryDirectory() as directory:
            received = Path(directory, "upload-0")
            received.write_bytes(b"1")
            session.pick_files(widget_id, [ReceivedFile(name, "", received)])
        file = main_view.form.shapes.file
        assert file is not None, name
        kept = file.path.name
        assert file.path.read_bytes() == b"1", name
        assert len(kept.encode()) <= 200, name
        assert not kept.startswith("."), name
        assert not kept.endswith((" ", ".")), name
        refused = set('<>:"/\\|?*\x7f') | {chr(code) for code in range(32)}
        assert not refused & set(kept), name
        assert kept.split(".")[0].rstrip(" ").lower() not in _WINDOWS_DEVICES, name
        assert kept.lower().endswith(end.lower().strip(" .")), name  # its type
        # a name each system holds stays the user's own
        plain = stem.isascii() and stem.isalnum() and len(name) <= 200
        if plain and stem.lower() not in _WINDOWS_DEVICES and end in {".shp", ".SHP"}:
            assert kept == name

    try:
        give()
    finally:
        session.close()


def _fail_the_choice_s_folder(monkeypatch: pytest.MonkeyPatch) -> None:
    real_mkdtemp = tempfile.mkdtemp

    def mkdtemp(**kwargs: str) -> str:
        if "dir" in kwargs:  # the folder of an upload, not the request's scratch folder
            raise OSError(errno.ENOSPC, "full")
        return real_mkdtemp(**kwargs)

    monkeypatch.setattr(tempfile, "mkdtemp", mkdtemp)


def _fail_the_second_move(monkeypatch: pytest.MonkeyPatch) -> None:
    real_move = shutil.move
    moves: list[str] = []

    def move(source: str, target: str) -> object:
        moves.append(target)
        if len(moves) == 2:
            raise OSError(errno.ENOSPC, "full")
        return real_move(source, target)

    monkeypatch.setattr(shutil, "move", move)


@pytest.mark.parametrize(
    ("files", "page_fields", "message"),
    [
        (
            [("Roads.shp", b"1"), ("roads.shp", b"2")],
            {},
            "Can't open 'Roads.shp' and 1 other file:"
            " another of the files chosen has the same name.",
        ),
        (
            [("a:b.shp", b"1"), ("a-b.shp", b"2")],
            {},
            "Can't open 'a:b.shp' and 1 other file: another of the files chosen has the same name.",
        ),
        (
            [("roads.shp", b"1"), ("notes.txt", b"2")],
            {},
            "Can't open 'notes.txt' and 1 other file: expected a .shp or .shx or .dbf file.",
        ),
        (
            [("roads.shp", b"#" * 600_000), ("roads.dbf", b"#" * 600_000)],
            {},
            "Can't open 'roads.shp' and 1 other file: the files are larger than 1 MiB together.",
        ),
        (
            [("roads.shp", b"1"), ("roads.dbf", b"2")],
            {"fail": "folder"},
            "Can't open 'roads.shp' and 1 other file: the server has no room for them right now.",
        ),
        (
            [("roads.shp", b"1"), ("roads.dbf", b"2"), ("roads.shx", b"3")],
            {"fail": "move"},
            "Can't open 'roads.shp' and 2 other files: the server has no room for them right now.",
        ),
        (
            [],
            {"too_large": "roads.shp", "count": "3"},
            "Can't open 'roads.shp' and 2 other files: the files are larger than 1 MiB together.",
        ),
        (
            [],
            {"too_many": "roads.shp", "count": "101"},
            "Can't open 'roads.shp' and 100 other files: at most 100 files go at once.",
        ),
    ],
    ids=[
        "same name",
        "same name once safe",
        "other type",
        "too large together",
        "no room for a folder",
        "no room",
        "page: too large",
        "page: too many",
    ],
)
def test_files_given_together_are_refused_together_and_the_last_ones_stay(
    monkeypatch: pytest.MonkeyPatch,
    files: list[tuple[str, bytes]],
    page_fields: dict[str, str],
    message: str,
) -> None:
    monkeypatch.setattr(DataFileMainView, "max_upload_size", 1024 * 1024)
    with _data_files_app() as (client, main_view):
        shapes = main_view.form.shapes
        field = _part(shapes, "field")
        url = f"/widget/{field.widget_id}/file"
        client.post(url, files=[("file", ("kept.shp", b"0"))])
        kept = shapes.files
        uploads = kept[0].path.parent.parent  # the field's, each upload in a folder
        failing = page_fields.pop("fail", None)
        if failing == "folder":
            _fail_the_choice_s_folder(monkeypatch)
        elif failing == "move":
            _fail_the_second_move(monkeypatch)

        response = client.post(
            url,
            files=[("file", file) for file in files]
            + [(field_name, (None, value)) for field_name, value in page_fields.items()],
        )

        status = _swapped(response.text, _widget_id(main_view.notification.renderer))
        assert status.text == message
        assert (shapes.files, kept[0].path.read_bytes()) == (kept, b"0")
        assert list(uploads.iterdir()) == [kept[0].path.parent]


def _wait_for_the_jobs(session: WebSession, main_view: MainView) -> None:
    """Poll as the page does, until the jobs' outcomes have come back."""
    for _ in range(600):
        session.poll_jobs()
        if not main_view.jobs.is_running:
            break
        time.sleep(0.05)
    assert not main_view.jobs.is_running
    session.poll_jobs()


@pytest.mark.parametrize("replacement", ["upload", "clear"])
def test_a_job_reads_a_file_replaced_before_it_opened_it(replacement: str) -> None:
    main_view = DataFileMainView()
    session = WebSession(main_view)
    dataset = main_view.form.dataset
    field = _part(dataset, "field")
    _pick_file(session, field.widget_id, "first.csv", b"first")
    first = dataset.file
    assert first is not None
    replaced = threading.Event()
    read: list[bytes] = []

    def work(_job: Job[None, None], path: Path) -> None:
        assert replaced.wait(30)
        read.append(path.read_bytes())

    main_view.jobs.start(work, first.path)
    if replacement == "upload":
        _pick_file(session, field.widget_id, "second.csv", b"second")
    else:
        dataset.clear()
    session.poll_jobs()
    assert first.path.exists()
    replaced.set()

    _wait_for_the_jobs(session, main_view)

    assert read == [b"first"]
    assert not first.path.exists()
    # the file the view holds now stays
    if replacement == "upload":
        assert dataset.file is not None
        assert dataset.file.path.read_bytes() == b"second"
    session.close()


def test_a_file_path_replaced_during_a_job_stays_until_the_job_is_over() -> None:
    main_view = DataFileMainView()
    session = WebSession(main_view)
    measurements = main_view.form.measurements
    field = _part(measurements, "field")
    _pick_file(session, field.widget_id, "first.csv", b"first")
    first = measurements.path
    assert first is not None
    release = threading.Event()

    def work(_job: Job[None, None]) -> None:
        assert release.wait(30)

    main_view.jobs.start(work)
    _pick_file(session, field.widget_id, "second.csv", b"second")
    assert first.read_bytes() == b"first"
    release.set()
    _wait_for_the_jobs(session, main_view)

    assert not first.exists()
    assert measurements.path is not None
    assert measurements.path.read_bytes() == b"second"
    session.close()


def test_the_end_of_a_session_removes_a_replaced_file_while_a_job_runs() -> None:
    main_view = DataFileMainView()
    session = WebSession(main_view)
    field = _part(main_view.form.dataset, "field")
    _pick_file(session, field.widget_id, "first.csv", b"first")
    first = main_view.form.dataset.file
    assert first is not None
    started, release = threading.Event(), threading.Event()
    threads: list[threading.Thread] = []

    def work(_job: Job[None, None]) -> None:
        threads.append(threading.current_thread())
        started.set()
        assert release.wait(30)

    main_view.jobs.start(work)
    # running, not only started: a busy runner starts the thread late
    assert started.wait(30)
    main_view.form.dataset.clear()
    session.poll_jobs()
    assert first.path.exists()

    session.close()
    assert first.path.exists()  # the job may still read it
    release.set()
    threads[0].join(30)

    assert not first.path.exists()


def test_an_upload_that_fails_to_arrive_keeps_the_file_the_view_holds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main_view = DataFileMainView()
    session = WebSession(main_view)
    dataset = main_view.form.dataset
    field = _part(dataset, "field")
    _pick_file(session, field.widget_id, "first.csv", b"first")
    first = dataset.file
    assert first is not None

    with monkeypatch.context() as patch:
        patch.setattr(shutil, "move", mock.Mock(side_effect=OSError("No space left on device")))
        result = _pick_file(session, field.widget_id, "second.csv", b"second")
    session.poll_jobs()  # the next request, which removes what was replaced

    assert result is not None
    status = _swapped(result[0], _widget_id(main_view.notification.renderer))
    assert "no room" in status.text
    assert dataset.file == first
    assert first.path.read_bytes() == b"first"
    session.close()


def test_a_disabled_file_path_keeps_the_copy_it_holds() -> None:
    main_view = DataFileMainView()
    session = WebSession(main_view)
    measurements = main_view.form.measurements
    field = _part(measurements, "field")
    _pick_file(session, field.widget_id, "flows.csv", b"1,2")
    held = measurements.path
    assert held is not None

    measurements.is_enabled = False
    with pytest.raises(UnsupportedEventError):
        _pick_file(session, field.widget_id, "other.csv", b"3")

    assert held.read_bytes() == b"1,2"
    session.close()


def test_a_file_path_is_typed_or_uploaded_its_copy_kept_until_the_session_ends() -> None:
    main_view = DataFileMainView()
    main_view.status_bar.timeout = 0
    session = WebSession(main_view)
    main_view.set_language("fr")
    measurements = main_view.form.measurements
    label, field = _part(measurements, "label"), _part(measurements, "field")
    assert isinstance(label, WebFormLabelRenderer)
    picked: list[tuple[Path, bytes]] = []
    measurements.path_picked.connect(lambda path: picked.append((path, path.read_bytes())))
    reloads: list[None] = []
    measurements.reload_clicked.connect(lambda: reloads.append(None))
    element = _element(field.to_html(), field.widget_id)
    text, picker = (attributes for tag, attributes in element.descendants if tag == "input")
    assert text["aria-labelledby"] == label.text_id
    assert (picker["type"], picker["accept"]) == ("file", ".csv,.txt,.text")
    assert picker["hx-post"] == f"/widget/{field.widget_id}/file"
    buttons = [attributes for tag, attributes in element.descendants if tag == "button"]
    assert [button["aria-label"] for button in buttons] == ["Choisir un fichier", "Recharger"]

    handle_event(field, "change", {"value": "/data/flows.csv"})
    assert measurements.path == Path("/data/flows.csv")
    result = _pick_file(session, field.widget_id, "flows.csv", b"1,2")
    assert result is not None
    ((first, content),) = picked
    assert (first.name, content, measurements.path) == ("flows.csv", b"1,2", first)
    swapped = _swapped(result[0], field.widget_id)  # the field shows the copy's path
    assert next(a["value"] for tag, a in swapped.descendants if tag == "input") == str(first)
    # the field keeps its last upload only; another type is refused
    _pick_file(session, field.widget_id, "levels.txt", b"3")
    assert (picked[-1][0].name, first.exists()) == ("levels.txt", False)
    result = _pick_file(session, field.widget_id, "notes.md", b"#")
    assert result is not None
    status = _swapped(result[0], _widget_id(main_view.notification.renderer))
    assert status.text == "Can't open 'notes.md': expected a .csv or .txt or .text file."
    assert len(picked) == 2

    handle_event(field, "reload", {})
    assert len(reloads) == 1
    measurements.has_reload = False  # no button: nothing to reload
    with pytest.raises(UnsupportedEventError):
        handle_event(field, "reload", {})
    assert len(reloads) == 1
    session.close()
    assert not picked[-1][0].exists()


def test_a_file_path_s_upload_stays_in_the_app_s_folder_under_a_free_name(
    tmp_path: Path,
) -> None:
    main_view = DataFileMainView()
    measurements = main_view.form.measurements
    measurements.upload_folder = tmp_path
    session = WebSession(main_view)
    field = _part(measurements, "field")
    picked: list[Path] = []
    measurements.path_picked.connect(picked.append)
    _pick_file(session, field.widget_id, "flows.csv", b"1,2")
    _pick_file(session, field.widget_id, "flows.csv", b"3")
    session.close()
    # the app's files: neither the next upload nor the session's end removes them
    assert picked == [tmp_path / "flows.csv", tmp_path / "flows-1.csv"]
    assert [path.read_bytes() for path in picked] == [b"1,2", b"3"]
    assert measurements.text == str(tmp_path / "flows-1.csv")
    assert sorted(path.name for path in tmp_path.iterdir()) == ["flows-1.csv", "flows.csv"]


def _server_files(main_view: StudyFileMainView, root: Path) -> WebRenderer[Any]:
    """Render `main_view` with its study's files in `root`, its `.export` files; its field."""
    main_view.study.extensions = {"Code_Aster": (".export",)}
    main_view.study.server_roots = (root,)
    main_view.render(RendererType.WEB)
    return _part(main_view.study, "field")


def test_a_file_path_with_server_roots_is_picked_among_their_files_never_copied(
    tmp_path: Path,
) -> None:
    root = tmp_path / "studies"
    (root / "beam").mkdir(parents=True)
    (root / "Alpha").mkdir()
    for name in ("beam/beam.export", "beam/beam.comm", "zeta.export", "notes.txt", ".old.export"):
        (root / name).write_text("")
    main_view = StudyFileMainView()
    field = _server_files(main_view, root)
    main_view.set_language("fr")
    picked: list[Path] = []
    main_view.study.path_picked.connect(picked.append)
    element = _element(field.to_html(), field.widget_id)
    assert [tag for tag, a in element.descendants if a.get("type") == "file"] == []  # no upload
    files = root.resolve()

    # at the only root: its folders, then its files of the field's types, none hidden
    body = handle_event(field, "browse", {})
    assert _listed(body, field) == [
        ("browse-folder", "Alpha"),
        ("browse-folder", "beam"),
        ("browse-file", "zeta.export"),
    ]
    assert str(files) in _element(body, f"{field.widget_id}-files-list").text
    body = handle_event(field, "browse-folder", {"name": "beam"})
    assert _listed(body, field) == [("browse-parent", ""), ("browse-file", "beam.export")]
    # only the list swaps: the dialog open stays the same element
    assert _find(body, f"{field.widget_id}-files") is _find(body, field.widget_id) is None
    assert "Dossier parent" in _element(body, f"{field.widget_id}-files-list").text
    handle_event(field, "browse-file", {"name": "beam.comm"})  # not of the field's types
    assert (main_view.study.text, _shows_files(field)) == ("", True)

    body = handle_event(field, "browse-file", {"name": "beam.export"})

    assert picked == [files / "beam" / "beam.export"]
    assert main_view.study.path == files / "beam" / "beam.export"
    assert "hidden" in _element(body, f"{field.widget_id}-files").attributes
    with pytest.raises(UnsupportedEventError):  # closed: nothing to move in
        handle_event(field, "browse-folder", {"name": "beam"})
    # opened again: in the folder of the field's file, closed by Cancel or Escape
    assert _listed(handle_event(field, "browse", {}), field)[-1] == ("browse-file", "beam.export")
    handle_event(field, "browse-parent", {})
    assert _listed(field.to_html(), field)[0] == ("browse-folder", "Alpha")
    handle_event(field, "browse-close", {})
    assert not _shows_files(field)


def test_a_file_path_with_server_roots_keeps_to_them_whatever_the_page_sends(
    tmp_path: Path,
) -> None:
    root, other = tmp_path / "studies", tmp_path / "other"
    (root / "beam").mkdir(parents=True)
    (root / "beam" / "beam.export").write_text("")
    (root / ".old").mkdir()
    (root / ".old" / "old.export").write_text("")
    (other / "secret").mkdir(parents=True)
    (other / "secret" / "secret.export").write_text("")
    main_view = StudyFileMainView()
    field = _server_files(main_view, root)
    study = main_view.study
    handle_event(field, "browse", {})
    shown = _listed(field.to_html(), field)

    crafted = ["..", "../other", str(other), "beam/../..", "/", ".old", "missing", "a\0b"]
    for name in [*crafted, "beam/beam.export"]:
        handle_event(field, "browse-folder", {"name": name})
        handle_event(field, "browse-file", {"name": name})
    handle_event(field, "browse-parent", {})  # at the only root: nowhere above it
    handle_event(field, "browse-root", {"name": "0"})  # one root: no list of them

    assert (_listed(field.to_html(), field), study.text) == (shown, "")
    # typed: only a path inside the roots, links followed, is the field's path
    for typed, path in [
        (str(root / "beam" / "beam.export"), root / "beam" / "beam.export"),
        (str(root / "beam" / ".." / ".." / "other" / "secret" / "secret.export"), None),
        (str(other / "secret" / "secret.export"), None),
        ("a\0b", None),
    ]:
        handle_event(field, "change", {"value": typed})
        assert study.path == path, typed


def test_a_path_that_lists_the_server_s_files_refuses_an_upload_its_page_never_sends(
    tmp_path: Path,
) -> None:
    # crafted: it would write in `upload_folder`, e.g. a folder of the roots
    main_view = StudyFileMainView()
    main_view.study.server_roots = (tmp_path,)
    main_view.study.upload_folder = tmp_path
    session = WebSession(main_view)
    with pytest.raises(UnsupportedEventError):
        _pick_file(session, _part(main_view.study, "field").widget_id, "beam.export", b"")
    table_view = DataFilesTableMainView()
    table = table_view.inputs
    table.cell_widgets = {1: CellWidget.file_path(server_roots=(tmp_path,), upload_folder=tmp_path)}
    session = WebSession(table_view)
    _pick_cell_file(session, _widget_id(table.renderer), 0, "flows.csv", b"1,2")
    assert (table.rows[0][1], list(tmp_path.iterdir())) == ("", [])


#: pieces of the names a page could post for an item: separators, dots, a link out of
#: the roots, a NUL character, and items that are there
_NAME_PIECES = ["..", ".", "/", "\\", "~", "\0", "beam", "beam.export", "out", "other", "secret"]


def test_no_name_a_page_posts_leads_out_of_the_server_roots(tmp_path: Path) -> None:
    root, other = tmp_path / "studies", tmp_path / "other"
    (root / "beam").mkdir(parents=True)
    (root / "beam" / "beam.export").write_text("")
    (other / "secret").mkdir(parents=True)
    if sys.platform != "win32":  # Windows needs a privilege to make a symbolic link
        (root / "out").symlink_to(other)
        (root / "beam" / "out").symlink_to(other / "secret")
    roots = serverfiles.resolve_roots([root])

    @given(
        st.sampled_from([root, root / "beam"]),
        st.lists(st.sampled_from(_NAME_PIECES), min_size=1, max_size=5).map("".join),
    )
    def post(folder: Path, name: str) -> None:
        path = serverfiles.item_path(folder, name, roots)
        assert path is None or serverfiles.is_within(path, roots), name
        # one item of the folder, shown: not a path, even one inside the roots, nor hidden
        separators = [os.sep, os.altsep or os.sep, "\0"]
        if name.startswith(".") or any(separator in name for separator in separators):
            assert path is None, name

    post()


def test_a_file_path_s_base_folder_reads_its_relative_text_and_opens_its_server_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, elsewhere = tmp_path / "studies", tmp_path / "elsewhere"
    (root / "beam" / "inputs").mkdir(parents=True)
    (root / "beam" / "inputs" / "beam.export").write_text("")
    (root / "beam" / "beam.export").write_text("")
    (tmp_path / "secret.export").write_text("")
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)  # the process started in another folder
    main_view = StudyFileMainView()
    main_view.study.base_folder = root / "beam"
    field = _server_files(main_view, root)
    study = main_view.study
    picked: list[Path] = []
    study.path_picked.connect(picked.append)

    # typed: from the base folder, and kept to the roots, `..` followed
    for typed, path in [
        ("inputs/beam.export", root / "beam" / "inputs" / "beam.export"),
        ("../../secret.export", None),
    ]:
        handle_event(field, "change", {"value": typed})
        assert study.path == path, typed
    # the field empty: the list opens in the base folder
    handle_event(field, "change", {"value": ""})
    body = handle_event(field, "browse", {})
    assert _listed(body, field)[1:] == [("browse-folder", "inputs"), ("browse-file", "beam.export")]
    handle_event(field, "browse-folder", {"name": "inputs"})

    handle_event(field, "browse-file", {"name": "beam.export"})

    shown = root.resolve() / "beam" / "inputs" / "beam.export"
    assert (study.text, picked) == (str(Path("inputs", "beam.export")), [shown])
    assert study.path == root / "beam" / "inputs" / "beam.export"


def test_a_file_path_with_several_server_roots_lists_them_first(tmp_path: Path) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    (first / "beam").mkdir(parents=True)
    second.mkdir()
    (tmp_path / "file.export").write_text("")
    main_view = StudyFileMainView()
    field = _server_files(main_view, first)
    # a root missing, a file, or there twice: left out
    main_view.study.server_roots = (first, tmp_path / "missing", tmp_path / "file.export", second)
    main_view.study.server_roots += (first / ".." / "first",)

    body = handle_event(field, "browse", {})
    assert _listed(body, field) == [("browse-root", "0"), ("browse-root", "1")]
    assert str(second.resolve()) in _element(body, f"{field.widget_id}-files-list").text
    for name in ("2", "x"):  # no such root: the list stays
        handle_event(field, "browse-root", {"name": name})
    handle_event(field, "browse-parent", {})
    assert _listed(field.to_html(), field) == [("browse-root", "0"), ("browse-root", "1")]

    handle_event(field, "browse-root", {"name": "0"})
    # a root among others: its parent is the list of the roots
    assert _listed(field.to_html(), field) == [("browse-parent", ""), ("browse-folder", "beam")]
    handle_event(field, "browse-parent", {})
    assert _listed(field.to_html(), field)[0] == ("browse-root", "0")
    # opened again on a file that isn't there: on the list of the roots
    main_view.study.text = str(first / "beam" / "gone.export")
    assert _listed(handle_event(field, "browse", {}), field)[0] == ("browse-root", "0")
    # in a root the field no longer has: back to the list of the roots
    handle_event(field, "browse-root", {"name": "1"})
    main_view.study.server_roots = (first,)
    handle_event(field, "browse-folder", {"name": "beam"})
    assert _listed(field.to_html(), field) == [("browse-root", "0")]


def test_a_file_path_s_server_list_says_when_a_folder_is_too_large_or_unreadable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "studies"
    (root / "beam").mkdir(parents=True)
    for name in ("a.export", "b.export", "c.export"):
        (root / "beam" / name).write_text("")
    main_view = StudyFileMainView()
    field = _server_files(main_view, root)
    main_view.study.partial_folder_text = "Too many"
    main_view.study.unreadable_folder_text = "Unreadable"
    monkeypatch.setattr(serverfiles, "MAX_ITEMS", 2)
    handle_event(field, "browse", {})

    body = handle_event(field, "browse-folder", {"name": "beam"})

    assert len(_listed(body, field)) == 3  # the parent folder, and 2 of the 3 files
    assert _element(body, f"{field.widget_id}-files-list").text.count("Too many") == 1
    for name in ("a.export", "b.export", "c.export"):
        (root / "beam" / name).unlink()
    (root / "beam").rmdir()  # gone while shown

    body = handle_event(field, "browse-folder", {"name": "gone"})

    assert _listed(body, field) == [("browse-parent", "")]
    assert "Unreadable" in _element(body, f"{field.widget_id}-files-list").text


def test_a_file_path_s_server_list_shows_nothing_a_link_leads_to_outside_the_roots(
    tmp_path: Path,
) -> None:
    if sys.platform == "win32":
        pytest.skip("Windows needs a privilege to make a symbolic link")
    root, other = tmp_path / "studies", tmp_path / "other"
    (root / "beam").mkdir(parents=True)
    (root / "beam" / "beam.export").write_text("")
    other.mkdir()
    (other / "secret.export").write_text("")
    (root / "out").symlink_to(other)
    (root / "secret.export").symlink_to(other / "secret.export")
    (root / "loop.export").symlink_to(root / "loop.export")
    (root / "study.export").symlink_to(root / "beam" / "beam.export")  # inside: kept
    (root / "it's <b> & co.export").write_text("")
    main_view = StudyFileMainView()
    field = _server_files(main_view, root)
    study = main_view.study

    body = handle_event(field, "browse", {})

    assert _listed(body, field) == [
        ("browse-folder", "beam"),
        ("browse-file", "it's <b> & co.export"),
        ("browse-file", "study.export"),
    ]
    for name in ("out", "secret.export", "loop.export"):
        handle_event(field, "browse-folder", {"name": name})
        handle_event(field, "browse-file", {"name": name})
    assert study.text == ""
    for typed in ("out/secret.export", "secret.export", "loop.export"):
        handle_event(field, "change", {"value": str(root / typed)})
        assert study.path is None, typed
    handle_event(field, "browse", {})
    handle_event(field, "browse-file", {"name": "it's <b> & co.export"})
    assert study.path == root.resolve() / "it's <b> & co.export"


def test_a_file_path_s_server_list_needs_its_roots_and_an_enabled_field(tmp_path: Path) -> None:
    main_view = StudyFileMainView()
    field = _server_files(main_view, tmp_path)
    handle_event(field, "browse", {})
    main_view.study.is_enabled = False
    assert not _shows_files(field)  # nothing to pick in a disabled field
    with pytest.raises(UnsupportedEventError):
        handle_event(field, "browse-close", {})
    main_view.study.is_enabled = True
    main_view.study.server_roots = ()
    with pytest.raises(UnsupportedEventError):  # the field uploads its file
        handle_event(field, "browse", {})
    main_view.study.server_roots = (tmp_path,)
    with pytest.raises(UnsupportedEventError):
        handle_event(field, "browse-up", {})


def test_a_folder_path_is_typed_on_the_web_without_server_roots(tmp_path: Path) -> None:
    main_view = StudyFileMainView()
    main_view.render(RendererType.WEB)
    scratch = main_view.scratch
    field = _part(scratch, "field")
    element = _element(field.to_html(), field.widget_id)

    # the browser can't give a folder's path: no button, nothing uploaded
    assert [tag for tag, _attributes in element.descendants] == ["input"]
    handle_event(field, "change", {"value": str(tmp_path)})
    assert scratch.path == tmp_path  # any folder: no roots to keep to
    with pytest.raises(UnsupportedEventError):
        handle_event(field, "browse", {})


def test_a_folder_path_with_server_roots_is_picked_among_their_folders(tmp_path: Path) -> None:
    root, other = tmp_path / "studies", tmp_path / "other"
    (root / "beam" / "run").mkdir(parents=True)
    (root / "beam" / "beam.export").write_text("")
    other.mkdir()
    main_view = StudyFileMainView()
    main_view.results.server_roots = (root,)
    main_view.render(RendererType.WEB)
    main_view.set_language("fr")
    results = main_view.results
    field = _part(results, "field")
    picked: list[Path] = []
    results.path_picked.connect(picked.append)
    folders = root.resolve()
    choose = f"{field.widget_id}-files-action"

    body = handle_event(field, "browse", {})
    assert _listed(body, field) == [("browse-folder", "beam")]
    assert _element(body, choose).text == "Choisir ce dossier"
    # its folders only, the files left out; "Choose this folder" swapped with the list
    body = handle_event(field, "browse-folder", {"name": "beam"})
    assert _listed(body, field) == [("browse-parent", ""), ("browse-folder", "run")]
    assert "disabled" not in _swapped(body, choose).attributes

    body = handle_event(field, "browse-choose", {})

    assert picked == [folders / "beam"]
    assert results.path == folders / "beam"
    assert "hidden" in _element(body, f"{field.widget_id}-files").attributes
    # opened again: in the folder itself
    body = handle_event(field, "browse", {})
    assert _listed(body, field) == [("browse-parent", ""), ("browse-folder", "run")]
    handle_event(field, "browse-close", {})
    # a file isn't a folder: neither listed, nor picked by name
    handle_event(field, "browse", {})
    with pytest.raises(UnsupportedEventError):
        handle_event(field, "browse-file", {"name": "beam.export"})
    assert picked == [folders / "beam"]
    handle_event(field, "browse-close", {})
    handle_event(field, "change", {"value": str(other)})
    assert results.path is None  # typed outside the roots

    # several roots: none chosen while they're listed
    results.server_roots = (root, other)
    handle_event(field, "change", {"value": ""})
    body = handle_event(field, "browse", {})
    assert "disabled" in _element(body, choose).attributes
    handle_event(field, "browse-choose", {})
    assert len(picked) == 1
    # and a file field picks no folder
    study = _part(main_view.study, "field")
    handle_event(study, "browse", {})
    with pytest.raises(UnsupportedEventError):
        handle_event(study, "browse-choose", {})


def _name_box(markup: str, field: WebRenderer[Any]) -> _Element:
    return _element(markup, f"{field.widget_id}-files-name")


def test_a_save_path_with_server_roots_is_picked_in_a_folder_with_the_name_typed(
    tmp_path: Path,
) -> None:
    root = tmp_path / "studies"
    (root / "beam" / "old.pdf").mkdir(parents=True)  # a folder, named as a file
    (root / "beam" / "report.pdf").write_text("")
    main_view = StudyFileMainView()
    report = main_view.report
    report.extensions = {"PDF": (".pdf",)}
    report.server_roots = (root,)
    main_view.render(RendererType.WEB)
    main_view.set_language("fr")
    field = _part(report, "field")
    picked: list[Path] = []
    report.path_picked.connect(picked.append)
    beam = root.resolve() / "beam"
    action = f"{field.widget_id}-files-action"

    body = handle_event(field, "browse", {})
    assert _listed(body, field) == [("browse-folder", "beam")]
    assert (_element(body, action).text, _name_box(body, field).attributes["value"]) == (
        "Enregistrer",
        "",
    )
    body = handle_event(field, "browse-folder", {"name": "beam"})
    # its folders, then its files of the field's types, each giving its name
    assert _listed(body, field) == [
        ("browse-parent", ""),
        ("browse-folder", "old.pdf"),
        ("browse-name", "report.pdf"),
    ]
    for name in ("report.pdf", "../x"):  # a name that isn't one: the box keeps its own
        body = handle_event(field, "browse-name", {"name": name})
        assert _name_box(body, field).attributes["value"] == "report.pdf"

    # a file that exists: picked once the user agrees to replace it
    body = handle_event(field, "browse-save", {"name": "report"})
    assert (
        "report.pdf existe déjà. Le remplacer ?"
        in _swapped(body, f"{field.widget_id}-files-list").text
    )
    assert "disabled" in _swapped(body, action).attributes
    body = handle_event(field, "browse-keep", {})
    assert _name_box(body, field).attributes["value"] == "report"
    assert picked == []
    for name in ("../x", ".hidden", "a/b", "", "a\0b", "old.pdf"):  # not a file's name
        body = handle_event(field, "browse-save", {"name": name})
        assert _name_box(body, field).attributes.get("aria-invalid") == "true", name
    handle_event(field, "browse-replace", {})  # nothing to replace
    handle_event(field, "browse-save", {"name": "report"})

    body = handle_event(field, "browse-replace", {})

    assert picked == [beam / "report.pdf"]
    assert report.text == str(beam / "report.pdf")
    assert report.is_replace_agreed  # remembered: saving won't ask again
    assert "hidden" in _element(body, f"{field.widget_id}-files").attributes
    # closed by the server: the "…" button takes the focus back
    assert "autofocus" in _element(body, f"{field.widget_id}-browse").attributes
    # opened again: in the file's folder, its name in the box; a new file, at once
    assert _name_box(handle_event(field, "browse", {}), field).attributes["value"] == ("report.pdf")
    handle_event(field, "browse-save", {"name": "summary"})
    assert picked[-1] == beam / "summary.pdf"
    assert not report.is_replace_agreed  # nothing to replace
    report.confirms_overwrite = False
    handle_event(field, "browse", {})
    handle_event(field, "browse-save", {"name": "report"})  # replaced without a question
    assert picked[-1] == beam / "report.pdf"
    assert not report.is_replace_agreed  # so nothing agreed


def test_a_save_path_is_typed_with_its_extension_inside_the_server_roots(tmp_path: Path) -> None:
    root, other = tmp_path / "studies", tmp_path / "other"
    (root / "beam").mkdir(parents=True)
    other.mkdir()
    main_view = StudyFileMainView()
    report = main_view.report
    report.extensions = {"PDF": (".pdf",)}
    report.server_roots = (root, other)
    main_view.render(RendererType.WEB)
    field = _part(report, "field")
    action = f"{field.widget_id}-files-action"

    for typed, path in [
        (str(root / "beam" / "summary"), root / "beam" / "summary.pdf"),
        (str(root / "beam" / "summary.pdf"), root / "beam" / "summary.pdf"),
        (str(tmp_path / "elsewhere"), None),
    ]:
        handle_event(field, "change", {"value": typed})
        assert report.path == path, typed

    # several roots: nothing saved while they're listed
    handle_event(field, "change", {"value": ""})
    body = handle_event(field, "browse", {})
    assert "disabled" in _element(body, action).attributes
    body = handle_event(field, "browse-save", {"name": "summary"})
    assert _name_box(body, field).attributes.get("aria-invalid") == "true"
    handle_event(field, "browse-close", {})
    # opened on a typed file: in its folder, else on the list of the roots
    for typed, listed in [
        (str(root / "beam" / "summary"), ("browse-parent", "")),
        (str(root / "gone" / "summary"), ("browse-root", "0")),
    ]:
        handle_event(field, "change", {"value": typed})
        assert _listed(handle_event(field, "browse", {}), field)[0] == listed
        handle_event(field, "browse-close", {})
    # without roots, typed: no button
    report.server_roots = ()
    element = _element(field.to_html(), field.widget_id)
    assert [tag for tag, _attributes in element.descendants] == ["input"]


def test_a_disabled_file_path_field_refuses_an_upload(tmp_path: Path) -> None:
    view = DataFileMainView()
    view.render(RendererType.WEB)
    field = _part(view.form.measurements, "field")
    assert isinstance(field, WebFilePathInputRenderer)
    view.form.measurements.is_enabled = False

    with pytest.raises(UnsupportedEventError):  # the route answers 400
        field.pick_file(tmp_path / "data.csv")
    assert view.form.measurements.text == ""

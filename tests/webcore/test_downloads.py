"""Tests of the web downloads: the files an app gives and the streams that write them."""

from __future__ import annotations

import asyncio
import contextlib
import html
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
import types
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING
from unittest import mock
from urllib.parse import unquote

import pytest
from typing_extensions import override

pytest.importorskip("starlette")
# Starlette's test client: httpx2, which needs Python 3.11, or httpx before it
pytest.importorskip("httpx2" if sys.version_info >= (3, 11) else "httpx")

from hypothesis import example, given
from hypothesis import strategies as st

from composeui.core._views.files import DOWNLOAD_CHUNK_SIZE, DownloadCanceledError
from composeui.core.application import WebSettings
from composeui.core.view import (
    DownloadedFile,
    StreamContent,
)
from composeui.webcore import downloads as downloads_module
from composeui.webcore import streaming as streaming_module
from composeui.webcore.downloads import (
    DOWNLOAD_TTL,
    FETCHED_TTL,
    MAX_DOWNLOADS,
    Downloads,
    OpenedUrl,
)
from composeui.webcore.streaming import MAX_QUEUED_BYTES, Stream, StreamFailedError
from composeui.webcore.webapplication import WebApplication
from tests.console import RunMainView
from tests.downloading import ReportMainView
from tests.opening import HELP_URL, OpeningMainView

if sys.version_info >= (3, 11):
    import httpx2 as httpx
else:
    import httpx

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path
    from typing import BinaryIO

    from starlette.testclient import TestClient

    from examples.webhello import HelloMainView


from tests.webcore.support import _Browser, _element, _session_of, _swapped, _widget_id


def test_an_uploaded_file_name_cannot_reach_the_download_header(
    main_view: HelloMainView, client: TestClient
) -> None:
    # built by hand: httpx would percent-encode the quote before it reached the server
    body = (
        b"--b\r\n"
        b'Content-Disposition: form-data; name="file"; filename="evil\\"; x=1; my study.hello"\r\n'
        b"Content-Type: application/octet-stream\r\n\r\n"
        b"{}\r\n--b--\r\n"
    )

    client.post(
        "/_composeui/state",
        content=body,
        headers={"Content-Type": "multipart/form-data; boundary=b"},
    )

    assert main_view.state_filepath is not None
    assert '"' in main_view.state_filepath.name  # the hostile name did reach the server
    disposition = client.get("/_composeui/state").headers["content-disposition"]
    assert re.fullmatch(r'attachment; filename="[A-Za-z0-9._-]+\.hello"', disposition)


#: a download's `Content-Disposition`: a fallback name in printable ASCII, quoted, then
#: the name itself in RFC 5987's characters
_DISPOSITION = re.compile(
    r"attachment; filename=\"([ !#-\[\]-~]*)\"; filename\*=UTF-8''([A-Za-z0-9!#$&+.^_`|~%-]*)"
)


def test_an_app_s_file_is_named_until_the_page_of_its_session_fetches_it(tmp_path: Path) -> None:
    views: list[ReportMainView] = []

    class ReportApp(WebApplication[ReportMainView]):
        @override
        def setup_session(self, main_view: ReportMainView) -> None:
            views.append(main_view)

    def links(markup: str) -> list[tuple[str, str]]:
        """Get the address and the name of each file the markup tells the page to fetch."""
        found = _element(markup, "cui-downloads").descendants
        return [(a["href"] or "", a["download"] or "") for tag, a in found if tag == "a"]

    starlette_app = ReportApp(build_main_view=ReportMainView).create_starlette_app()
    with _Browser(starlette_app) as client, _Browser(starlette_app) as other:
        assert links(client.get("/").text) == []
        other.get("/")
        view = views[0]
        export_id = _widget_id(view.export.renderer)

        body = client.post(f"/_composeui/widget/{export_id}", data={"event": "click"}).text
        _swapped(body, "cui-downloads")
        ((address, name),) = links(body)
        assert name == "report é.csv"  # without the folder
        # named again until fetched: the answer may be lost, the page reloaded
        assert links(client.get(f"/_composeui/widget/{export_id}").text) == [(address, name)]
        assert links(client.get("/").text) == [(address, name)]
        stolen = other.get(address)  # the ticket is its session's alone
        as_url = client.get(address.replace("/download/", "/open/"), follow_redirects=False)
        assert as_url.status_code == 404  # a file, not a URL: still to fetch
        assert links(client.get("/").text) == [(address, name)]
        head = client.head(address)
        fetched = client.get(address)
        again = client.get(address)  # e.g. a download manager's: no longer named, still kept
        after = client.get(f"/_composeui/widget/{export_id}").text

        report = tmp_path / "report.csv"
        report.write_bytes(b"x\n")
        view.report = report
        client.post(f"/_composeui/widget/{export_id}", data={"event": "click"})
        ((address, _),) = links(client.get(f"/_composeui/widget/{export_id}").text)
        from_file = client.get(address)
        client.post(f"/_composeui/widget/{export_id}", data={"event": "click"})
        ((address, _),) = links(client.get(f"/_composeui/widget/{export_id}").text)
        report.unlink()
        gone = client.get(address)
        view.download("notes", b"# Notes", "text/markdown")  # outside any request
        ((address, _),) = links(client.get(f"/_composeui/widget/{export_id}").text)
        notes = client.get(address)
        view.export.content = None  # gives nothing
        nothing = client.post(f"/_composeui/widget/{export_id}", data={"event": "click"}).text

    assert stolen.status_code == 404
    assert head.status_code == 200
    assert fetched.content == again.content == b"a,b\n1,2\n"
    assert fetched.headers["content-disposition"].endswith("''report%20%C3%A9.csv")
    assert 'id="cui-downloads"' not in after
    assert from_file.content == b"x\n"
    assert gone.status_code == 404
    assert notes.headers["content-type"] == "text/markdown; charset=utf-8"
    assert 'id="cui-downloads"' not in nothing


def test_a_file_made_in_a_job_is_named_by_the_jobs_poll_the_button_disabled_meanwhile() -> None:
    views: list[ReportMainView] = []

    class ReportApp(WebApplication[ReportMainView]):
        @override
        def setup_session(self, main_view: ReportMainView) -> None:
            main_view.status_bar.timeout = 0
            views.append(main_view)

    release = threading.Event()
    outcomes: list[bytes | OSError] = [b"dropped", b"late", OSError("disk full")]

    def make() -> bytes:
        release.wait(10)
        outcome = outcomes.pop(0)
        if isinstance(outcome, OSError):
            raise outcome
        return outcome

    def poll_until_over(client: TestClient, view: ReportMainView) -> str:
        """Get the jobs poll's answer once the job is over."""
        deadline = time.monotonic() + 10
        while view.jobs.is_running and time.monotonic() < deadline:
            time.sleep(0.01)
        response: httpx.Response = client.get("/_composeui/jobs")
        return response.text

    with _Browser(ReportApp(build_main_view=ReportMainView).create_starlette_app()) as client:
        client.get("/")
        (view,) = views
        view.later.content = make
        later_id = _widget_id(view.later.renderer)

        started = client.post(f"/_composeui/widget/{later_id}", data={"event": "click"}).text
        refused = client.post(
            f"/_composeui/widget/{later_id}", data={"event": "click"}
        )  # while it runs
        view.jobs.drop()  # as New and Open do: the file is the study's replaced
        dropped = client.get(f"/_composeui/widget/{later_id}").text
        release.set()
        deadline = time.monotonic() + 10
        while view.jobs.has_workers and time.monotonic() < deadline:
            time.sleep(0.01)
        after_drop = client.get("/_composeui/jobs").text

        client.post(f"/_composeui/widget/{later_id}", data={"event": "click"})
        polled = poll_until_over(client, view)
        ((address, name),) = [
            (a["href"], a["download"])
            for tag, a in _swapped(polled, "cui-downloads").descendants
            if tag == "a"
        ]
        fetched = client.get(address or "")

        client.post(f"/_composeui/widget/{later_id}", data={"event": "click"})
        failed = poll_until_over(client, view)

    assert "disabled" in _swapped(started, later_id).attributes
    assert refused.status_code == 400
    assert "disabled" not in _element(dropped, later_id).attributes
    assert 'id="cui-downloads"' not in after_drop
    assert "disabled" not in _swapped(polled, later_id).attributes
    assert (name, fetched.content) == ("later.csv", b"late")
    assert "Can't make the file: disk full." in html.unescape(failed)
    assert "disabled" not in _swapped(failed, later_id).attributes
    assert 'id="cui-downloads"' not in failed


def test_a_url_the_app_opens_is_named_until_the_page_of_its_session_opens_its_tab() -> None:
    views: list[OpeningMainView] = []

    class OpeningApp(WebApplication[OpeningMainView]):
        @override
        def setup_session(self, main_view: OpeningMainView) -> None:
            views.append(main_view)

    def tabs(markup: str) -> tuple[list[str], str]:
        """Get the address of each link the page opens in a new tab, and their text."""
        marker = _element(markup, "cui-downloads")
        found = [
            a["href"] or ""
            for tag, a in marker.descendants
            if tag == "a" and "data-open" in a and a["target"] == "_blank"
        ]
        return found, marker.text.strip()

    starlette_app = OpeningApp(build_main_view=OpeningMainView).create_starlette_app()
    with _Browser(starlette_app) as client, _Browser(starlette_app) as other:
        client.get("/")
        other.get("/")
        help_id = _widget_id(views[0].help.renderer)

        body = client.post(f"/_composeui/widget/{help_id}", data={"event": "click"}).text
        (address,), text = tabs(body)
        assert text == HELP_URL  # shown if the browser refuses the tab
        assert tabs(client.get("/").text) == ([address], text)  # until the tab follows it
        ticket = address.rsplit("/", 1)[-1]
        stolen = other.get(address, follow_redirects=False)  # its session's alone
        as_file = client.get(f"/_composeui/download/{ticket}")  # a URL, not a file
        assert tabs(client.get("/").text) == ([address], text)  # still to open
        followed = client.get(address, follow_redirects=False)
        after = client.get("/").text

    assert stolen.status_code == as_file.status_code == 404
    assert followed.status_code == 303
    assert followed.headers["location"] == HELP_URL
    assert followed.headers["cache-control"] == "no-store"
    assert tabs(after) == ([], "")
    assert views[0].notification.message == ""  # the browser opens it: nothing to tell


def test_a_session_keeps_its_newest_files_within_its_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [0.0]
    kept = Downloads(clock=lambda: now[0])
    oldest = kept.add(DownloadedFile("oldest", b"", "text/plain"))
    tickets = [kept.add(DownloadedFile(str(i), b"", "text/plain")) for i in range(MAX_DOWNLOADS)]
    assert kept.take(oldest) is None  # one past the count
    fetched = tickets[-1]
    assert kept.take(fetched) is not None
    assert fetched not in dict(kept.tickets())  # no longer named
    now[0] = FETCHED_TTL + 1
    assert kept.take(fetched) is None  # gone a while after its fetch
    assert len(kept.tickets()) == MAX_DOWNLOADS - 1  # the others still kept
    now[0] = DOWNLOAD_TTL + 1
    assert kept.tickets() == []
    monkeypatch.setattr(downloads_module, "MAX_DOWNLOAD_BYTES", 4)
    kept.add(DownloadedFile("a", b"ab", "text/plain"))
    url = OpenedUrl("https://example.org")  # no bytes
    kept.add(url)
    b = DownloadedFile("b", b"ab", "text/plain")
    kept.add(b)
    c = DownloadedFile("c", b"a", "text/plain")
    kept.add(c)  # 5 bytes: the oldest goes
    assert [kept for _, kept in kept.tickets()] == [url, b, c]


class _ReportApp(WebApplication[ReportMainView]):
    """The report app, keeping each session's main view."""

    def __init__(self, settings: WebSettings | None = None) -> None:
        super().__init__(build_main_view=ReportMainView, settings=settings)
        self.views: list[ReportMainView] = []

    @override
    def setup_session(self, main_view: ReportMainView) -> None:
        self.views.append(main_view)


def _stream_ticket(
    client: TestClient, view: ReportMainView, write: Callable[[BinaryIO], object]
) -> str:
    """Give `write` as the report, click Export, and get the address that the page fetches."""
    view.report = StreamContent(write)
    body = client.post(
        f"/_composeui/widget/{_widget_id(view.export.renderer)}", data={"event": "click"}
    ).text
    # the newest: the answer names each file not fetched yet
    *_, address = [
        a["href"] or "" for tag, a in _swapped(body, "cui-downloads").descendants if tag == "a"
    ]
    return address


def test_a_stream_is_written_once_by_the_first_fetch_of_its_ticket(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = _ReportApp()
    rows = range(50_000)
    writes: list[str] = []

    def write(sink: BinaryIO) -> None:
        writes.append("write")
        sink.writelines(b"%d,row\n" % row for row in rows)

    def fails_first(_sink: BinaryIO) -> None:
        msg = "source gone"
        raise ValueError(msg)

    def fails_later(sink: BinaryIO) -> None:
        sink.write(bytes(DOWNLOAD_CHUNK_SIZE))
        msg = "source gone"
        raise ValueError(msg)

    with _Browser(app.create_starlette_app()) as client:
        client.get("/")
        (view,) = app.views
        address = _stream_ticket(client, view, write)
        written_by_click = len(writes)
        head = client.head(address)
        written_by_head = len(writes)
        fetched = client.get(address, headers={"Accept-Encoding": "gzip"})
        again = client.get(address)  # e.g. a download manager's: written once only
        failed_first = client.get(_stream_ticket(client, view, fails_first))
        later = _stream_ticket(client, view, fails_later)
        # its first bytes sent, the connection breaks: the browser shows a failed download
        with pytest.raises(StreamFailedError):
            client.get(later)

    assert (written_by_click, written_by_head) == (0, 0)
    assert head.status_code == 200
    assert "content-length" not in head.headers  # unknown until written
    assert fetched.content == b"".join(b"%d,row\n" % row for row in rows)
    assert fetched.headers["content-disposition"].endswith("''report%20%C3%A9.csv")
    assert "content-encoding" not in fetched.headers  # sent as written, not compressed
    assert writes == ["write"]
    assert again.status_code == 404
    assert failed_first.status_code == 500
    assert "Can't write a download." in caplog.text


@pytest.mark.asyncio
async def test_a_stream_s_writer_waits_while_no_one_reads_and_stops_once_canceled() -> None:
    returned = 0
    stopped: list[DownloadCanceledError] = []
    waiting = threading.Event()

    class WatchedCondition(threading.Condition):
        @override
        def wait(self, timeout: float | None = None) -> bool:
            waiting.set()  # the writer still holds the lock: a cancel comes once it waits
            return super().wait(timeout)

    def write(sink: BinaryIO) -> None:
        nonlocal returned
        try:
            while True:
                sink.write(bytes(DOWNLOAD_CHUNK_SIZE))  # a piece each
                returned += 1
        except DownloadCanceledError as error:
            stopped.append(error)
            raise

    watched = types.SimpleNamespace(Condition=WatchedCondition, Thread=threading.Thread)
    with mock.patch.object(streaming_module, "threading", watched):
        stream = Stream(StreamContent(write))
    stream.start()
    loop = asyncio.get_running_loop()
    assert await loop.run_in_executor(None, waiting.wait, 10)
    stream.cancel()
    await asyncio.wait_for(stream.ended(), 10)

    assert returned == MAX_QUEUED_BYTES // DOWNLOAD_CHUNK_SIZE  # the pieces that fill the room
    assert len(stopped) == 1
    with pytest.raises(StreamFailedError):  # what was written isn't sent: the file is cut
        async for _ in stream.pieces():
            pass


@pytest.mark.asyncio
async def test_a_stream_s_reader_waits_for_more_pieces_until_the_writer_finishes() -> None:
    release = threading.Event()
    requested = asyncio.Event()
    first_piece = bytes(DOWNLOAD_CHUNK_SIZE)

    def write(sink: BinaryIO) -> None:
        sink.write(first_piece)
        assert release.wait(10)
        sink.write(b"last")

    stream = Stream(StreamContent(write))
    pieces = stream.pieces()

    async def read_next() -> bytes:
        requested.set()
        return await pieces.__anext__()

    async with stream.running():
        try:
            assert await asyncio.wait_for(stream.first(), 10) is None
            assert await asyncio.wait_for(pieces.__anext__(), 10) == first_piece
            reading = asyncio.ensure_future(read_next())
            await asyncio.wait_for(requested.wait(), 10)
            # read_next runs until it suspends: there is no next piece until the gate opens.
            assert not reading.done()
        finally:
            release.set()

        assert await asyncio.wait_for(reading, 10) == b"last"
        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(pieces.__anext__(), 10)


@pytest.mark.asyncio
async def test_a_stream_canceled_midway_waits_for_its_writer_to_end() -> None:
    loop = asyncio.get_running_loop()
    started = asyncio.Event()
    cleaning_up = asyncio.Event()
    release = threading.Event()
    finished = threading.Event()

    def write(sink: BinaryIO) -> None:
        try:
            while True:
                sink.write(bytes(DOWNLOAD_CHUNK_SIZE))
        except DownloadCanceledError:
            loop.call_soon_threadsafe(cleaning_up.set)
            assert release.wait(10)  # the writer's cleanup, e.g. closing its source
            finished.set()
            raise

    stream = Stream(StreamContent(write))

    async def answer() -> None:
        async with stream.running():
            assert await stream.first() is None
            started.set()
            await asyncio.Event().wait()

    task = asyncio.ensure_future(answer())
    try:
        await asyncio.wait_for(started.wait(), 10)
        # as uvicorn cancels the answers when the server stops, then `asyncio.run` as it ends
        task.cancel()
        await asyncio.wait_for(cleaning_up.wait(), 10)
        assert not task.done()
        task.cancel()
        await asyncio.sleep(0)  # deliver the second cancel while the writer is still held
        assert not task.done()
    finally:
        release.set()
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.wait_for(task, 10)

    # the answer's place and session are freed once nothing writes any more
    assert task.cancelled()
    assert finished.is_set()


def test_the_server_writes_at_most_its_streams_at_once_the_next_waiting() -> None:
    app = _ReportApp(WebSettings(max_download_streams=1))
    starlette_app = app.create_starlette_app()
    limiter = starlette_app.state.stream_places.server
    first_writing, release, second_started = threading.Event(), threading.Event(), threading.Event()

    def first(sink: BinaryIO) -> None:
        sink.write(b"first")
        first_writing.set()
        assert release.wait(10)

    def second(sink: BinaryIO) -> None:
        second_started.set()
        sink.write(b"second")

    with _Browser(starlette_app) as client, ThreadPoolExecutor(2) as pool:
        client.get("/")
        (view,) = app.views
        first_address = _stream_ticket(client, view, first)
        second_address = _stream_ticket(client, view, second)
        first_fetch = pool.submit(client.get, first_address)
        assert first_writing.wait(10)
        second_fetch = pool.submit(client.get, second_address)
        for _ in range(1000):  # until the second asks for a place
            if limiter.statistics().tasks_waiting == 1:
                break
            time.sleep(0.01)
        waiting = limiter.statistics().tasks_waiting
        started_meanwhile = second_started.is_set()
        release.set()
        contents = (first_fetch.result(10).content, second_fetch.result(10).content)

    assert waiting == 1
    assert not started_meanwhile
    assert contents == (b"first", b"second")


def test_a_session_writes_at_most_its_streams_at_once_leaving_the_others_to_other_browsers() -> (
    None
):
    app = _ReportApp(WebSettings(max_download_streams=2, max_session_download_streams=1))
    starlette_app = app.create_starlette_app()
    first_writing, release, second_started = threading.Event(), threading.Event(), threading.Event()

    def first(sink: BinaryIO) -> None:
        sink.write(b"first")
        first_writing.set()
        assert release.wait(10)

    def second(sink: BinaryIO) -> None:
        second_started.set()
        sink.write(b"second")

    with _Browser(starlette_app) as alice, ThreadPoolExecutor(3) as pool:
        # on Alice's event loop: a server has one, where a place freed wakes the next
        bob = _Browser(starlette_app)
        bob.portal = alice.portal
        alice.get("/")
        bob.get("/")
        alice_view, bob_view = app.views
        try:
            first_fetch = pool.submit(alice.get, _stream_ticket(alice, alice_view, first))
            assert first_writing.wait(10)
            second_fetch = pool.submit(alice.get, _stream_ticket(alice, alice_view, second))
            alice_places = starlette_app.state.stream_places.of(_session_of(starlette_app, alice))
            for _ in range(1000):  # until Alice's second waits for a place of her own
                if alice_places.statistics().tasks_waiting == 1:
                    break
                time.sleep(0.01)
            waiting = alice_places.statistics().tasks_waiting
            # the server's second place: Alice's second waits without it
            other = pool.submit(
                bob.get, _stream_ticket(bob, bob_view, lambda sink: sink.write(b"b"))
            )
            bob_content = other.result(10).content
            started_meanwhile = second_started.is_set()
        finally:
            release.set()
        contents = (first_fetch.result(10).content, second_fetch.result(10).content)

    assert waiting == 1
    assert bob_content == b"b"
    assert not started_meanwhile
    assert contents == (b"first", b"second")


def test_a_session_that_ends_stops_its_streams_and_starts_none() -> None:
    app = _ReportApp(WebSettings(max_download_streams=1))
    starlette_app = app.create_starlette_app()
    limiter = starlette_app.state.stream_places.server
    started, go = threading.Event(), threading.Event()
    stopped: list[DownloadCanceledError] = []
    writers: list[str] = []

    def write(sink: BinaryIO) -> None:
        writers.append("write")
        started.set()
        assert go.wait(10)
        try:
            sink.write(bytes(DOWNLOAD_CHUNK_SIZE))
        except DownloadCanceledError as error:
            stopped.append(error)
            raise

    with _Browser(starlette_app) as client, ThreadPoolExecutor(2) as pool:
        client.get("/")
        (view,) = app.views
        running = pool.submit(client.get, _stream_ticket(client, view, write))
        assert started.wait(10)
        waiting = pool.submit(client.get, _stream_ticket(client, view, write))
        for _ in range(1000):  # until the second waits for a place
            if limiter.statistics().tasks_waiting == 1:
                break
            time.sleep(0.01)
        # the sessions end, as one does at Exit (`SessionStore.drop`) or past `session_ttl`
        starlette_app.state.sessions.close_all()
        go.set()
        responses = (running.result(10).status_code, waiting.result(10).status_code)

    assert responses == (404, 404)  # as files gone
    assert len(stopped) == 1
    assert writers == ["write"]  # the second never started


#: an app whose Export writes for ever, until stopped; it notes the error that stopped it
_ENDLESS_EXPORT_APP = """
import os, pathlib, sys, time
from composeui.core.view import DownloadView, MainView, StreamContent, child, define_view
from composeui.core.application import WebSettings
from composeui.webcore.webapplication import WebApplication

def write(sink):
    try:
        while True:
            sink.write(bytes(65536))
            time.sleep(0.01)
    except Exception as error:
        pathlib.Path(os.environ["STOPPED"]).write_text(type(error).__name__)
        raise

@define_view
class ExportMainView(MainView):
    export: DownloadView = child(DownloadView, text="Export", filename="endless.bin")

    def __attrs_post_init__(self):
        super().__attrs_post_init__()
        self.export.content = lambda: StreamContent(write)

WebApplication(
    build_main_view=ExportMainView, settings=WebSettings(shutdown_timeout=1)
).run()
"""


@pytest.mark.skipif(sys.platform == "win32", reason="Ctrl+C is a console event on Windows")
def test_a_server_that_stops_ends_the_downloads_being_written(tmp_path: Path) -> None:
    script = tmp_path / "app.py"
    script.write_text(_ENDLESS_EXPORT_APP)
    stopped = tmp_path / "stopped"
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    program = subprocess.Popen(  # noqa: S603 (a command the code builds, no user input)
        [sys.executable, str(script), "--port", str(port)],
        cwd=tmp_path,
        env={**os.environ, "STOPPED": str(stopped)},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        with httpx.Client(
            base_url=f"http://127.0.0.1:{port}", headers={"Sec-Fetch-Site": "same-origin"}
        ) as client:
            page = None
            for _ in range(300):  # until the server serves
                with contextlib.suppress(httpx.TransportError):
                    page = client.get("/").text
                    break
                time.sleep(0.1)
            assert page is not None
            match = re.search(r'hx-post="(/_composeui/widget/[^"]+)"[^>]*>Export<', page)
            assert match is not None
            body = client.post(match[1], data={"event": "click"}).text
            ticket = re.search(r'href="(/_composeui/download/[^"]+)"', body)
            assert ticket is not None
            with client.stream("GET", ticket[1]) as download:
                # kept: an iterator closed would close the download
                pieces = download.iter_raw()
                next(pieces)  # being written
                program.send_signal(signal.SIGINT)  # Ctrl+C
                # past `shutdown_timeout`, not once the endless file is sent
                code = program.wait(timeout=30)
    finally:
        if program.poll() is None:
            program.kill()
            program.wait()

    assert code == 0
    assert stopped.read_text() == "DownloadCanceledError"


def test_a_download_of_whatever_name_has_a_header_naming_it() -> None:
    views: list[RunMainView] = []

    class RunApp(WebApplication[RunMainView]):
        @override
        def setup_session(self, main_view: RunMainView) -> None:
            views.append(main_view)

    with _Browser(RunApp(build_main_view=RunMainView).create_starlette_app()) as client:
        client.get("/")
        (view,) = views
        address = f"/_composeui/widget/{_widget_id(view.output.renderer)}/text"

        # any characters a name can hold: quotes, slashes, line breaks, letters beyond ASCII
        @given(st.text(st.characters(codec="utf-8"), min_size=1, max_size=12))
        @example('a\x1f"b\\.log')  # a control character: uvicorn refused the header
        @example("runs/1.log")  # RFC 5987 takes no "/"
        def download(name: str) -> None:
            view.output.export_filename = name
            header = client.get(address).headers["content-disposition"]
            matched = _DISPOSITION.fullmatch(header)
            assert matched is not None, header
            assert unquote(matched[2]) == name

        download()

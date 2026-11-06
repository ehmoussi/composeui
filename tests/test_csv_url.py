"""CSV URL decoding, resource ownership, and network errors."""

from __future__ import annotations

import csv
import gzip
import socket
import threading
from contextlib import ExitStack
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import TYPE_CHECKING, Any
from urllib.error import HTTPError
from urllib.request import urlopen

import attrs
import pytest

from composeui.core import sqlitemodel
from composeui.core.model import RefusedError
from composeui.core.sqlitemodel import AllowedUrls, CSVSqliteTable, SqliteModel, open_csv_url

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@attrs.define
class DownloadRow:
    name: str
    value: float


class DownloadRows(CSVSqliteTable, row_type=DownloadRow, name="download"):
    pass


@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("encoding", ["utf-8", "latin-1"])
def test_csv_url_decodes_content_preserves_newlines_and_closes_text(
    tmp_path: Path, compressed: bool, encoding: str
) -> None:
    # Neither the suffix nor the CSV's embedded newlines should affect decoding.
    path = tmp_path / "data"
    payload = 'name;value\r\n"Café\r\nstation";1.5\r\n'.encode(encoding)
    path.write_bytes(gzip.compress(payload) if compressed else payload)
    with open_csv_url(path.as_uri(), encoding=encoding) as text:
        assert list(csv.DictReader(text, delimiter=";")) == [
            {"name": "Café\r\nstation", "value": "1.5"}
        ]
    assert text.closed


@pytest.mark.parametrize(
    ("payload", "encoding", "error"),
    [
        (b"\xff", "utf-8", UnicodeDecodeError),
        (gzip.compress(b"name\nvalue\n", mtime=0)[:-8], "utf-8", EOFError),
        (b"name\nvalue\n", "not-an-encoding", LookupError),
    ],
    ids=["decoding", "gzip-footer", "encoding-setup"],
)
def test_csv_url_closes_the_response_when_decoding_or_stream_setup_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    payload: bytes,
    encoding: str,
    error: type[Exception],
) -> None:
    path = tmp_path / "data"
    path.write_bytes(payload)
    responses: list[Any] = []

    def record_open(url: str, *, timeout: float) -> Any:
        response = urlopen(url, timeout=timeout)  # noqa: S310 (the test supplies its local file URL)
        responses.append(response)
        return response

    monkeypatch.setattr(sqlitemodel, "urlopen", record_open)
    with pytest.raises(error), open_csv_url(path.as_uri(), encoding=encoding) as text:
        text.read()
    assert len(responses) == 1
    assert responses[0].closed


@pytest.mark.parametrize("url", ["ftp://example.org/data.csv", "data:text/csv,name", "data.csv"])
def test_csv_url_rejects_unsupported_schemes(url: str) -> None:
    with ExitStack() as resources, pytest.raises(ValueError, match="must use http, https or file"):
        resources.enter_context(open_csv_url(url))


def test_csv_url_reads_http_and_propagates_http_errors_and_socket_timeouts() -> None:
    release = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/slow":
                release.wait()
            elif self.path == "/missing":
                self.send_error(404)
            else:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(gzip.compress(b'name;value\r\n"Station; A";1.5\r\n'))

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    model = SqliteModel()
    try:
        with open_csv_url(f"{url}/download?name=data", timeout=2) as text:
            assert list(csv.DictReader(text, delimiter=";")) == [
                {"name": "Station; A", "value": "1.5"}
            ]
        # An HTTP response cannot seek back after dialect detection.
        rows = model.add_table(DownloadRows)
        assert list(rows.fill_from_url(f"{url}/download", sniff=True, timeout=2)) == [1]
        assert rows.source().cells([1], ["name", "value"]) == {1: ["Station; A", 1.5]}
        with ExitStack() as resources, pytest.raises(HTTPError) as caught:
            resources.enter_context(open_csv_url(f"{url}/missing", timeout=2))
        assert caught.value.code == 404
        with (
            ExitStack() as resources,
            pytest.raises((TimeoutError, socket.timeout)),
        ):
            resources.enter_context(open_csv_url(f"{url}/slow", timeout=0.1))
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join()
        model.close()


@pytest.fixture
def redirecting_server() -> Iterator[tuple[str, list[str]]]:
    """Serve a CSV at `/data`, and redirects to it and to another host; lists the requests."""
    requests: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            requests.append(self.path)
            if self.path == "/data":
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"name,value\nA,1.5\n")
                return
            self.send_response(302)
            host = "evil.invalid" if self.path == "/away" else self.headers["Host"]
            self.send_header("Location", f"http://{host}/data")
            self.end_headers()

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", requests
    server.shutdown()
    server.server_close()
    thread.join()


@pytest.mark.parametrize(
    "url",
    [
        "https://elsewhere.org/data.csv",
        "https://data.example.org.elsewhere.org/data.csv",
        "http://data.example.org/data.csv",
        "file:///etc/passwd",
        "file://data.example.org/etc/passwd",
        "ftp://data.example.org/data.csv",
        "https://user@data.example.org/data.csv",
        "https://elsewhere.org\\@data.example.org/data.csv",
        "https:///data.csv",
        "https://[broken/data.csv",
        "https://data.example.org:6379/data.csv",  # another service of the host
        "https://data.example.org:80/data.csv",  # another scheme's port
        "https://data.example.org:notaport/data.csv",
    ],
)
def test_allowed_urls_refuse_a_url_outside_them_before_any_request(url: str) -> None:
    allowed = AllowedUrls(hosts={"data.example.org"})
    with pytest.raises(RefusedError, match="address"):
        allowed.check(url)
    allowed.check("https://DATA.example.org/data.csv?a=1")  # names without case
    allowed.check("https://data.example.org:443/data.csv")  # the scheme's own port


def test_allowed_urls_never_take_a_local_file_even_when_named() -> None:
    allowed = AllowedUrls(hosts={""}, schemes={"file"})
    with pytest.raises(RefusedError):
        allowed.check("file:///etc/passwd")


@pytest.mark.parametrize(
    "url", ["ftp://data.example.org/a.csv", "https://[broken/a.csv", "https://elsewhere.org/a.csv"]
)
def test_opening_a_url_outside_the_allowed_ones_is_a_refusal(url: str) -> None:
    """Not `ValueError`, which an app's `except RefusedError` would miss."""
    with (
        pytest.raises(RefusedError),
        open_csv_url(url, allowed=AllowedUrls(hosts={"data.example.org"})),
    ):
        pass


def test_allowed_urls_take_a_port_that_the_app_names() -> None:
    AllowedUrls(hosts={"data.example.org"}, ports={8443}).check("https://data.example.org:8443/a")


def test_a_url_from_a_user_imports_only_within_its_allowed_hosts_and_redirects(
    redirecting_server: tuple[str, list[str]],
) -> None:
    url, requests = redirecting_server
    port = int(url.rsplit(":", maxsplit=1)[1])
    local = AllowedUrls(hosts={"127.0.0.1"}, schemes={"http"}, ports={port})
    following = attrs.evolve(local, follows_redirects=True)
    model = SqliteModel()
    rows = model.add_table(DownloadRows)
    try:
        with pytest.raises(RefusedError, match="isn't allowed"):
            list(rows.fill_from_url(f"{url}/data", allowed=AllowedUrls(hosts={"other.org"})))
        assert requests == []  # refused before its request

        assert list(rows.fill_from_url(f"{url}/data", allowed=local)) == [1]
        requests.clear()

        # a redirect, refused by default; followed only to an allowed host
        with pytest.raises(RefusedError, match="redirects"):
            list(rows.fill_from_url(f"{url}/near", allowed=local))
        assert requests == ["/near"]
        assert list(rows.fill_from_url(f"{url}/near", allowed=following)) == [1]
        requests.clear()
        with pytest.raises(RefusedError, match="isn't allowed"):
            list(rows.fill_from_url(f"{url}/away", allowed=following))
        assert requests == ["/away"]
        assert rows.fetch_column("SELECT COUNT(*) FROM download") == [2]
    finally:
        model.close()

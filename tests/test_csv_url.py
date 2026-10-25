"""CSV URL decoding, resource ownership, and network errors."""

from __future__ import annotations

import csv
import gzip
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import TYPE_CHECKING, Any
from urllib.error import HTTPError
from urllib.request import urlopen

import attrs
import pytest

from composeui.core import sqlitemodel
from composeui.core.sqlitemodel import CSVSqliteTable, SqliteModel, open_csv_url

if TYPE_CHECKING:
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
    with pytest.raises(ValueError, match="must use http, https or file"), open_csv_url(url):
        pytest.fail("An unsupported URL must not open")


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
        with pytest.raises(HTTPError) as caught, open_csv_url(f"{url}/missing", timeout=2):
            pytest.fail("An HTTP error must propagate")
        assert caught.value.code == 404
        with (
            pytest.raises((TimeoutError, socket.timeout)),
            open_csv_url(f"{url}/slow", timeout=0.1),
        ):
            pytest.fail("A socket timeout must propagate")
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join()
        model.close()

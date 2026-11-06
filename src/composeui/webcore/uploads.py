"""Receive an upload straight into a file, without another copy or the session's lock.

Starlette's `Request.form` spools a file to a temporary file that a route can only copy. Here,
the body goes to a file of a scratch folder as it arrives, and stops going there once it passes
the limit. The session then moves that file where it keeps it (see `WebSession.pick_file`).
"""

from __future__ import annotations

import contextlib
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO, NamedTuple

import python_multipart
from python_multipart.exceptions import MultipartParseError
from python_multipart.multipart import parse_options_header
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from starlette.requests import Request

#: the most text fields a form may hold, and the largest one, in bytes: the body's limit
#: leaves room for a whole file, which a field would keep in memory
MAX_FIELDS = 100
MAX_FIELD_SIZE = 1024 * 1024
#: the most bytes of headers that a part of a form may have, kept in memory too
MAX_PART_HEADERS_SIZE = 16 * 1024


class ReceivedFile(NamedTuple):
    """The file of a form, as it arrived; its path holds nothing when it is too large."""

    filename: str
    media_type: str
    path: Path
    is_too_large: bool


class _Receiver:
    """Keep a form's text fields, and write its one file part to `path`."""

    def __init__(self, path: Path, max_size: int) -> None:
        self._path = path
        self._max_size = max_size
        self._file: BinaryIO | None = None
        self._size = 0
        #: what the current chunk of the body brought for the file, written off the event loop
        self.pending = bytearray()
        self.fields: dict[str, str] = {}
        #: set once its part has ended: a body cut short has no file
        self.received: ReceivedFile | None = None
        self._has_file_part = False
        self._field_name = ""
        self._header_name = bytearray()
        self._header_value = bytearray()
        self._part_headers_size = 0
        self._nb_parts = 0
        self._headers: dict[bytes, bytes] = {}
        self._filename: str | None = None
        self._value = bytearray()

    def on_part_begin(self) -> None:
        # a count of the parts, not of the fields kept: a name sent again replaces its value
        self._nb_parts += 1
        if self._nb_parts > MAX_FIELDS + 1:
            raise HTTPException(400, "The form has too many fields")
        self._part_headers_size = 0
        self._headers = {}
        self._filename = None
        self._value = bytearray()

    def _count_header_bytes(self, nb_bytes: int) -> None:
        self._part_headers_size += nb_bytes
        if self._part_headers_size > MAX_PART_HEADERS_SIZE:
            raise HTTPException(400, "A part of the form has too large headers")

    def on_header_field(self, data: bytes, start: int, end: int) -> None:
        self._count_header_bytes(end - start)
        self._header_name += data[start:end]

    def on_header_value(self, data: bytes, start: int, end: int) -> None:
        self._count_header_bytes(end - start)
        self._header_value += data[start:end]

    def on_header_end(self) -> None:
        self._headers[bytes(self._header_name).lower()] = bytes(self._header_value)
        self._header_name.clear()
        self._header_value.clear()

    def on_headers_finished(self) -> None:
        _, options = parse_options_header(self._headers.get(b"content-disposition", b""))
        if b"name" not in options:
            raise HTTPException(400, "A part of the form has no name")
        self._field_name = options[b"name"].decode("utf-8", "replace")
        if b"filename" not in options:
            return
        if self._has_file_part or self._field_name != "file":
            raise HTTPException(400, "The form takes one file")
        self._has_file_part = True
        self._filename = options[b"filename"].decode("utf-8", "replace")
        self._file = self._path.open("wb")

    def on_part_data(self, data: bytes, start: int, end: int) -> None:
        if self._filename is None:
            if len(self._value) + end - start > MAX_FIELD_SIZE:
                raise HTTPException(400, "A field of the form is too large")
            self._value += data[start:end]
            return
        self._size += end - start
        if self._size <= self._max_size:
            self.pending += data[start:end]
        else:
            self.pending.clear()

    def on_part_end(self) -> None:
        if self._filename is None:
            self.fields[self._field_name] = self._value.decode("utf-8", "replace")
            return
        self.received = ReceivedFile(
            self._filename,
            self._headers.get(b"content-type", b"").decode("latin-1"),
            self._path,
            is_too_large=self._size > self._max_size,
        )

    def write_pending(self) -> None:
        """Write what the file part brought: nothing once the file is over the limit."""
        assert self._file is not None  # a file part brought it
        self._file.write(self.pending)
        self.pending.clear()

    def close(self) -> None:
        if self._file is not None:
            self._file.close()


async def _feed(
    parser: python_multipart.MultipartParser, receiver: _Receiver, stream: AsyncIterator[bytes]
) -> None:
    async for chunk in stream:
        parser.write(chunk)
        if receiver.pending:
            await run_in_threadpool(receiver.write_pending)


async def _receive_multipart(
    request: Request, directory: Path, max_size: int
) -> tuple[ReceivedFile | None, dict[str, str]]:
    _, options = parse_options_header(request.headers.get("content-type", ""))
    if b"boundary" not in options:
        raise HTTPException(400, "The form has no boundary")
    receiver = _Receiver(directory / "upload", max_size)
    parser = python_multipart.MultipartParser(
        options[b"boundary"],
        {
            "on_part_begin": receiver.on_part_begin,
            "on_part_data": receiver.on_part_data,
            "on_part_end": receiver.on_part_end,
            "on_header_field": receiver.on_header_field,
            "on_header_value": receiver.on_header_value,
            "on_header_end": receiver.on_header_end,
            "on_headers_finished": receiver.on_headers_finished,
        },
    )
    try:
        await _feed(parser, receiver, request.stream())
    except MultipartParseError as error:
        raise HTTPException(400, "The form can't be read") from error
    finally:
        await run_in_threadpool(receiver.close)
    return receiver.received, receiver.fields


@contextlib.asynccontextmanager
async def receive_upload(
    request: Request, max_size: int
) -> AsyncIterator[tuple[ReceivedFile | None, dict[str, str]]]:
    """Get a form's file and text fields; its scratch file is gone on leaving, unless moved.

    A file over `max_size` bytes stops going to the disk there. A malformed form raises
    `HTTPException`. A body that isn't a multipart form isn't read: the page sends no other.
    """
    content_type, _ = parse_options_header(request.headers.get("content-type"))
    if content_type != b"multipart/form-data":
        yield None, {}
        return
    directory = Path(await run_in_threadpool(tempfile.mkdtemp, prefix="composeui-"))
    try:
        yield await _receive_multipart(request, directory, max_size)
    finally:
        await run_in_threadpool(shutil.rmtree, directory, ignore_errors=True)

"""Receive an upload straight into a file, without another copy or the session's lock.

Starlette's `Request.form` spools a file to a temporary file that a route can only copy. Here,
the body goes to files of a scratch folder as it arrives, and stops going there once it passes
the limit, or the disk runs short. The session then moves those files where it keeps them
(see `WebSession.pick_file` and `pick_files`).
"""

from __future__ import annotations

import contextlib
import enum
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
#: the most files a form may hold: the files that a user gives together
MAX_UPLOAD_FILES = 100
#: the most bytes of headers that a part of a form may have, kept in memory too
MAX_PART_HEADERS_SIZE = 16 * 1024
#: the bytes written between two checks of the disk's free space: uploads that arrive at once
#: each passed a check at their start
DISK_CHECK_BYTES = 1024 * 1024


class UploadRefusal(enum.Enum):
    """Why the files that arrived aren't kept."""

    TOO_LARGE = enum.auto()
    NO_ROOM = enum.auto()
    TOO_MANY = enum.auto()


class ReceivedFile(NamedTuple):
    """A file of a form, as it arrived; its path holds nothing useful when refused."""

    filename: str
    media_type: str
    path: Path


class ReceivedUpload(NamedTuple):
    """The files of a form, in the order sent, and why they aren't kept, if they aren't.

    Several files are the ones a user chose together: refused or kept together.
    """

    files: tuple[ReceivedFile, ...]
    refusal: UploadRefusal | None


class _Receiver:
    """Keep a form's text fields, and write each of its file parts to a file of `directory`."""

    def __init__(
        self, directory: Path, max_size: int, min_free_disk: int, *, has_room: bool
    ) -> None:
        self._directory = directory
        #: the most bytes of all the files together
        self._max_size = max_size
        self._min_free_disk = min_free_disk
        #: the files of the parts, by part, open until their part ended and was written
        self._files: list[BinaryIO | None] = []
        self._paths: list[Path] = []
        self._size = 0
        #: the bytes written since the last check of the disk: the first write checks it
        self._unchecked = DISK_CHECK_BYTES
        self._has_no_room = not has_room
        #: what the current chunk of the body brought for each file, by its index, in order:
        #: a chunk can end a file and start the next. Written off the event loop.
        self._pending: list[tuple[int, bytes]] = []
        #: the files whose part ended: closed once written
        self._ended: list[int] = []
        self.fields: dict[str, str] = {}
        self._field_name = ""
        self._header_name = bytearray()
        self._header_value = bytearray()
        self._part_headers_size = 0
        #: a count of the text parts, not of the fields kept: a name sent again replaces its value
        self._nb_fields = 0
        self._headers: dict[bytes, bytes] = {}
        #: the index of the current part's file, if the part is a file
        self._file_index: int | None = None
        #: each file part's name and type, once seen: other parts may come after it
        self._received: list[tuple[str, str]] = []
        self._nb_whole_files = 0
        self._value = bytearray()

    @property
    def has_pending(self) -> bool:
        """Tell whether the chunk brought bytes to write, or ended a file to close."""
        return bool(self._pending or self._ended)

    def on_part_begin(self) -> None:
        self._part_headers_size = 0
        self._headers = {}
        self._file_index = None
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
            self._nb_fields += 1
            if self._nb_fields > MAX_FIELDS:
                raise HTTPException(400, "The form has too many fields")
            return
        if self._field_name != "file":
            raise HTTPException(400, "The form takes files only as its field file")
        if len(self._received) == MAX_UPLOAD_FILES:
            raise HTTPException(400, "The form has too many files")
        filename = options[b"filename"].decode("utf-8", "replace")
        media_type = self._headers.get(b"content-type", b"").decode("latin-1")
        self._file_index = len(self._received)
        self._received.append((filename, media_type))
        path = self._directory / f"upload-{self._file_index}"
        self._paths.append(path)
        file = None
        if not self._has_no_room:
            try:
                file = path.open("wb")
            except OSError:  # no room for even a name: the same message for the user
                self._has_no_room = True
        self._files.append(file)

    def on_part_data(self, data: bytes, start: int, end: int) -> None:
        index = self._file_index
        if index is None:
            if len(self._value) + end - start > MAX_FIELD_SIZE:
                raise HTTPException(400, "A field of the form is too large")
            self._value += data[start:end]
            return
        self._size += end - start
        if self._has_no_room or self._size > self._max_size:
            self._pending.clear()  # refused: nothing more goes to the disk
            return
        self._pending.append((index, data[start:end]))

    def on_part_end(self) -> None:
        if self._file_index is None:
            self.fields[self._field_name] = self._value.decode("utf-8", "replace")
            return
        self._nb_whole_files += 1
        self._ended.append(self._file_index)
        self._file_index = None

    def received(self) -> ReceivedUpload | None:
        """Get the files, once the whole body is written: its last bytes may find no room.

        None for a form without a file, or a body cut short in one.
        """
        if not self._received or self._nb_whole_files < len(self._received):
            return None
        refusal = None
        if self._size > self._max_size:
            refusal = UploadRefusal.TOO_LARGE
        elif self._has_no_room:
            refusal = UploadRefusal.NO_ROOM
        files = tuple(
            ReceivedFile(filename, media_type, path)
            for (filename, media_type), path in zip(self._received, self._paths)
        )
        return ReceivedUpload(files, refusal)

    def write_pending(self) -> None:
        """Write what the parts brought, close the ended files; stop for good once short of room."""
        pending, self._pending = self._pending, []
        try:
            for index, data in pending:
                file = self._files[index]
                assert file is not None  # open until its part ends: these bytes came first
                self._unchecked += len(data)
                if self._unchecked >= DISK_CHECK_BYTES:
                    self._unchecked = 0
                    free = shutil.disk_usage(self._directory).free
                    self._has_no_room = free < self._min_free_disk
                if self._has_no_room:
                    break
                file.write(data)
        except OSError:  # the disk is full, whatever the floor: the same message for the user
            self._has_no_room = True
        ended, self._ended = self._ended, []
        for index in ended:
            self._close(index)
        if self._has_no_room:
            self.close()
            # what they held is free again at once, not at the end of the body
            for path in self._paths:
                path.unlink(missing_ok=True)

    def _close(self, index: int) -> None:
        file, self._files[index] = self._files[index], None
        if file is not None:
            try:
                file.close()
            except OSError:  # its last bytes, still in the buffer, found no room: a cut file
                self._has_no_room = True

    def close(self) -> None:
        for index in range(len(self._files)):
            self._close(index)


async def _feed(
    parser: python_multipart.MultipartParser, receiver: _Receiver, stream: AsyncIterator[bytes]
) -> None:
    async for chunk in stream:
        parser.write(chunk)
        if receiver.has_pending:
            await run_in_threadpool(receiver.write_pending)


async def _receive_multipart(
    request: Request, directory: Path | None, max_size: int, min_free_disk: int
) -> tuple[ReceivedUpload | None, dict[str, str]]:
    _, options = parse_options_header(request.headers.get("content-type", ""))
    if b"boundary" not in options:
        raise HTTPException(400, "The form has no boundary")
    # without a directory, the files are refused and their paths never read
    receiver = _Receiver(
        Path(directory or "."), max_size, min_free_disk, has_room=directory is not None
    )
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
    return receiver.received(), receiver.fields


@contextlib.asynccontextmanager
async def receive_upload(
    request: Request, max_size: int, min_free_disk: int = 0
) -> AsyncIterator[tuple[ReceivedUpload | None, dict[str, str]]]:
    """Get a form's files and text fields; their scratch files are gone on leaving, unless moved.

    Files of more than `max_size` bytes together, or that would leave less than
    `min_free_disk` bytes free, stop going to the disk there, and are marked refused. A
    malformed form raises `HTTPException`. A body that isn't a multipart form isn't read: the
    page sends no other.
    """
    content_type, _ = parse_options_header(request.headers.get("content-type"))
    if content_type != b"multipart/form-data":
        yield None, {}
        return
    directory = None
    # no room for a folder: the body is still read, for a notification to say so
    with contextlib.suppress(OSError):
        directory = Path(await run_in_threadpool(tempfile.mkdtemp, prefix="composeui-"))
    try:
        yield await _receive_multipart(request, directory, max_size, min_free_disk)
    finally:
        if directory is not None:
            await run_in_threadpool(shutil.rmtree, directory, ignore_errors=True)

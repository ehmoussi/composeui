"""A download that the app writes as the browser receives it (`StreamContent`).

`GET /download/{ticket}` takes the file (`Downloads.take`), then `StreamResponse` runs its
writer on a thread of its own, outside the session's lock, and sends the pieces that it
writes. The writer waits while `MAX_QUEUED_BYTES` wait to be sent: a slow browser slows it
down, and a file of any size takes little memory. At most
`WebApplication.max_download_streams` run at once on the server, and
`WebApplication.max_session_download_streams` for one session; the next wait for one to end.

The thread and the answer end apart. A browser that leaves, or the session's end, cancels
the stream: the writer's next write raises. The answer then waits for the thread, so that
the session and the stream's place are freed only once nothing writes any more.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
import weakref
from collections import deque
from typing import TYPE_CHECKING, BinaryIO, cast

import anyio
from starlette.responses import PlainTextResponse, Response, StreamingResponse

from composeui.core.view import DOWNLOAD_CHUNK_SIZE, DownloadCanceledError, DownloadSink

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Mapping

    from starlette.types import Receive, Scope, Send

    from composeui.core.view import StreamContent
    from composeui.webcore.session import WebSession

#: the most bytes written and not sent yet, for one stream: past it, the writer waits
MAX_QUEUED_BYTES = 4 * DOWNLOAD_CHUNK_SIZE
#: streams written at once on the server, by default (`WebApplication.max_download_streams`)
MAX_STREAMS = 8
#: streams written at once for one session, by default
#: (`WebApplication.max_session_download_streams`)
MAX_SESSION_STREAMS = 2

LOGGER = logging.getLogger("COMPOSEUI")
_NO_STORE = {"Cache-Control": "no-store"}


class StreamPlaces:
    """The places of the downloads written at once: on the server, and for each session.

    A download waits for one of its session's, then for one of the server's: one waiting for
    its session's holds none of the server's. So one browser can't take them all.
    """

    def __init__(self, total: int = MAX_STREAMS, per_session: int = MAX_SESSION_STREAMS) -> None:
        #: the server's places
        self.server = anyio.CapacityLimiter(total)
        self._per_session = per_session
        # read on the event loop only; a session that ends frees its own
        self._sessions: weakref.WeakKeyDictionary[WebSession, anyio.CapacityLimiter] = (
            weakref.WeakKeyDictionary()
        )

    def of(self, session: WebSession) -> anyio.CapacityLimiter:
        """Get the places of `session`'s downloads, made at its first."""
        places = self._sessions.get(session)
        if places is None:
            places = self._sessions[session] = anyio.CapacityLimiter(self._per_session)
        return places


class StreamFailedError(Exception):
    """A download's writer failed after its first bytes were sent: the file is incomplete."""


class Stream:
    """A `StreamContent` written on a thread of its own, its pieces read on the event loop.

    Make it on the event loop that reads it. The writer waits while `MAX_QUEUED_BYTES` wait;
    `cancel`, from any thread, makes its next write raise, and every one after.
    """

    def __init__(self, content: StreamContent) -> None:
        self._content = content
        self._loop = asyncio.get_running_loop()
        # the pieces, their size, and the outcome: under the condition, which the writer
        # waits on while too many wait
        self._condition = threading.Condition()
        self._pieces: deque[bytes] = deque()
        self._size = 0
        self._is_canceled = False
        self._is_written = False
        self._error: BaseException | None = None
        #: set from the thread once there are pieces, or the outcome: the reader waits on it
        self._ready = asyncio.Event()
        #: set from the thread as it ends
        self._ended = asyncio.Event()
        self._thread = threading.Thread(target=self._write, name="composeui-download", daemon=True)

    def start(self) -> None:
        """Start the writer's thread; none once canceled, e.g. by the session's end."""
        with self._condition:
            is_canceled = self._is_canceled
        if is_canceled:
            self._ended.set()
        else:
            self._thread.start()

    def cancel(self) -> None:
        """Make the writer's next write raise, and stop sending: no one wants the file."""
        with self._condition:
            self._is_canceled = True
            self._condition.notify_all()
        self._call_soon(self._ready.set)

    async def first(self) -> BaseException | None:
        """Wait for the first piece, or for the writer's end; get why it ended if before it.

        `DownloadCanceledError` if canceled first.
        """
        while True:
            with self._condition:
                if self._is_canceled:
                    return DownloadCanceledError()
                if len(self._pieces) > 0:
                    return None
                if self._is_written or self._error is not None:
                    return self._error
                self._ready.clear()
            await self._ready.wait()

    async def pieces(self) -> AsyncIterator[bytes]:
        """Get the pieces as they're written.

        Raise `StreamFailedError` if the writer failed, or the stream was canceled: the file
        is incomplete.
        """
        while True:
            with self._condition:
                if self._is_canceled:
                    raise StreamFailedError
                if len(self._pieces) > 0:
                    piece = self._pieces.popleft()
                    self._size -= len(piece)
                    self._condition.notify_all()
                elif self._error is not None:
                    raise StreamFailedError from self._error
                elif self._is_written:
                    return
                else:
                    self._ready.clear()
                    piece = None
            if piece is None:
                await self._ready.wait()
            else:
                yield piece

    @contextlib.asynccontextmanager
    async def running(self) -> AsyncIterator[None]:
        """Start the writer for the block; then cancel it, and wait for its thread to end.

        The wait is shielded: a canceled answer still waits, so that nothing writes once it
        ends.
        """
        self.start()
        try:
            yield
        finally:
            self.cancel()
            with anyio.CancelScope(shield=True):
                await self.ended()

    async def ended(self) -> None:
        """Wait for the writer's thread to end."""
        await self._ended.wait()

    def _write(self) -> None:
        sink = DownloadSink(self._put)
        try:
            self._content.write(cast("BinaryIO", sink))
            sink.close()
        # the app's writer: anything that ends it ends the file, which the reader then waits
        # for no more
        except BaseException as error:  # noqa: BLE001
            sink.discard()
            with self._condition:
                # the writer may have raised its own error for ours, e.g. Arrow's
                if not self._is_canceled:
                    self._error = error
        else:
            with self._condition:
                self._is_written = True
        finally:
            self._call_soon(self._ready.set)
            self._call_soon(self._ended.set)

    def _put(self, piece: bytes) -> None:
        """Queue a piece for the reader, once there's room; raise once canceled."""
        with self._condition:
            while not self._is_canceled and self._size + len(piece) > MAX_QUEUED_BYTES:
                self._condition.wait()
            if self._is_canceled:
                raise DownloadCanceledError
            self._pieces.append(piece)
            self._size += len(piece)
        self._call_soon(self._ready.set)

    def _call_soon(self, callback: Callable[[], None]) -> None:
        # the loop closes only once the server stopped, after every answer ended
        with contextlib.suppress(RuntimeError):  # the loop closed: no one reads any more
            self._loop.call_soon_threadsafe(callback)


class StreamResponse(Response):
    """Send a `StreamContent` as its writer writes it, holding its session meanwhile.

    It waits for a place among its session's streams, then among the server's (`places`),
    then for the first piece:
    a writer that fails before it gets a 500. One that fails after it breaks the connection,
    so that the browser shows a failed download, not a short file.
    """

    def __init__(
        self,
        session: WebSession,
        content: StreamContent,
        places: StreamPlaces,
        *,
        media_type: str,
        headers: Mapping[str, str],
    ) -> None:
        super().__init__(media_type=media_type)
        self._session = session
        self._content = content
        self._places = places
        self._download_headers = headers

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # left in the reverse order: the place and the session are freed once nothing writes
        async with contextlib.AsyncExitStack() as stack:
            stack.enter_context(self._session.held())
            await stack.enter_async_context(self._places.of(self._session))
            await stack.enter_async_context(self._places.server)
            stream = Stream(self._content)
            stack.enter_context(self._session.streaming(stream))
            await stack.enter_async_context(stream.running())
            await self._send(stream, scope, receive, send)

    async def _send(self, stream: Stream, scope: Scope, receive: Receive, send: Send) -> None:
        error = await stream.first()
        if isinstance(error, DownloadCanceledError):  # the session ended: as a file gone
            gone = PlainTextResponse("Not Found", status_code=404, headers=_NO_STORE)
            await gone(scope, receive, send)
            return
        if error is not None:
            LOGGER.error("Can't write a download.", exc_info=error)
            failed = PlainTextResponse(
                "The file couldn't be made.", status_code=500, headers=_NO_STORE
            )
            await failed(scope, receive, send)
            return
        response = StreamingResponse(
            stream.pieces(), media_type=self.media_type, headers=self._download_headers
        )
        await response(scope, receive, send)

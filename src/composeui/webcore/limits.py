"""Refuse a request body larger than any upload the app accepts, before it is all read.

The routes check an upload's size once they have it (`MAX_STATE_SIZE`, `MAX_FILE_SIZE`),
but Starlette parses a whole multipart body first, spooling its files to temporary files
with no limit: an upload of many gigabytes would fill the disk before that check runs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.datastructures import Headers
from starlette.exceptions import HTTPException
from starlette.responses import PlainTextResponse

from composeui.webcore.session import MAX_FILE_SIZE, MAX_STATE_SIZE

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Message, Receive, Scope, Send

#: largest request body accepted, in bytes: the largest upload, and room around it for the
#: form's other fields, so a file just too large still gets the route's own message
MAX_BODY_SIZE = max(MAX_STATE_SIZE, MAX_FILE_SIZE) + 1024 * 1024


class BodySizeLimitMiddleware:
    """Answer 413 to a request whose body is larger than `max_size` bytes."""

    def __init__(self, app: ASGIApp, max_size: int = MAX_BODY_SIZE) -> None:
        self.app = app
        self.max_size = max_size

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        length = Headers(scope=scope).get("content-length")
        if length is not None and length.isdigit() and int(length) > self.max_size:
            response = PlainTextResponse("Request body too large", status_code=413)
            await response(scope, receive, send)
            return
        received = 0

        async def limited_receive() -> Message:
            # a body without a length (chunked), or longer than it said
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_size:
                    # raised in the route reading the body: Starlette answers it
                    raise HTTPException(413, "Request body too large")
            return message

        await self.app(scope, limited_receive, send)

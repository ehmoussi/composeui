"""Refuse a request body larger than any upload the app accepts, before it is all read.

A route reads a file only up to its limit (`MAX_STATE_SIZE`, `MainView.max_upload_size`), but
it still reads the whole body, and Starlette's form parser spools files with no limit: an upload
of many gigabytes would fill the disk, or keep the server busy, before the route could answer.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from starlette.datastructures import Headers
from starlette.exceptions import HTTPException
from starlette.responses import PlainTextResponse

from composeui.webcore.session import MAX_STATE_SIZE

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Message, Receive, Scope, Send


#: room around a file for the form's other fields, so a file just too large still gets the
#: route's own message
_FORM_ROOM = 1024 * 1024
#: largest request body accepted outside the route of file uploads, in bytes: a study
MAX_BODY_SIZE = MAX_STATE_SIZE + _FORM_ROOM
#: the route of file uploads, the only one that writes a body to a file under the app's limits
_UPLOAD_ROUTE = re.compile(r"/widget/[^/]+/file")


def max_upload_body_size(max_upload_size: int) -> int:
    """Get the largest request body that the route of file uploads accepts, in bytes."""
    return max_upload_size + _FORM_ROOM


class BodySizeLimitMiddleware:
    """Answer 413 to a body over `MAX_BODY_SIZE`, or `max_upload_size` for the upload route.

    The app's larger limit reaches no other route: their form parser would spool the body, or
    keep it in memory, under no limit of the disk.
    """

    def __init__(self, app: ASGIApp, max_upload_size: int) -> None:
        self.app = app
        self.max_upload_body_size = max_upload_body_size(max_upload_size)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        is_upload = _UPLOAD_ROUTE.fullmatch(scope["path"]) is not None
        max_size = self.max_upload_body_size if is_upload else MAX_BODY_SIZE
        length = Headers(scope=scope).get("content-length")
        if length is not None and length.isdigit() and int(length) > max_size:
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
                if received > max_size:
                    # raised in the route reading the body: Starlette answers it
                    raise HTTPException(413, "Request body too large")
            return message

        await self.app(scope, limited_receive, send)

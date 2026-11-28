"""The user that a login proxy names in a header of each request (`WebSettings.user_header`).

The proxy logs the user in, and the server takes its word: it can't tell the proxy's
requests from others. So only the proxy may reach the server, and it sets the header on
each request, replacing one that the browser sent.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.responses import PlainTextResponse

if TYPE_CHECKING:
    from collections.abc import Iterable

    from starlette.types import ASGIApp, Receive, Scope, Send


def header_user(headers: Iterable[tuple[bytes, bytes]], name: str) -> str | None:
    """Get the user that the header `name` names; None if none does, or not one alone.

    None for an empty header, one that isn't UTF-8, and two of them: a proxy that adds its
    header beside the browser's, rather than replacing it, sends both.
    """
    key = name.lower().encode("ascii")
    values = [value for header, value in headers if header == key]
    if len(values) != 1:
        return None
    try:
        user = values[0].decode("utf-8")
    except UnicodeDecodeError:
        return None
    return user or None


class UserHeaderMiddleware:
    """Answer 403 to a request whose header doesn't name one user (`header_user`)."""

    def __init__(self, app: ASGIApp, *, header: str) -> None:
        self.app = app
        self._header = header

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and header_user(scope["headers"], self._header) is None:
            # the proxy isn't in front, or doesn't set the header: never a request without
            # a user, which would share the sessions of another
            response = PlainTextResponse("No user: the login proxy names none", status_code=403)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)

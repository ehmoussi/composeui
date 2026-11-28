"""The user that a login proxy names in headers of each request (`WebSettings.user_header`).

The proxy logs the user in, and the server takes its word: it can't tell the proxy's
requests from others. So only the proxy may reach the server, and it sets the headers on
each request, replacing those that the browser sent.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import attrs
from starlette.responses import PlainTextResponse

from composeui.core.client import User

if TYPE_CHECKING:
    from collections.abc import Iterable

    from starlette.types import ASGIApp, Receive, Scope, Send


def _values(headers: Iterable[tuple[bytes, bytes]], name: str) -> list[bytes]:
    """Get the values of each header `name` of a request, in their order."""
    key = name.lower().encode("ascii")
    return [value for header, value in headers if header == key]


def _text(value: bytes) -> str | None:
    """Get a header's value as text; None if it's empty or isn't UTF-8."""
    try:
        return value.decode("utf-8") or None
    except UnicodeDecodeError:
        return None


@attrs.frozen
class UserHeaders:
    """The headers that name the user and give their name and email (`User`)."""

    #: the header of the user's id (`WebSettings.user_header`)
    user: str
    #: the header of their name (`WebSettings.user_name_header`), or None
    name: Optional[str] = None
    #: the header of their email (`WebSettings.user_email_header`), or None
    email: Optional[str] = None

    def refusal(self, headers: Iterable[tuple[bytes, bytes]]) -> str | None:
        """Get why the server refuses a request with these headers; None if it doesn't.

        Refused without one user, and with two of a header: a proxy that adds its header
        beside the browser's, rather than replacing it, sends both.
        """
        headers = list(headers)
        users = _values(headers, self.user)
        if len(users) != 1 or _text(users[0]) is None:
            return "No user: the login proxy names none"
        for name in (self.name, self.email):
            if name is not None and len(_values(headers, name)) > 1:
                return f"Two {name} headers: the login proxy must replace the browser's"
        return None

    def read(self, headers: Iterable[tuple[bytes, bytes]]) -> User:
        """Get the user that the headers of a request name, which `refusal` let through."""
        headers = list(headers)
        (user,) = _values(headers, self.user)

        def optional(name: str | None) -> str | None:
            values = [] if name is None else _values(headers, name)
            return _text(values[0]) if values else None

        return User(id=user.decode("utf-8"), name=optional(self.name), email=optional(self.email))


class UserHeaderMiddleware:
    """Answer 403 to a request that `UserHeaders.refusal` refuses."""

    def __init__(self, app: ASGIApp, *, headers: UserHeaders) -> None:
        self.app = app
        self._headers = headers

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            refusal = self._headers.refusal(scope["headers"])
            if refusal is not None:
                # the proxy isn't in front, or doesn't set the headers: never a request
                # without a user, which would share the sessions of another
                response = PlainTextResponse(refusal, status_code=403)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)

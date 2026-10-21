"""The headers every response carries, whatever route or middleware answers it.

- Clickjacking: another site could show the app in a hidden frame, so the user's clicks
  reach it from the app's own page, which the origin check (`origin.py`) lets through. So
  no page of the app may be shown in a frame.
- No MIME sniffing: a browser keeps to the content type each response says it is, so an
  uploaded or served file can't run as a script or a page it doesn't say it is.
- Referrer: the app's addresses aren't sent to other sites, and its own requests still
  carry them, which the origin check falls back to.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.datastructures import MutableHeaders

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Message, Receive, Scope, Send


class SecurityHeadersMiddleware:
    """Add the framing, sniffing and referrer headers to every response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                # the standard header, and the older one for browsers without it
                headers.append("Content-Security-Policy", "frame-ancestors 'none'")
                headers["X-Frame-Options"] = "DENY"
                # kept when a route sets them (e.g. an icon's)
                headers.setdefault("X-Content-Type-Options", "nosniff")
                headers.setdefault("Referrer-Policy", "same-origin")
            await send(message)

        await self.app(scope, receive, send_with_headers)

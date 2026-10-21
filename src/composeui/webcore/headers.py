"""The headers every response carries, whatever route or middleware answers it.

- Scripts: the page runs only the app's own script files, so text that ever got past
  the escaping (`html.escape`) can't run as a script, inline or evaluated. Inline style
  attributes stay allowed: the renderers lay out with them, and they run nothing.
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


#: the app's own files only; daisyUI's stylesheet draws a few marks from `data:` images
POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self';"
    " style-src-attr 'unsafe-inline'; img-src 'self' data:; object-src 'none';"
    " base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)


class SecurityHeadersMiddleware:
    """Add the content, framing, sniffing and referrer headers to every response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                # beside a route's own (an icon's), which can then only be stricter
                headers.append("Content-Security-Policy", POLICY)
                # the older framing header, for browsers without `frame-ancestors`
                headers["X-Frame-Options"] = "DENY"
                # kept when a route sets them (e.g. an icon's)
                headers.setdefault("X-Content-Type-Options", "nosniff")
                headers.setdefault("Referrer-Policy", "same-origin")
            await send(message)

        await self.app(scope, receive, send_with_headers)

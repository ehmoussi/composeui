"""Refuse requests that change a session from another origin (cross-site request forgery).

The session cookie is `SameSite=Lax`, but "same site" ignores the port and spans sibling
subdomains: a page on `localhost:9000` still sends it to an app on `localhost:8000`. So
every unsafe request must prove it comes from the app's own pages, as OWASP's Fetch
Metadata defense asks: `Sec-Fetch-Site`, else `Origin`, else `Referer`, else refused.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from starlette.datastructures import URL, Headers
from starlette.responses import PlainTextResponse

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Receive, Scope, Send

#: methods that only read: every request changing a session uses another one
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def is_same_origin(scope: Scope) -> bool:
    """Tell whether the browser says the request comes from a page of this origin.

    A browser sets these headers itself: no page can forge them. A request without any
    is refused: it isn't evidence of a same-origin one (an old browser, or a proxy
    stripping them).
    """
    headers = Headers(scope=scope)
    site = headers.get("sec-fetch-site")
    if site is not None:
        return site == "same-origin"
    url = URL(scope=scope)
    own = f"{url.scheme}://{url.netloc}"
    origin = headers.get("origin")
    if origin is not None:
        return origin == own  # "null" (e.g. a sandboxed frame) is never ours
    referer = headers.get("referer")
    if referer is not None:
        parts = urlsplit(referer)
        return f"{parts.scheme}://{parts.netloc}" == own
    return False


class SameOriginMiddleware:
    """Answer 403 to an unsafe request (e.g. a POST) that another origin sent."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] == "http"
            and scope["method"] not in SAFE_METHODS
            and not is_same_origin(scope)
        ):
            response = PlainTextResponse("Cross-origin request refused", status_code=403)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)

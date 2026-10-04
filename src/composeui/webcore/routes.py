from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.concurrency import run_in_threadpool
from starlette.responses import HTMLResponse, PlainTextResponse, Response

from composeui.webcore.webrenderer import UnsupportedEventError

if TYPE_CHECKING:
    from starlette.requests import Request

    from composeui.webcore.session import SessionStore, WebSession

#: Every page and fragment reflects live server state: a browser reusing a cached copy
#: (or restoring the fields of one) would show values the server no longer has, e.g.
#: after a server restart.
_NO_STORE = {"Cache-Control": "no-store"}
#: Answer to a widget request whose session is gone (expired, or the server restarted):
#: htmx reloads the page, which starts a fresh session, instead of the request failing.
_RELOAD = {**_NO_STORE, "HX-Refresh": "true"}
#: key of the session id in Starlette's signed session cookie
SESSION_KEY = "composeui_session"


def _store(request: Request) -> SessionStore:
    store: SessionStore = request.app.state.sessions
    return store


def _session(request: Request) -> WebSession | None:
    return _store(request).get(request.session.get(SESSION_KEY))


def homepage(request: Request) -> HTMLResponse:
    session = _session(request)
    if session is None:
        session_id, session = _store(request).create()
        request.session[SESSION_KEY] = session_id
    return HTMLResponse(session.page_html(), headers=_NO_STORE)


async def widget_event(request: Request) -> Response:
    """Dispatch a browser event to a widget; respond with every fragment it changed."""
    session = _session(request)
    if session is None:
        return Response(headers=_RELOAD)
    form = await request.form()
    fields = {name: value for name, value in form.items() if isinstance(value, str)}
    event = fields.pop("event", "")
    widget_id = request.path_params["widget_id"]
    try:
        # view callbacks are plain sync code: keep them off the event loop
        body = await run_in_threadpool(session.handle_event, widget_id, event, fields)
    except UnsupportedEventError as e:
        return PlainTextResponse(str(e), status_code=400)
    if body is None:
        return PlainTextResponse("Unknown widget", status_code=404)
    return HTMLResponse(body, headers=_NO_STORE)


def widget_fragment(request: Request) -> Response:
    """Return a widget's current fragment (e.g. a status bar whose message timed out)."""
    session = _session(request)
    if session is None:
        return Response(headers=_RELOAD)
    body = session.fragment(request.path_params["widget_id"])
    if body is None:
        return PlainTextResponse("Unknown widget", status_code=404)
    return HTMLResponse(body, headers=_NO_STORE)

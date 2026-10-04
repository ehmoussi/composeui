from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response

from composeui.webcore.session import MAX_STATE_SIZE
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
    if session.closed:
        # e.g. Exit: end the session; the page it lands on starts a fresh one
        _store(request).drop(request.session.get(SESSION_KEY))
        return Response(headers={**_NO_STORE, "HX-Redirect": "/"})
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


def state_download(request: Request) -> Response:
    """Download the session's state as a file, the web side of `MainView.save_state`.

    A plain link, not htmx (htmx can't start downloads); without a session, the
    browser is sent to the page, which starts one.
    """
    session = _session(request)
    if session is None:
        return RedirectResponse("/", status_code=303)
    trigger = request.query_params.get("trigger")
    if trigger is not None:
        session.trigger_action(trigger)  # e.g. Save's own `triggered`, before the download
    filename, body = session.save_state()
    headers = {**_NO_STORE, "Content-Disposition": f'attachment; filename="{filename}"'}
    return Response(body, media_type="application/json", headers=headers)


async def state_upload(request: Request) -> Response:
    """Load an uploaded state file, the web side of `MainView.load_state`.

    A load can change any part of the tree, so instead of collecting fragments the page
    reloads; a rejected file leaves the state alone and says why in the status bar.
    """
    session = _session(request)
    if session is None:
        return Response(headers=_RELOAD)
    form = await request.form(max_files=1)
    upload = form.get("file")
    if not isinstance(upload, UploadFile):
        return PlainTextResponse("No file uploaded", status_code=400)
    trigger = form.get("trigger")
    if isinstance(trigger, str):
        # e.g. Open's own `triggered`, before the file is loaded
        await run_in_threadpool(session.trigger_action, trigger)
    # one byte over the limit is enough to know the file is too large
    content = await upload.read(MAX_STATE_SIZE + 1)
    status_bar = await run_in_threadpool(session.load_state, upload.filename or "", content)
    if status_bar is None:
        return Response(headers=_RELOAD)
    return HTMLResponse(status_bar, headers=_NO_STORE)

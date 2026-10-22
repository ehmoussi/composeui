from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import quote

from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.responses import (
    FileResponse,
    HTMLResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)

from composeui.core import chartimage
from composeui.webcore.icons import icon_path
from composeui.webcore.session import MAX_FILE_SIZE, MAX_STATE_SIZE
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
#: An icon's address names its content (see `icons.py`), so it never changes; an SVG
#: opened on its own runs no script and loads nothing.
_ICON_HEADERS = {
    "Cache-Control": "public, max-age=31536000, immutable",
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
    "X-Content-Type-Options": "nosniff",
}
#: key of the session id in Starlette's signed session cookie
SESSION_KEY = "composeui_session"


def _store(request: Request) -> SessionStore:
    store: SessionStore = request.app.state.sessions
    return store


def _session(request: Request) -> WebSession | None:
    return _store(request).get(request.session.get(SESSION_KEY))


def _session_or_new(request: Request) -> WebSession | None:
    """Get the request's session, or a new one; None while the server has too many."""
    session = _session(request)
    if session is None:
        created = _store(request).create()
        if created is None:
            return None
        session_id, session = created
        request.session[SESSION_KEY] = session_id
    return session


def _reload_instance(request: Request) -> str | None:
    """Get the id of this process of a ``--reload`` server; None for another server."""
    instance: str | None = request.app.state.reload_instance
    return instance


def _too_many_sessions() -> Response:
    return PlainTextResponse(
        "Too many sessions are open: try again later.", status_code=503, headers=_NO_STORE
    )


def homepage(request: Request) -> Response:
    """Show the app; one with pages is sent to its first page's address."""
    session = _session_or_new(request)
    if session is None:
        return _too_many_sessions()
    path = session.home_path()
    if path is not None:
        return RedirectResponse(path, status_code=303, headers=_NO_STORE)
    return HTMLResponse(session.page_html(_reload_instance(request)), headers=_NO_STORE)


def page(request: Request) -> Response:
    """Show the app on the page of the address's route (`/<route>`).

    An address no page has is not found, rather than sent to a page: a browser asks
    for addresses of its own (e.g. `/favicon.ico`), which must not navigate.
    """
    session = _session_or_new(request)
    if session is None:
        return _too_many_sessions()
    if not session.open_route(request.path_params["route"]):
        return PlainTextResponse("Not Found", status_code=404, headers=_NO_STORE)
    return HTMLResponse(session.page_html(_reload_instance(request)), headers=_NO_STORE)


def reload_poll(request: Request) -> Response:
    """Tell a page of a ``--reload`` server whether another process of it served the page.

    Then its answer reloads the page (``HX-Refresh``), which runs the changed code. Only
    a read: the next request restores the session (`SessionStore`). A server without
    ``--reload`` reloads the page too: a tab a ``--reload`` server served, left open on
    its address, would else ask it every second, for ever.
    """
    instance = _reload_instance(request)
    if instance is not None and request.query_params.get("instance") == instance:
        return Response(status_code=204, headers=_NO_STORE)
    return Response(headers=_RELOAD)


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
        result = await run_in_threadpool(session.handle_event, widget_id, event, fields)
    except UnsupportedEventError as e:
        return PlainTextResponse(str(e), status_code=400)
    if result is None:
        return PlainTextResponse("Unknown widget", status_code=404)
    return _widget_response(request, session, *result)


def _widget_response(
    request: Request, session: WebSession, body: str, path: str | None
) -> Response:
    """Answer a widget request with the fragments it changed, `body`, and its page."""
    if session.closed:
        # e.g. Exit: end the session; the page it lands on starts a fresh one
        _store(request).drop(request.session.get(SESSION_KEY))
        return Response(headers={**_NO_STORE, "HX-Redirect": "/"})
    # a navigation puts the new page's address in the browser's history
    headers = _NO_STORE if path is None else {**_NO_STORE, "HX-Push-Url": path}
    return HTMLResponse(body, headers=headers)


async def widget_file(request: Request) -> Response:
    """Hand an uploaded file to a `PickFileAction`; respond as `widget_event` does."""
    session = _session(request)
    if session is None:
        return Response(headers=_RELOAD)
    form = await request.form(max_files=1)
    upload = form.get("file")
    if not isinstance(upload, UploadFile):
        return PlainTextResponse("No file uploaded", status_code=400)
    # one byte over the limit is enough to know the file is too large
    content = await upload.read(MAX_FILE_SIZE + 1)
    widget_id = request.path_params["widget_id"]
    try:
        result = await run_in_threadpool(
            session.pick_file, widget_id, upload.filename or "", content
        )
    except UnsupportedEventError as e:
        return PlainTextResponse(str(e), status_code=400)
    if result is None:
        return PlainTextResponse("Unknown widget", status_code=404)
    return _widget_response(request, session, *result)


def widget_fragment(request: Request) -> Response:
    """Return a widget's current fragment (e.g. a status bar whose message timed out)."""
    session = _session(request)
    if session is None:
        return Response(headers=_RELOAD)
    body = session.fragment(request.path_params["widget_id"])
    if body is None:
        return PlainTextResponse("Unknown widget", status_code=404)
    return HTMLResponse(body, headers=_NO_STORE)


async def chart_image(request: Request) -> Response:
    """Download a chart's image as a report's figure, drawn by matplotlib at its zoom.

    A plain link, like the state's download. Without matplotlib (the `report` extra), not
    found: the page draws its PNG itself.
    """
    session = _session(request)
    if session is None:
        return RedirectResponse("/", status_code=303)
    if not chartimage.is_available():
        return PlainTextResponse("Not Found", status_code=404)
    query = dict(request.query_params)
    image_format = query.pop("format", "pdf").lower()
    widget_id = request.path_params["widget_id"]
    try:
        # matplotlib takes a while: off the event loop
        result = await run_in_threadpool(session.chart_image, widget_id, image_format, query)
    except ValueError as error:
        return PlainTextResponse(str(error), status_code=400)
    if result is None:
        return PlainTextResponse("Unknown widget", status_code=404)
    filename, body = result
    headers = {**_NO_STORE, "Content-Disposition": _attachment(filename)}
    return Response(body, media_type=chartimage.MEDIA_TYPES[image_format], headers=headers)


def _attachment(filename: str) -> str:
    """Get the `Content-Disposition` of a download named `filename`."""
    # the name's own letters, which a header's latin-1 may not have, and a fallback
    ascii_name = filename.encode("ascii", "replace").decode().replace("?", "_")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


def table_csv(request: Request) -> Response:
    """Download a large table's rows shown as CSV, streamed a window of rows at a time.

    A plain link, like a chart's image: it only reads.
    """
    session = _session(request)
    if session is None:
        return RedirectResponse("/", status_code=303)
    result = session.table_csv(request.path_params["widget_id"])
    if result is None:
        return PlainTextResponse("Unknown widget", status_code=404)
    filename, chunks = result
    headers = {**_NO_STORE, "Content-Disposition": _attachment(filename)}
    return StreamingResponse(chunks, media_type="text/csv; charset=utf-8", headers=headers)


def jobs_poll(request: Request) -> Response:
    """Return the jobs' poller and what they changed, which it fetches while they run."""
    session = _session(request)
    if session is None:
        return Response(headers=_RELOAD)
    return HTMLResponse(session.poll_jobs(), headers=_NO_STORE)


def state_download(request: Request) -> Response:
    """Download the session's state as a file, the web side of `MainView.save_state`.

    A plain link, not htmx (htmx can't start downloads); without a session, the
    browser is sent to the page, which starts one.
    """
    session = _session(request)
    if session is None:
        return RedirectResponse("/", status_code=303)
    return _state_file(session)


async def state_save(request: Request) -> Response:
    """Fire Save's own `triggered`, then download the state as `state_download` does.

    A form's post rather than a link: the action changes the session, which a GET must
    not (a link from another site would fire it).
    """
    session = _session(request)
    if session is None:
        return RedirectResponse("/", status_code=303)
    trigger = (await request.form()).get("trigger")
    if isinstance(trigger, str):
        await run_in_threadpool(session.trigger_action, trigger)
    return _state_file(session)


def _state_file(session: WebSession) -> Response:
    filename, body, media_type = session.save_state()
    headers = {**_NO_STORE, "Content-Disposition": f'attachment; filename="{filename}"'}
    return Response(body, media_type=media_type, headers=headers)


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


def icon(request: Request) -> Response:
    """Serve an icon file a view named; any other name is not found."""
    path = icon_path(request.path_params["name"])
    if path is None or not path.is_file():
        return PlainTextResponse("Not Found", status_code=404)
    return FileResponse(path, headers=_ICON_HEADERS)

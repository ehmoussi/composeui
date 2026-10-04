from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.concurrency import run_in_threadpool
from starlette.responses import HTMLResponse, PlainTextResponse, Response

from composeui.webcore.webrenderer import (
    UnsupportedEventError,
    get_renderer,
    handle_event,
    render_fragment,
    render_page,
)

if TYPE_CHECKING:
    from starlette.requests import Request


def homepage(request: Request) -> HTMLResponse:
    return HTMLResponse(render_page(request.app.state.main_view))


async def widget_event(request: Request) -> Response:
    """Dispatch a browser event to a widget; respond with every fragment it changed."""
    renderer = get_renderer(request.path_params["widget_id"])
    if renderer is None:
        return PlainTextResponse("Unknown widget", status_code=404)
    form = await request.form()
    fields = {name: value for name, value in form.items() if isinstance(value, str)}
    event = fields.pop("event", "")
    try:
        # view callbacks are plain sync code: keep them off the event loop
        body = await run_in_threadpool(handle_event, renderer, event, fields)
    except UnsupportedEventError as e:
        return PlainTextResponse(str(e), status_code=400)
    return HTMLResponse(body)


def widget_fragment(request: Request) -> Response:
    """Return a widget's current fragment (e.g. a status bar whose message timed out)."""
    renderer = get_renderer(request.path_params["widget_id"])
    if renderer is None:
        return PlainTextResponse("Unknown widget", status_code=404)
    return HTMLResponse(render_fragment(renderer))

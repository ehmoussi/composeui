from starlette.requests import Request
from starlette.responses import HTMLResponse


def homepage(request: Request) -> HTMLResponse:
    return HTMLResponse(request.app.state.main_view.renderer.to_html())

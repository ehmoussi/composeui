from __future__ import annotations

import secrets
from pathlib import Path
from typing import TYPE_CHECKING, Callable, ClassVar, TypeVar

import uvicorn
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from composeui.core.application import Application, _add_reference_to_signals
from composeui.webcore.routes import (
    homepage,
    state_download,
    state_upload,
    widget_event,
    widget_fragment,
)
from composeui.webcore.session import SessionStore

if TYPE_CHECKING:
    from composeui.core.view import MainView


MainViewT = TypeVar("MainViewT", bound="MainView")


def create_starlette_app(sessions: SessionStore) -> Starlette:
    """Create the Starlette app serving one main view per browser session."""
    app = Starlette(
        routes=[
            Route("/", homepage),
            Route("/widget/{widget_id}", widget_event, methods=["POST"]),
            Route("/widget/{widget_id}", widget_fragment, methods=["GET"]),
            Route("/state", state_download, methods=["GET"]),
            Route("/state", state_upload, methods=["POST"]),
            Mount(
                "/static",
                app=StaticFiles(directory=Path(__file__).parent / "static"),
                name="static",
            ),
        ],
        middleware=[
            # A per-process signing key is enough: sessions live in this process only,
            # so a cookie from before a restart has no session left to point at anyway.
            # `same_site="lax"`: cross-site POSTs carry no session cookie, so another
            # site can't drive a user's session (the CSRF story for now).
            Middleware(SessionMiddleware, secret_key=secrets.token_urlsafe(32), same_site="lax"),
        ],
    )
    app.state.sessions = sessions
    return app


class WebApplication(Application[MainViewT]):
    """Serve the app over HTTP, building one `MainView` per browser session.

    `main_view` is only a template (for the command line, e.g. `-f`'s extension
    check): every session gets its own instance from `build_main_view`. So
    `connect(view=app.main_view..., ...)` would only reach the template; wire behavior
    inside the views, as `examples/pipeform.py` does, or in `setup_session`.
    """

    #: seconds a session may stay idle before it is dropped
    session_ttl: ClassVar[float] = 3600.0

    def __init__(self, *, build_main_view: Callable[[], MainViewT]) -> None:
        self._build_main_view = build_main_view
        super().__init__(main_view=build_main_view())
        self._parser.add_argument(
            "--host", metavar="HOST", help="Host to serve on.", default="127.0.0.1"
        )
        self._parser.add_argument(
            "--port", metavar="PORT", help="Port to serve on.", type=int, default=8000
        )

    def setup_session(self, main_view: MainViewT) -> None:
        """Wire a new session's main view; override to connect app-level behavior."""

    def create_starlette_app(self) -> Starlette:
        """Create the Starlette app, building a fresh main view for each new session."""
        return create_starlette_app(SessionStore(self._new_session_view, ttl=self.session_ttl))

    def run(self) -> None:
        """Build and serve the app."""
        super().run()
        assert self._args is not None
        uvicorn.run(self.create_starlette_app(), host=self._args.host, port=self._args.port)

    def _new_session_view(self) -> MainViewT:
        main_view = self._build_main_view()
        _add_reference_to_signals(main_view, None)
        main_view.is_visible = True
        self.setup_session(main_view)
        # after the wiring, like Qt/Textual apps loading `-f` once everything is connected
        if self._args is not None and self._args.f is not None:
            main_view.load_state(self._args.f)
        return main_view

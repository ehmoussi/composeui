from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Callable, TypeVar

import uvicorn
from starlette.applications import Starlette
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from composeui.core.application import Application
from composeui.core.registry import RendererType
from composeui.webcore.routes import homepage, widget_event

if TYPE_CHECKING:
    from composeui.core.view import MainView


MainViewT = TypeVar("MainViewT", bound="MainView")


def create_starlette_app(main_view: MainView) -> Starlette:
    """Create the Starlette app serving an already rendered `main_view`."""
    app = Starlette(
        routes=[
            Route("/", homepage),
            Route("/widget/{widget_id}", widget_event, methods=["POST"]),
            Mount(
                "/static",
                app=StaticFiles(directory=Path(__file__).parent / "static"),
                name="static",
            ),
        ],
    )
    app.state.main_view = main_view
    return app


class WebApplication(Application[MainViewT]):
    def __init__(self, *, build_main_view: Callable[[], MainViewT]) -> None:
        # kept to build one main view per session (M6); a single one is served for now
        self._build_main_view = build_main_view
        super().__init__(main_view=build_main_view())
        self._parser.add_argument(
            "--host", metavar="HOST", help="Host to serve on.", default="127.0.0.1"
        )
        self._parser.add_argument(
            "--port", metavar="PORT", help="Port to serve on.", type=int, default=8000
        )

    def create_starlette_app(self) -> Starlette:
        """Render the main view and create the Starlette app serving it."""
        self.render(RendererType.WEB)
        return create_starlette_app(self._main_view)

    def run(self) -> None:
        """Build and serve the app."""
        super().run()
        assert self._args is not None
        uvicorn.run(self.create_starlette_app(), host=self._args.host, port=self._args.port)

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Callable, TypeVar

import uvicorn
from starlette.applications import Starlette
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from composeui.core.application import LOGGER, Application
from composeui.core.registry import RendererType
from composeui.webcore.routes import homepage

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from composeui.core.view import MainView


MainViewT = TypeVar("MainViewT", bound="MainView")


_build_main_view: Callable[[], MainView] | None = None


def configure(build_main_view: Callable[[], MainView]) -> None:
    global _build_main_view  # noqa: PLW0603
    _build_main_view = build_main_view


def create_starlette_app(build_main_view: Callable[[], MainView]) -> Starlette:
    """Create the starlette app."""

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        main_view = build_main_view()
        main_view.render(RendererType.WEB)
        app.state.main_view = main_view
        yield

    return Starlette(
        lifespan=lifespan,
        routes=[
            Route("/", homepage),
            Mount(
                "/static",
                app=StaticFiles(directory=Path(__file__).parent / "static"),
                name="static",
            ),
        ],
    )


class WebApplication(Application[MainViewT]):
    def __init__(self, *, build_main_view: Callable[[], MainViewT]) -> None:
        self._build_main_view = build_main_view
        super().__init__(main_view=build_main_view())
        self._parser.add_argument("--reload", help="Enable auto-reload", action="store_true")
        self._parser.add_argument(
            "--port", metavar="PORT", help="Port to serve on.", type=int, default=8000
        )
        # self._config = uvicorn.Config(
        #     "composeui.webcore.webapplication:get_starlette_app",
        #     factory=True,
        # )
        # self._config.load()
        # self._server: uvicorn.Server | None = None
        # self._app: Starlette = self._config.loaded_app.app

    @asynccontextmanager
    async def lifespan(self, app: Starlette) -> AsyncIterator[None]:
        self._main_view.is_visible = True
        self._main_view.render(RendererType.WEB)
        app.state.main_view = self._main_view
        yield

    def run(self) -> None:
        """Build and serve the app."""
        super().run()
        assert self._args is not None
        configure(self._build_main_view)
        uvicorn.run(
            lambda: create_starlette_app(
                self._build_main_view
            ),  # "composeui.webcore.webapplication:create_starlette_app",
            factory=True,
            reload=self._args.reload,
            port=self._args.port,
        )
        # self._config.reload = self._args.reload
        # self._config.port = self._args.port
        # self._app.debug = self._args.reload
        # self._main_view.is_visible = True
        # self._main_view.render(RendererType.WEB)
        # self._app.state.main_view = self._main_view
        # self._server = uvicorn.Server(self._config)
        # self._server.run()

"""Fixtures shared by the web tests."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest
from typing_extensions import override

pytest.importorskip("starlette")
# Starlette's test client: httpx2, which needs Python 3.11, or httpx before it
pytest.importorskip("httpx2" if sys.version_info >= (3, 11) else "httpx")

from composeui.core.registry import RendererType
from composeui.webcore.webapplication import WebApplication
from examples.pipeform import PipeMainView
from tests.folderform import StudyMainView
from tests.horizontal import HorizontalMainView
from tests.markdown import HelpMainView
from tests.metrics import JobsMainView
from tests.pages import PagesMainView
from tests.toolbar import ToolBarMainView

if TYPE_CHECKING:
    from collections.abc import Iterator

    from starlette.applications import Starlette
    from starlette.testclient import TestClient

    from examples.webhello import HelloMainView


from tests.webcore.support import _Browser, _HelloApp, _NoteMainView, _RowsMainView


@pytest.fixture
def app() -> _HelloApp:
    return _HelloApp()


@pytest.fixture
def client(app: _HelloApp) -> Iterator[TestClient]:
    with _Browser(app.create_starlette_app()) as client:
        client.get("/")  # starts the session
        yield client


@pytest.fixture
def main_view(app: _HelloApp, client: TestClient) -> HelloMainView:
    client.get("/")  # the client's own session: still the one view built so far
    (main_view,) = app.session_views
    return main_view


@pytest.fixture
def help_views() -> list[HelpMainView]:
    """Each session's main view, kept by `help_client`'s app."""
    return []


@pytest.fixture
def help_client(help_views: list[HelpMainView]) -> Iterator[TestClient]:
    class HelpApp(WebApplication[HelpMainView]):
        def __init__(self) -> None:
            super().__init__(build_main_view=HelpMainView)

        @override
        def setup_session(self, main_view: HelpMainView) -> None:
            main_view.status_bar.timeout = 0
            help_views.append(main_view)

    with _Browser(HelpApp().create_starlette_app()) as client:
        yield client


@pytest.fixture
def rows() -> _RowsMainView:
    main_view = _RowsMainView()
    main_view.render(RendererType.WEB)
    return main_view


@pytest.fixture
def pipe_views() -> list[PipeMainView]:
    """Each pipeform session's main view, kept by `pipe_client`'s app."""
    return []


@pytest.fixture
def pipe_web(pipe_views: list[PipeMainView]) -> Starlette:
    """Build the pipeform web app, keeping each session's main view in `pipe_views`."""

    class PipeApp(WebApplication[PipeMainView]):
        def __init__(self) -> None:
            super().__init__(build_main_view=PipeMainView)

        @override
        def setup_session(self, main_view: PipeMainView) -> None:
            main_view.status_bar.timeout = 0
            pipe_views.append(main_view)

    web: Starlette = PipeApp().create_starlette_app()
    return web


@pytest.fixture
def pipe_client(pipe_web: Starlette) -> Iterator[TestClient]:
    with _Browser(pipe_web) as client:
        client.get("/")  # starts the session
        yield client


@pytest.fixture
def pipe_main_view(pipe_views: list[PipeMainView], pipe_client: TestClient) -> PipeMainView:
    pipe_client.get("/")  # the client's own session: still the one view built so far
    (main_view,) = pipe_views
    return main_view


@pytest.fixture
def pages_views() -> list[PagesMainView]:
    """Each session's main view, kept by `pages_client`'s app."""
    return []


@pytest.fixture
def pages_client(pages_views: list[PagesMainView]) -> Iterator[TestClient]:
    class PagesApp(WebApplication[PagesMainView]):
        def __init__(self) -> None:
            super().__init__(build_main_view=PagesMainView)

        @override
        def setup_session(self, main_view: PagesMainView) -> None:
            pages_views.append(main_view)

    with _Browser(PagesApp().create_starlette_app()) as client:
        yield client


@pytest.fixture
def toolbar_views() -> list[ToolBarMainView]:
    """Each session's main view, kept by `toolbar_client`'s app."""
    return []


@pytest.fixture
def toolbar_client(toolbar_views: list[ToolBarMainView]) -> Iterator[TestClient]:
    class ToolBarApp(WebApplication[ToolBarMainView]):
        def __init__(self) -> None:
            super().__init__(build_main_view=ToolBarMainView)

        @override
        def setup_session(self, main_view: ToolBarMainView) -> None:
            toolbar_views.append(main_view)

    with _Browser(ToolBarApp().create_starlette_app()) as client:
        yield client


@pytest.fixture
def study() -> Iterator[tuple[TestClient, StudyMainView]]:
    """Serve an app opening a study from a form dialog; yield a client and its main view."""
    views: list[StudyMainView] = []

    class StudyApp(WebApplication[StudyMainView]):
        @override
        def setup_session(self, main_view: StudyMainView) -> None:
            views.append(main_view)

    app = StudyApp(build_main_view=StudyMainView)
    with _Browser(app.create_starlette_app()) as client:
        client.get("/")
        (view,) = views
        yield client, view


@pytest.fixture
def jobs() -> Iterator[tuple[TestClient, JobsMainView]]:
    """Serve an app with a row of metrics; yield a client and its main view."""
    views: list[JobsMainView] = []

    class JobsApp(WebApplication[JobsMainView]):
        @override
        def setup_session(self, main_view: JobsMainView) -> None:
            views.append(main_view)

    app = JobsApp(build_main_view=JobsMainView)
    with _Browser(app.create_starlette_app()) as client:
        client.get("/")
        (view,) = views
        yield client, view


@pytest.fixture
def notes() -> Iterator[tuple[TestClient, _NoteMainView]]:
    """Serve an app with a dialog on its second page; yield a client and its main view."""
    views: list[_NoteMainView] = []

    class NotesApp(WebApplication[_NoteMainView]):
        def __init__(self) -> None:
            super().__init__(build_main_view=_NoteMainView)

        @override
        def setup_session(self, main_view: _NoteMainView) -> None:
            views.append(main_view)

    with _Browser(NotesApp().create_starlette_app()) as client:
        client.get("/")
        (main_view,) = views
        yield client, main_view


@pytest.fixture
def tables() -> Iterator[tuple[TestClient, HorizontalMainView]]:
    """Serve an app with tables side by side; yield a client and its main view."""
    views: list[HorizontalMainView] = []

    class TablesApp(WebApplication[HorizontalMainView]):
        @override
        def setup_session(self, main_view: HorizontalMainView) -> None:
            views.append(main_view)

    app = TablesApp(build_main_view=HorizontalMainView)
    with _Browser(app.create_starlette_app()) as client:
        client.get("/")
        (view,) = views
        yield client, view

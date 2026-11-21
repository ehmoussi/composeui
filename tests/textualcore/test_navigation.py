"""Tests of the Textual main view, router and sidebar."""

from __future__ import annotations

import pytest

pytest.importorskip("textual")
pytest.importorskip("textual_fspicker")

from typing import TYPE_CHECKING

from textual.widgets import (
    Button,
    Input,
    ProgressBar,
)

from composeui.core.application import _add_reference_to_signals
from composeui.core.registry import RendererType
from composeui.core.view import (
    StreamContent,
)
from composeui.textualcore._renderers.navigation import TextualMainRenderer
from composeui.textualcore.textualrenderer import TextualWidgetRenderer
from composeui.textualcore.widgets.composesidebar import ComposeSidebar
from composeui.textualcore.widgets.composetoolbar import ComposeToolbarButton
from tests.downloading import ReportMainView
from tests.pages import PagesMainView
from tests.sidebar import SidebarMainView
from tests.textualcore.support import _names, _widget

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.asyncio
async def test_the_toolbar_shows_one_page_at_a_time() -> None:
    view = PagesMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    name = view.router.inputs.name.renderer
    total = view.router.results.total.renderer
    assert isinstance(name, TextualWidgetRenderer)
    assert isinstance(total, TextualWidgetRenderer)
    assert name.widget is not None
    assert total.widget is not None

    async with app.run_test() as pilot:
        await pilot.pause()
        buttons = {str(button.label): button for button in app.query(ComposeToolbarButton)}
        assert list(buttons) == ["Inputs", "Results"]
        assert buttons["Inputs"].variant == "primary"
        assert name.widget.region.height > 0
        assert total.widget.region.height == 0

        await pilot.click(buttons["Results"])
        await pilot.pause()
        assert view.router.current_route == "results"
        assert total.widget.region.height > 0
        assert name.widget.region.height == 0
        assert buttons["Results"].variant == "primary"
        assert buttons["Inputs"].variant == "default"

        view.router.navigate("inputs")  # from app code
        await pilot.pause()
        assert name.widget.region.height > 0
        assert buttons["Inputs"].variant == "primary"


@pytest.mark.asyncio
async def test_a_sidebar_is_a_column_left_of_the_pages_whatever_the_page() -> None:
    view = SidebarMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    widgets = [
        renderer.widget
        for renderer in (
            view.sidebar.renderer,
            view.sidebar.create.renderer,
            view.router.inputs.submit.renderer,
            view.router.results.progress.renderer,
        )
        if isinstance(renderer, TextualWidgetRenderer)
    ]
    sidebar, create, submit, progress = widgets
    assert isinstance(sidebar, ComposeSidebar)
    assert isinstance(create, Button)
    assert isinstance(submit, Button)
    assert isinstance(progress, ProgressBar)

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        assert str(sidebar.title.render()) == "New record"
        assert create in sidebar.walk_children()
        assert sidebar.region.right <= submit.region.x  # on the pages' left

        view.router.navigate("results")
        await pilot.pause()
        assert create.region.area > 0  # still shown, beside the other page
        assert sidebar.region.right <= progress.region.x
        view.sidebar.title = ""
        await pilot.pause()
        assert not sidebar.title.display  # no empty heading


@pytest.mark.asyncio
async def test_a_sidebar_retracts_to_a_strip_by_its_arrow_and_back() -> None:
    view = SidebarMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    widgets = [
        renderer.widget
        for renderer in (view.sidebar.renderer, view.sidebar.create.renderer)
        if isinstance(renderer, TextualWidgetRenderer)
    ]
    sidebar, create = widgets
    assert isinstance(sidebar, ComposeSidebar)
    assert isinstance(create, Button)
    toggles: list[bool] = []
    view.sidebar.toggled.connect(toggles.append)

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        width = sidebar.region.width
        await pilot.click(sidebar.toggle)
        await pilot.pause()
        assert (view.sidebar.is_expanded, toggles) == (False, [False])
        assert create.region.area == 0
        assert sidebar.region.width < width / 4  # a strip: the pages take the room
        assert sidebar.toggle.region.area > 0  # its arrow brings it back
        assert not sidebar.title.display

        sidebar.toggle.focus()
        await pilot.press("enter")
        await pilot.pause()
        assert (view.sidebar.is_expanded, toggles) == (True, [False, True])
        assert create.region.area > 0
        view.sidebar.is_expanded = False  # set in code: retracted, and not reported
        await pilot.pause()
        assert create.region.area == 0
        assert toggles == [False, True]


@pytest.mark.asyncio
async def test_an_app_s_files_are_saved_where_the_user_picks_one_dialog_at_a_time(
    tmp_path: Path,
) -> None:
    view = ReportMainView()
    view.status_bar.timeout = 0  # no timer clearing the message after the test
    _add_reference_to_signals(view, None)  # as the app does
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None

    def asked() -> list[str]:
        """Get the name that each save dialog open offers."""
        assert app is not None
        return [screen.query_one(Input).value for screen in app.screen_stack[1:]]

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.click(_widget(view.export))
        view.download("second.txt", b"second")  # while the first dialog is open
        await pilot.pause()
        assert asked() == ["report é.csv"]
        app.screen.dismiss(tmp_path / "a.csv")  # as the dialog's Save button does
        await pilot.pause()
        assert asked() == ["second.txt"]
        app.screen.dismiss(None)  # Cancel
        await pilot.pause()
        assert asked() == []
        saved = view.status_bar.message
        files = _names(tmp_path)  # the second cancelled

        view.report = StreamContent(lambda sink: sink.write(b"streamed"))  # written in a job
        await pilot.click(_widget(view.export))
        await pilot.pause()
        app.screen.dismiss(tmp_path / "b.csv")
        for _ in range(100):  # until the job's outcome reaches the status bar
            if view.status_bar.message == "Saved b.csv.":
                break
            await pilot.pause(0.05)

    assert files == ["a.csv"]
    assert saved == "Saved a.csv."
    assert view.status_bar.message == "Saved b.csv."
    assert (tmp_path / "b.csv").read_bytes() == b"streamed"

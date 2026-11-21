"""Helpers shared by the Textual tests."""

from __future__ import annotations

import pytest

pytest.importorskip("textual")
pytest.importorskip("textual_fspicker")

from typing import TYPE_CHECKING, Any, Optional, Union

from textual.widget import Widget

from composeui.core.registry import RendererType
from composeui.core.renderer import Renderer, RendererContainer
from composeui.core.view import (
    View,
)
from composeui.textualcore._renderers.navigation import TextualMainRenderer
from composeui.textualcore.textualrenderer import TextualWidgetRenderer

if TYPE_CHECKING:
    from pathlib import Path

    from textual.app import App
    from textual.pilot import Pilot

    from composeui.core.view import (
        MainView,
        View,
    )


def _field_widget(
    field_row_renderer: Optional[Union[Renderer[Any, Any], RendererContainer[Any]]],
) -> Widget:
    assert isinstance(field_row_renderer, RendererContainer)
    field_renderer = field_row_renderer.get_renderer("field")
    assert isinstance(field_renderer, TextualWidgetRenderer)
    assert isinstance(field_renderer.widget, Widget)
    return field_renderer.widget


def _names(directory: Path) -> list[str]:
    """Get the names of the files in `directory`: an async test can't list it itself."""
    return sorted(path.name for path in directory.iterdir())


def _widget(view: View) -> Widget:
    assert isinstance(view.renderer, TextualWidgetRenderer)
    assert isinstance(view.renderer.widget, Widget)
    return view.renderer.widget


async def _click_laid_out(pilot: Pilot[Any], widget: Widget) -> None:
    """Click `widget` once its screen has laid it out, e.g. on a screen just pushed.

    The pilot aims at the widget's region, empty until then: the click would land on the
    screen's corner instead, on a slow machine.
    """
    for _ in range(100):
        if widget.region.area > 0:
            break
        await pilot.pause()
    assert await pilot.click(widget)


def _app_of(view: MainView) -> App[Any]:
    """Render `view` on Textual, and get the app that shows it, not running yet."""
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    return app

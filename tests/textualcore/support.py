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
    from collections.abc import Callable
    from pathlib import Path

    from textual.app import App
    from textual.pilot import Pilot
    from textual.screen import Screen

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
    screen's corner instead, on a slow machine. A button pressed less than 0.2 s ago keeps
    its `-active` class and ignores the click: a timer removes it, late on a slow machine.
    """
    for _ in range(100):
        if widget.region.area > 0:
            break
        await pilot.pause()
    for _ in range(200):
        if not widget.has_class("-active"):
            break
        await pilot.pause(0.05)
    assert not widget.has_class("-active")
    assert await pilot.click(widget)


async def _wait_until(pilot: Pilot[Any], condition: Callable[[], bool]) -> None:
    """Pause until `condition` holds, 10 s at most, then assert it.

    For what a worker thread or a timer of the app makes, which a slow machine makes late: a
    fixed count of pauses is enough only on a fast one.
    """
    for _ in range(200):
        if condition():
            return
        await pilot.pause(0.05)
    assert condition()


async def _wait_for_screen(
    pilot: Pilot[Any], screen: type[Screen[Any]], part: type[Widget]
) -> None:
    """Wait until the app shows a `screen`, mounted and laid out: until its `part` takes room.

    A screen pushed is on the stack before it is mounted: a key, a click or the app's end that
    comes then is too soon, on a slow machine.
    """

    def is_shown() -> bool:
        shown = pilot.app.screen
        return isinstance(shown, screen) and any(
            widget.region.area > 0 for widget in shown.query(part)
        )

    await _wait_until(pilot, is_shown)


def _app_of(view: MainView) -> App[Any]:
    """Render `view` on Textual, and get the app that shows it, not running yet."""
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    return app

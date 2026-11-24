"""The Textual driver: keys pressed through the headless pilot."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, Literal, Optional

from textual.widgets import Checkbox

from composeui.core.registry import RendererType
from composeui.textualcore._renderers.navigation import TextualMainRenderer
from composeui.textualcore.widgets.composeinput import ComposeInput
from composeui.textualcore.widgets.composerange import ComposeRangeSlider
from composeui.textualcore.widgets.composeslider import ComposeSlider
from tests.textualcore.support import _widget

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from textual.pilot import Pilot

    from composeui.core.view import MainView, View


class TextualDriver:
    def __init__(self) -> None:
        self._pilot: Optional[Pilot[Any]] = None

    @asynccontextmanager
    async def open(self, main_view: MainView) -> AsyncGenerator[None, None]:
        main_view.render(RendererType.TEXTUAL)
        assert isinstance(main_view.renderer, TextualMainRenderer)
        app = main_view.renderer.app
        assert app is not None
        async with app.run_test() as pilot:
            await pilot.pause()
            self._pilot = pilot
            yield

    async def type(self, view: View, text: str) -> None:
        text_input = _input(view)
        text_input.focus()
        await self._press("ctrl+shift+a", *text)  # select all, then type over it

    async def leave(self, view: View) -> None:
        await self._press("tab")
        assert not _input(view).has_focus

    def shown_text(self, view: View) -> str:
        return _input(view).value

    async def toggle(self, view: View) -> None:
        _checkbox(view).focus()
        await self._press("space")

    def is_checked(self, view: View) -> bool:
        return _checkbox(view).value

    async def slide(self, view: View, end: Literal["start", "end"]) -> None:
        _slider(view).focus()
        await self._press("home" if end == "start" else "end")

    def slider_text(self, view: View) -> str:
        return _slider(view).shown_text()

    async def _press(self, *keys: str) -> None:
        assert self._pilot is not None
        await self._pilot.press(*keys)
        # a key's `Changed` comes in a message handled after it
        await self._pilot.pause()


def _input(view: View) -> ComposeInput:
    """Find the input that the user types in: the field, or its own (a date's, a file path's)."""
    field = _widget(view)
    return field if isinstance(field, ComposeInput) else field.query_one(ComposeInput)


def _checkbox(view: View) -> Checkbox:
    checkbox = _widget(view)
    assert isinstance(checkbox, Checkbox)
    return checkbox


def _slider(view: View) -> ComposeSlider | ComposeRangeSlider:
    slider = _widget(view)
    assert isinstance(slider, (ComposeSlider, ComposeRangeSlider))
    return slider

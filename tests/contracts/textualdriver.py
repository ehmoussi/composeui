"""The Textual driver: keys pressed through the headless pilot."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, Literal, Optional

from rich.text import Text
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
    from textual.widget import Widget

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

    @asynccontextmanager
    async def by_code(self) -> AsyncGenerator[None, None]:
        assert self._pilot is not None
        yield
        await self._pilot.pause()

    async def type(self, view: View, text: str) -> None:
        await self._focus(_input(view))
        await self._press("ctrl+shift+a", *text)  # select all, then type over it

    async def leave(self, view: View) -> None:
        await self._press("tab")
        assert not _input(view).has_focus

    def shown_text(self, view: View) -> str:
        return _input(view).value

    def edits(self, text: str) -> list[str]:
        return [text[:end] for end in range(1, len(text) + 1)]  # a report per key

    async def toggle(self, view: View) -> None:
        await self._focus(_checkbox(view))
        await self._press("space")

    def is_checked(self, view: View) -> bool:
        return _checkbox(view).value

    async def slide(self, view: View, end: Literal["start", "end"]) -> None:
        await self._focus(_slider(view))
        await self._press("home" if end == "start" else "end")

    def slider_text(self, view: View) -> str:
        # as drawn, not `shown_text()`, which can follow the value while the label stays behind
        drawn = _slider(view).render()
        assert isinstance(drawn, Text)
        return drawn.plain.lstrip("\u2500\u2501\u25cf").strip()  # the track's ─━●, then the value

    async def _focus(self, widget: Widget) -> None:
        assert self._pilot is not None
        # `focus()` only asks the app to focus it later: a key could come first, and an input's
        # `Focus`, which selects all its text, after it. `set_focus` posts `Focus` now, and the
        # pause waits for the messages already posted to each widget.
        self._pilot.app.screen.set_focus(widget)
        await self._pilot.pause()

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

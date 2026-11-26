"""The Textual driver: keys pressed through the headless pilot."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, Literal, Optional

from rich.text import Text
from textual.widgets import Checkbox, Input, TextArea

from composeui.core.registry import RendererType
from composeui.textualcore._renderers.navigation import TextualMainRenderer
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

    async def type(self, view: View, text: str, *, part: int = 0) -> None:
        box = _text_boxes(view)[part]
        await self._focus(box)
        keys = [{"\n": "enter", " ": "space"}.get(key, key) for key in text]
        # select all, then type over it
        await self._press("f7" if isinstance(box, TextArea) else "ctrl+shift+a", *keys)

    async def leave(self, view: View) -> None:
        await self._press("tab")  # a text area's too: it goes to the next field
        assert not any(box.has_focus for box in _text_boxes(view))

    def shown_text(self, view: View, *, part: int = 0) -> str:
        box = _text_boxes(view)[part]
        return box.text if isinstance(box, TextArea) else box.value

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


def _text_boxes(view: View) -> list[Input | TextArea]:
    """Find the boxes that the user types in, in order.

    The field, or its own: a date's, a file path's, a date range's two.
    """
    field = _widget(view)
    if isinstance(field, (Input, TextArea)):
        return [field]
    boxes = [box for box in field.query("Input, TextArea") if isinstance(box, (Input, TextArea))]
    assert boxes
    return boxes


def _checkbox(view: View) -> Checkbox:
    checkbox = _widget(view)
    assert isinstance(checkbox, Checkbox)
    return checkbox


def _slider(view: View) -> ComposeSlider | ComposeRangeSlider:
    slider = _widget(view)
    assert isinstance(slider, (ComposeSlider, ComposeRangeSlider))
    return slider

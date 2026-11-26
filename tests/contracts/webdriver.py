"""The web driver: the posts the page sends, through the Starlette test client.

The page posts a field's text on `input`, debounced, and again on `change`, when the field
loses the focus after a change, with the values of its box (`hx-vals`, a date range's end),
and a text area's line breaks as the form encodes them, CRLF. A check box posts on
`change`, and a slider its value, or a range its two positions, on `input` and `change`.
What the page's scripts do is for `tests/test_browser.py`.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Literal, Optional

from composeui.webcore.webapplication import WebApplication
from tests.webcore.support import _Browser, _element, _widget_id

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Mapping

    from starlette.testclient import TestClient

    from composeui.core.view import MainView, View


class WebDriver:
    def __init__(self) -> None:
        self._client: Optional[TestClient] = None
        self._part = 0  # the text box typed in, which posts `change` once left

    @asynccontextmanager
    async def open(self, main_view: MainView) -> AsyncGenerator[None, None]:
        app = WebApplication(build_main_view=lambda: main_view)
        with _Browser(app.create_starlette_app()) as client:
            client.get("/")  # starts the session, which renders the view
            self._client = client
            yield

    @asynccontextmanager
    async def by_code(self) -> AsyncGenerator[None, None]:
        yield  # a post is handled before its response: nothing waits

    async def type(self, view: View, text: str, *, part: int = 0) -> None:
        self._post(view, part, "input", text)
        self._part = part

    async def leave(self, view: View) -> None:
        self._post(view, self._part, "change", self.shown_text(view, part=self._part))

    def shown_text(self, view: View, *, part: int = 0) -> str:
        return _shown_text(self._text_boxes(view)[part])

    def edits(self, text: str) -> list[str]:
        return [text]  # the page posts the field's text once

    async def toggle(self, view: View) -> None:
        # an unchecked box posts no value
        self._send(
            view,
            {"event": "change"} if self.is_checked(view) else {"event": "change", "checked": "on"},
        )

    def is_checked(self, view: View) -> bool:
        (box,) = self._inputs(view)
        return "checked" in box

    async def slide(self, view: View, end: Literal["start", "end"]) -> None:
        inputs = self._inputs(view)
        # a range's inputs post both positions: the low one moves to the start, the high one
        # to the end
        moved = inputs[0] if end == "start" else inputs[-1]
        form = {str(attributes["name"]): str(attributes["value"]) for attributes in inputs}
        form[str(moved["name"])] = str(moved["min" if end == "start" else "max"])
        for event in ("input", "change"):
            self._send(view, {"event": event, **form})

    def slider_text(self, view: View) -> str:
        assert self._client is not None
        return _element(self._client.get("/").text, _widget_id(view.renderer)).text

    def _inputs(self, view: View) -> list[Mapping[str, Optional[str]]]:
        assert self._client is not None
        field = _element(self._client.get("/").text, _widget_id(view.renderer))
        return [attributes for tag, attributes in field.descendants if tag == "input"]

    def _text_boxes(self, view: View) -> list[tuple[str, dict[str, Optional[str]], str]]:
        """Find the boxes that the user types in, in order: each one's tag, attributes, text.

        The field, or its own: a date's, a file path's, a date range's two.
        """
        assert self._client is not None
        field = _element(self._client.get("/").text, _widget_id(view.renderer))
        if field.tag == "textarea":  # the field itself, its text the area's
            return [(field.tag, field.attributes, field.text)]
        boxes = [
            (tag, attributes, "")
            for tag, attributes in [(field.tag, field.attributes), *field.descendants]
            if tag == "input" and attributes.get("name") == "value"
        ]
        assert boxes
        return boxes

    def _post(self, view: View, part: int, event: str, text: str) -> None:
        _, attributes, _ = self._text_boxes(view)[part]
        box_values: dict[str, str] = json.loads(attributes.get("hx-vals") or "{}")
        value = text.replace("\n", "\r\n")
        self._send(view, {**box_values, "value": value, "event": event})

    def _send(self, view: View, form: Mapping[str, str]) -> None:
        assert self._client is not None
        response = self._client.post(f"/_composeui/widget/{_widget_id(view.renderer)}", data=form)
        assert response.status_code == 200


def _shown_text(box: tuple[str, dict[str, Optional[str]], str]) -> str:
    tag, attributes, text = box
    if tag == "textarea":
        # a browser drops a new line just after `<textarea>`
        return text.removeprefix("\n")
    value = attributes["value"]
    assert value is not None
    return value

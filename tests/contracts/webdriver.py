"""The web driver: the posts the page sends, through the Starlette test client.

The page posts a field's text on `input`, debounced, and again on `change`, when the field
loses the focus after a change. A check box posts on `change`, and a slider its value, or a
range its two positions, on `input` and `change`. What the page's scripts do is for
`tests/test_browser.py`.
"""

from __future__ import annotations

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

    @asynccontextmanager
    async def open(self, main_view: MainView) -> AsyncGenerator[None, None]:
        app = WebApplication(build_main_view=lambda: main_view)
        with _Browser(app.create_starlette_app()) as client:
            client.get("/")  # starts the session, which renders the view
            self._client = client
            yield

    async def type(self, view: View, text: str) -> None:
        self._post(view, "input", text)

    async def leave(self, view: View) -> None:
        self._post(view, "change", self.shown_text(view))

    def shown_text(self, view: View) -> str:
        assert self._client is not None
        return _shown_value(self._client.get("/").text, _widget_id(view.renderer))

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

    def _post(self, view: View, event: str, text: str) -> None:
        self._send(view, {"value": text, "event": event})

    def _send(self, view: View, form: Mapping[str, str]) -> None:
        assert self._client is not None
        response = self._client.post(f"/_composeui/widget/{_widget_id(view.renderer)}", data=form)
        assert response.status_code == 200


def _shown_value(page: str, widget_id: str) -> str:
    """Read the text of the field's input: the field, or its own (a date's, a file path's)."""
    field = _element(page, widget_id)
    inputs = [
        field.attributes,
        *(attributes for tag, attributes in field.descendants if tag == "input"),
    ]
    value = next(attributes["value"] for attributes in inputs if attributes.get("name") == "value")
    assert value is not None
    return value

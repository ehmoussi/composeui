"""The web driver: the posts the page sends, through the Starlette test client.

The page posts a field's text on `input`, debounced, and again on `change`, when the field
loses the focus after a change. What the page's scripts do is for `tests/test_browser.py`.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Optional

from composeui.webcore.webapplication import WebApplication
from tests.webcore.support import _Browser, _element, _widget_id

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

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

    def _post(self, view: View, event: str, text: str) -> None:
        assert self._client is not None
        response = self._client.post(
            f"/_composeui/widget/{_widget_id(view.renderer)}", data={"value": text, "event": event}
        )
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

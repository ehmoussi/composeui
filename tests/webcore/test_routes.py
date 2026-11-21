"""Tests of the web routes: a widget's fragment, its events, and compressed responses."""

from __future__ import annotations

import sys

import pytest

pytest.importorskip("starlette")
# Starlette's test client: httpx2, which needs Python 3.11, or httpx before it
pytest.importorskip("httpx2" if sys.version_info >= (3, 11) else "httpx")

from typing import TYPE_CHECKING

from tests.webcore.support import _element, _field_id, _widget_id

if TYPE_CHECKING:
    from starlette.testclient import TestClient

    from examples.webhello import HelloMainView


def test_unknown_widget_or_event_is_rejected(main_view: HelloMainView, client: TestClient) -> None:
    assert client.post("/widget/cui-0-input", data={"event": "input"}).status_code == 404
    input_id = _field_id(main_view.form.name)
    assert client.post(f"/widget/{input_id}", data={"event": "click"}).status_code == 400


def test_fetching_a_widget_returns_its_current_fragment(
    main_view: HelloMainView, client: TestClient
) -> None:
    status_bar = main_view.status_bar
    status_bar_id = _widget_id(status_bar.renderer)
    status_bar.timeout = 3.0
    status_bar.message = "Hello, Bob!"
    # what `show_message`'s timer does on the server, outside any request
    status_bar.clear_message()

    response = client.get(f"/widget/{status_bar_id}")

    assert response.status_code == 200
    element = _element(response.text, status_bar_id)
    assert element.tag == "footer"
    assert element.text == ""
    assert "hx-get" not in element.attributes  # cleared: nothing left to fetch later
    assert "hx-swap-oob" not in element.attributes  # swapped by its own `outerHTML`
    assert client.get("/widget/cui-0-status_bar").status_code == 404


def test_the_server_compresses_what_it_sends(client: TestClient) -> None:
    response = client.get("/static/app.css", headers={"Accept-Encoding": "gzip"})

    assert response.headers["Content-Encoding"] == "gzip"

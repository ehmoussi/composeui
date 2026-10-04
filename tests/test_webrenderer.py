"""Coverage for the web backend (Starlette + htmx), driven over HTTP.

Editing a field posts the browser event to `/widget/{id}`; the response carries every
fragment the event changed as an htmx out-of-band swap, except the field itself, which
is never swapped back while the user is typing in it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

pytest.importorskip("starlette")
pytest.importorskip("httpx")

from starlette.testclient import TestClient

from composeui.core.registry import RendererType
from composeui.core.renderer import NoRenderedObjectError
from composeui.core.view import StatusBar
from composeui.webcore.webrenderer import (
    WebInputRenderer,
    WebRenderer,
    WebStatusBarRenderer,
    collect_dirty,
    render_dirty,
)
from examples.webhello import HelloApp

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture
def app() -> HelloApp:
    app = HelloApp()
    # no `threading.Timer` clearing the message in the middle of a test
    app.main_view.status_bar.timeout = 0
    return app


@pytest.fixture
def client(app: HelloApp) -> Iterator[TestClient]:
    with TestClient(app.create_starlette_app()) as client:
        yield client


def _widget_id(renderer: Any) -> str:
    assert isinstance(renderer, WebRenderer)
    return renderer.widget_id


def test_page_renders_the_input_and_the_status_bar(app: HelloApp, client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "<title>Hello ComposeUI</title>" in response.text
    assert f'id="{_widget_id(app.main_view.greeting.renderer)}"' in response.text
    assert 'placeholder="Type your name..."' in response.text
    assert f'id="{_widget_id(app.main_view.status_bar.renderer)}"' in response.text


def test_page_shows_the_title_and_docks_an_empty_status_bar(
    app: HelloApp, client: TestClient
) -> None:
    response = client.get("/")

    assert '<h1 class="text-lg font-semibold">Hello ComposeUI</h1>' in response.text
    assert '<meta name="viewport"' in response.text
    status_bar_id = _widget_id(app.main_view.status_bar.renderer)
    status_bar = response.text[response.text.index(f'<footer id="{status_bar_id}"') :]
    status_bar = status_bar[: status_bar.index("</footer>")]
    # a status line, not a coloured callout: an empty message must not show a bar
    assert "alert" not in status_bar
    assert "fixed inset-x-0 bottom-0" in status_bar
    assert status_bar.endswith(">")


def test_typing_updates_the_status_bar_out_of_band(app: HelloApp, client: TestClient) -> None:
    main_view = app.main_view
    input_id = _widget_id(main_view.greeting.renderer)

    response = client.post(f"/widget/{input_id}", data={"value": "Bob", "event": "input"})

    assert response.status_code == 200
    assert main_view.greeting.text == "Bob"
    assert main_view.status_bar.message == "Hello, Bob!"
    status_bar_id = _widget_id(main_view.status_bar.renderer)
    assert f'<footer id="{status_bar_id}" hx-swap-oob="true"' in response.text
    assert "Hello, Bob!" in response.text
    # the field being typed in is never swapped back
    assert input_id not in response.text


def test_change_event_applies_the_text_and_finishes_editing_once(
    app: HelloApp, client: TestClient
) -> None:
    greeting = app.main_view.greeting
    finished: list[None] = []
    edited: list[str] = []
    greeting.editing_finished.connect(lambda: finished.append(None))

    # a def, not `edited.append`: signal logging needs the callback's `__code__`
    def on_edited(text: str) -> None:
        edited.append(text)

    greeting.text_edited.connect(on_edited)
    input_id = _widget_id(greeting.renderer)

    # a `change` can overtake a still-debounced `input` carrying the same value
    client.post(f"/widget/{input_id}", data={"value": "Ann", "event": "change"})
    client.post(f"/widget/{input_id}", data={"value": "Ann", "event": "input"})

    assert greeting.text == "Ann"
    assert edited == ["Ann"]
    assert len(finished) == 1


def test_unknown_widget_or_event_is_rejected(app: HelloApp, client: TestClient) -> None:
    assert client.post("/widget/cui-0-input", data={"event": "input"}).status_code == 404
    input_id = _widget_id(app.main_view.greeting.renderer)
    assert client.post(f"/widget/{input_id}", data={"event": "click"}).status_code == 400


def test_changes_outside_a_request_are_not_collected(app: HelloApp) -> None:
    app.create_starlette_app()
    status_bar = app.main_view.status_bar

    status_bar.message = "from a timer thread"

    assert isinstance(status_bar.renderer, WebStatusBarRenderer)
    assert "from a timer thread" in status_bar.renderer.to_html()


def test_changes_inside_a_request_mark_the_renderer_dirty_once(app: HelloApp) -> None:
    app.create_starlette_app()
    greeting = app.main_view.greeting

    with collect_dirty() as dirty:
        greeting.placeholder = "Name"
        greeting.text = "Zoe"

    assert list(dirty.values()) == [greeting.renderer]


def test_hidden_and_disabled_views_keep_their_id(app: HelloApp) -> None:
    app.create_starlette_app()
    greeting = app.main_view.greeting
    assert isinstance(greeting.renderer, WebInputRenderer)

    greeting.is_visible = False
    greeting.is_enabled = False

    fragment = greeting.renderer.to_html()
    assert f'id="{greeting.renderer.widget_id}" hidden' in fragment
    assert fragment.endswith(" disabled>")


def test_view_text_is_escaped(app: HelloApp) -> None:
    app.create_starlette_app()
    greeting = app.main_view.greeting
    assert isinstance(greeting.renderer, WebInputRenderer)

    greeting.text = '"><script>alert(1)</script>'

    fragment = greeting.renderer.to_html()
    assert "<script>" not in fragment
    assert 'value="&quot;&gt;&lt;script&gt;' in fragment


class _ContainerRenderer(WebRenderer[StatusBar]):
    """A fragment wrapping another one, like a group wrapping its rows."""

    _role = "container"

    def __init__(self, view: StatusBar, child: WebRenderer[Any]) -> None:
        super().__init__(view)
        self._child = child

    def to_html(self, *, oob: bool = False) -> str:
        return f"<div {self._root_attributes(oob=oob)}>{self._child.to_html()}</div>"


def test_render_dirty_drops_fragments_nested_in_another_dirty_fragment() -> None:
    child_view = StatusBar(message="child")
    child_view.render(RendererType.WEB)
    child = child_view.renderer
    assert isinstance(child, WebStatusBarRenderer)
    container = _ContainerRenderer(StatusBar(), child)
    container.render()

    body = render_dirty({child.widget_id: child, container.widget_id: container})

    assert body.count(f'id="{child.widget_id}"') == 1
    assert body.startswith(f'<div id="{container.widget_id}" hx-swap-oob="true">')


def test_widget_id_requires_a_render() -> None:
    renderer = WebStatusBarRenderer(StatusBar())
    with pytest.raises(NoRenderedObjectError):
        _ = renderer.widget_id

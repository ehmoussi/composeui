"""Coverage for the web backend (Starlette + htmx).

Editing a field posts the browser event to `/widget/{id}`; the response carries every
fragment the event changed as an htmx out-of-band swap, except the field itself, which
is never swapped back while the user is typing in it. The hello example is driven over
HTTP; form rows have no place on a page until the form renderer exists (M5), so their
renderers are driven directly through `handle_event`, the function the route calls.
"""

from __future__ import annotations

import enum
import re
from typing import TYPE_CHECKING, Any

import pytest

pytest.importorskip("starlette")
pytest.importorskip("httpx")

from attrs import Factory
from starlette.testclient import TestClient

from composeui.core.registry import RendererType
from composeui.core.renderer import NoRenderedObjectError, RendererContainer
from composeui.core.view import (
    LabelRowFloatInputView,
    LabelRowInputView,
    LabelRowRadioGroupView,
    LabelView,
    LogType,
    LogView,
    MainView,
    StatusBar,
    define_view,
)
from composeui.webcore.webrenderer import (
    WebFloatInputRenderer,
    WebInputRenderer,
    WebLabelRenderer,
    WebLogRenderer,
    WebRadioGroupRenderer,
    WebRenderer,
    WebStatusBarRenderer,
    collect_dirty,
    handle_event,
    render_dirty,
)
from examples.webhello import Colour, GreetingStyle, HelloApp

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


def test_the_browser_never_shows_a_stale_copy_of_the_page(
    app: HelloApp, client: TestClient
) -> None:
    """After a server restart, a reload must show the server's state, not the browser's.

    Without these, Firefox reused the old page (no cache header) or refilled every field
    of the fresh one with what was typed before, next to messages about empty fields.
    """
    page = client.get("/")
    controls = re.findall(r"<(?:input|select)\b[^>]*>", page.text)
    status_bar_id = _widget_id(app.main_view.status_bar.renderer)
    input_id = _widget_id(app.main_view.greeting.renderer)

    assert len(controls) >= 4  # name, age, two radios, colour
    assert all('autocomplete="off"' in control for control in controls)
    assert page.headers["cache-control"] == "no-store"
    event = client.post(f"/widget/{input_id}", data={"value": "Bob", "event": "input"})
    assert event.headers["cache-control"] == "no-store"
    assert client.get(f"/widget/{status_bar_id}").headers["cache-control"] == "no-store"


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


def test_one_keystroke_fans_out_to_the_log_the_summary_and_the_status_bar(
    app: HelloApp, client: TestClient
) -> None:
    main_view = app.main_view
    assert main_view.name_log.log_message == "A name is mandatory"
    input_id = _widget_id(main_view.greeting.renderer)

    body = client.post(f"/widget/{input_id}", data={"value": "Bob", "event": "input"}).text

    swapped = {
        renderer.widget_id
        for renderer in (
            main_view.name_log.renderer,
            main_view.summary.renderer,
            main_view.status_bar.renderer,
        )
        if isinstance(renderer, WebRenderer)
    }
    assert len(swapped) == 3
    for widget_id in swapped:
        assert f'id="{widget_id}" hx-swap-oob="true"' in body
    assert "Bob hasn&#x27;t said how old they are." in body
    assert input_id not in body


def test_age_is_validated_and_summarised(app: HelloApp, client: TestClient) -> None:
    main_view = app.main_view
    age_id = _widget_id(main_view.age.renderer)

    body = client.post(f"/widget/{age_id}", data={"value": "-3", "event": "input"}).text

    assert main_view.age.value == -3.0
    assert "An age can&#x27;t be negative" in body

    client.post(f"/widget/{age_id}", data={"value": "41", "event": "input"})

    assert main_view.age_log.log_message == ""
    assert main_view.summary.text == "Nobody is 41 years old."


def test_leaving_the_age_field_with_unparsable_text_shows_the_age_again(
    app: HelloApp, client: TestClient
) -> None:
    main_view = app.main_view
    age_id = _widget_id(main_view.age.renderer)
    finished: list[None] = []

    def on_finished() -> None:
        finished.append(None)

    main_view.age.editing_finished.connect(on_finished)
    client.post(f"/widget/{age_id}", data={"value": "4", "event": "input"})
    client.post(f"/widget/{age_id}", data={"value": "4a", "event": "input"})

    body = client.post(f"/widget/{age_id}", data={"value": "4a", "event": "change"}).text

    # the field, otherwise never swapped back, now shows the age its messages describe
    assert main_view.age.value == 4.0
    assert f'<input id="{age_id}" hx-swap-oob="true"' in body
    assert 'value="4.0"' in body
    assert finished == []


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


@define_view
class _NameRowView(LabelRowInputView):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.label = "Name <required>"
        self.set_validator(self._check_name, self.text_edited)
        self.run_validator()

    def _check_name(self) -> str | None:
        return "A name is mandatory" if self.text == "" else None


class _Shape(enum.Enum):
    ROUND = "Round"
    SQUARE = "Square"


@define_view
class _ShapeRowView(LabelRowRadioGroupView[_Shape]):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.label = "Shape"
        self.values = {shape.value: shape for shape in _Shape}
        self.value = _Shape.ROUND


@define_view
class _RowsMainView(MainView):
    name: _NameRowView = Factory(_NameRowView)
    length: LabelRowFloatInputView = Factory(LabelRowFloatInputView)
    note: LabelView = Factory(LabelView)
    form_log: LogView = Factory(LogView)
    shape: _ShapeRowView = Factory(_ShapeRowView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self._init_app_info(title="Rows", extension=".rows")
        self.length.label = "Length"
        self.length.value = 20.0


@pytest.fixture
def rows() -> _RowsMainView:
    main_view = _RowsMainView()
    main_view.render(RendererType.WEB)
    return main_view


def _part(row: Any, name: str) -> WebRenderer[Any]:
    """One of a form row's renderers: "label", "field" or "log"."""
    assert isinstance(row.renderer, RendererContainer)
    renderer = row.renderer.get_renderer(name)
    assert isinstance(renderer, WebRenderer)
    return renderer


def test_clearing_a_validated_input_dirties_its_log_but_not_the_input(
    rows: _RowsMainView,
) -> None:
    field, log = _part(rows.name, "field"), _part(rows.name, "log")
    assert rows.name.log_message == "A name is mandatory"

    body = handle_event(field, "input", {"value": "Al"})

    assert rows.name.text == "Al"
    assert rows.name.log_message == ""
    assert f'<p id="{log.widget_id}" hx-swap-oob="true" hidden' in body
    assert field.widget_id not in body

    body = handle_event(field, "input", {"value": ""})

    assert "A name is mandatory" in body
    assert f'id="{log.widget_id}" hx-swap-oob="true" aria-live' in body


def test_float_input_ignores_transient_text(rows: _RowsMainView) -> None:
    field = _part(rows.length, "field")

    handle_event(field, "input", {"value": "-"})
    assert rows.length.value == 20.0

    handle_event(field, "input", {"value": "-5.5"})
    assert rows.length.value == -5.5

    handle_event(field, "input", {"value": ""})
    assert rows.length.value is None


def test_change_after_input_finishes_editing_without_re_emitting(rows: _RowsMainView) -> None:
    field = _part(rows.length, "field")
    edited: list[str] = []
    finished: list[None] = []

    def on_edited(text: str) -> None:
        edited.append(text)

    def on_finished() -> None:
        finished.append(None)

    rows.length.text_edited.connect(on_edited)
    rows.length.editing_finished.connect(on_finished)

    handle_event(field, "input", {"value": "3"})
    handle_event(field, "change", {"value": "3"})

    assert rows.length.value == 3.0
    assert edited == ["3"]
    assert len(finished) == 1


def test_a_server_side_value_wins_over_the_last_typed_text(rows: _RowsMainView) -> None:
    field = _part(rows.length, "field")
    assert isinstance(field, WebFloatInputRenderer)
    edited: list[str] = []

    def on_edited(text: str) -> None:
        edited.append(text)

    rows.length.text_edited.connect(on_edited)
    handle_event(field, "input", {"value": "-"})

    with collect_dirty() as dirty:
        rows.length.value = 7.0

    assert list(dirty) == [field.widget_id]
    assert 'value="7.0"' in field.to_html()
    # "-" again is a new edit against the server's 7.0, not a duplicate post
    handle_event(field, "input", {"value": "-"})
    assert edited == ["-", "-"]


def test_float_input_renders_a_decimal_text_field(rows: _RowsMainView) -> None:
    fragment = _part(rows.length, "field").to_html()

    assert 'type="text"' in fragment
    assert 'inputmode="decimal"' in fragment
    assert 'pattern="' in fragment
    assert 'value="20.0"' in fragment


def test_form_label_points_at_its_field_and_escapes_the_text(rows: _RowsMainView) -> None:
    label, field = _part(rows.name, "label"), _part(rows.name, "field")

    fragment = label.to_html()

    assert f'for="{field.widget_id}"' in fragment
    assert "Name &lt;required&gt;" in fragment

    with collect_dirty() as dirty:
        rows.name.label = "Full name"

    assert list(dirty) == [label.widget_id]


def test_log_is_hidden_when_empty_and_coloured_by_type(rows: _RowsMainView) -> None:
    renderer = rows.form_log.renderer
    assert isinstance(renderer, WebLogRenderer)
    assert " hidden " in renderer.to_html()

    rows.form_log.log_message = "- first\n- second"
    rows.form_log.log_type = LogType.WARNING

    fragment = renderer.to_html()
    assert "hidden" not in fragment
    assert "text-warning" in fragment
    # the hook the page's stylesheet uses to mark the field before an error log
    assert 'data-log="warning"' in fragment
    assert "whitespace-pre-line" in fragment
    assert "- first\n- second" in fragment


def test_label_renders_escaped_text(rows: _RowsMainView) -> None:
    renderer = rows.note.renderer
    assert isinstance(renderer, WebLabelRenderer)

    with collect_dirty() as dirty:
        rows.note.text = "<b>bold</b>"

    assert list(dirty) == [renderer.widget_id]
    assert renderer.to_html() == f'<span id="{renderer.widget_id}">&lt;b&gt;bold&lt;/b&gt;</span>'


def test_page_renders_the_choices(app: HelloApp, client: TestClient) -> None:
    page = client.get("/").text
    style_id = _widget_id(app.main_view.style.renderer)
    colour_id = _widget_id(app.main_view.colour.renderer)

    assert f'<div id="{style_id}" role="radiogroup"' in page
    assert page.count('type="radio" class="radio radio-sm" value="') == 2
    assert f'value="Casual" checked name="{style_id}"' in page
    assert f'value="Formal" name="{style_id}"' in page
    # nothing chosen yet: the combobox starts on its empty choice
    assert f'<select id="{colour_id}"' in page
    assert '<option value="" selected></option><option value="Red">Red</option>' in page


def test_choosing_a_style_regreets_without_swapping_the_radio_group(
    app: HelloApp, client: TestClient
) -> None:
    main_view = app.main_view
    input_id = _widget_id(main_view.greeting.renderer)
    style_id = _widget_id(main_view.style.renderer)
    client.post(f"/widget/{input_id}", data={"value": "Bob", "event": "input"})

    body = client.post(f"/widget/{style_id}", data={style_id: "Formal", "event": "change"}).text

    assert main_view.style.value is GreetingStyle.FORMAL
    assert main_view.status_bar.message == "Good day, Bob."
    assert "Good day, Bob." in body
    assert style_id not in body


def test_choosing_a_colour_updates_the_summary(app: HelloApp, client: TestClient) -> None:
    main_view = app.main_view
    colour_id = _widget_id(main_view.colour.renderer)

    body = client.post(f"/widget/{colour_id}", data={colour_id: "Blue", "event": "change"}).text

    assert main_view.colour.value is Colour.BLUE
    assert "and likes blue." in body
    assert colour_id not in body

    # the empty choice clears the colour again
    client.post(f"/widget/{colour_id}", data={colour_id: "", "event": "change"})

    assert main_view.colour.value is None
    assert main_view.summary.text == "Nobody hasn't said how old they are."


def test_an_unknown_label_clears_the_value_instead_of_failing(
    app: HelloApp, client: TestClient
) -> None:
    main_view = app.main_view
    colour_id = _widget_id(main_view.colour.renderer)
    main_view.colour.value = Colour.RED

    response = client.post(f"/widget/{colour_id}", data={colour_id: "Purple", "event": "change"})

    assert response.status_code == 200
    assert main_view.colour.value is None


def test_choosing_the_current_value_again_does_not_re_emit(
    app: HelloApp, client: TestClient
) -> None:
    style = app.main_view.style
    style_id = _widget_id(style.renderer)
    emitted: list[GreetingStyle | None] = []

    def on_changed(value: GreetingStyle | None) -> None:
        emitted.append(value)

    style.value_changed.connect(on_changed)

    for _ in range(2):
        client.post(f"/widget/{style_id}", data={style_id: "Formal", "event": "change"})

    assert emitted == [GreetingStyle.FORMAL]


def test_replacing_the_values_rerenders_the_options(app: HelloApp) -> None:
    app.create_starlette_app()
    style = app.main_view.style
    renderer = style.renderer
    assert isinstance(renderer, WebRadioGroupRenderer)
    style.value = GreetingStyle.FORMAL

    with collect_dirty() as dirty:
        # drops the current value, which `_reconcile_values` clears
        style.values = {"Casual": GreetingStyle.CASUAL}

    assert list(dirty) == [renderer.widget_id]
    assert style.value is None
    fragment = renderer.to_html()
    assert "Formal" not in fragment
    assert "checked" not in fragment


def test_a_disabled_radio_group_disables_every_radio(app: HelloApp) -> None:
    app.create_starlette_app()
    style = app.main_view.style
    assert isinstance(style.renderer, WebRadioGroupRenderer)

    style.is_enabled = False

    assert style.renderer.to_html().count(" disabled>") == 2


def test_a_radio_row_label_does_not_point_at_the_group(rows: _RowsMainView) -> None:
    label, field = _part(rows.shape, "label"), _part(rows.shape, "field")

    assert "for=" not in label.to_html()
    assert f'name="{field.widget_id}"' in field.to_html()

    handle_event(field, "change", {field.widget_id: "Square"})

    assert rows.shape.value is _Shape.SQUARE


def test_a_timed_message_makes_the_status_bar_fetch_itself_after_the_timeout(
    app: HelloApp,
) -> None:
    app.create_starlette_app()
    status_bar = app.main_view.status_bar
    renderer = status_bar.renderer
    assert isinstance(renderer, WebStatusBarRenderer)
    status_bar.timeout = 3.0

    assert "hx-get" not in renderer.to_html()  # nothing to clear yet

    status_bar.message = "Saved"

    fragment = renderer.to_html()
    assert f'hx-get="/widget/{renderer.widget_id}"' in fragment
    assert 'hx-trigger="load delay:3250ms"' in fragment
    assert 'hx-swap="outerHTML"' in fragment

    status_bar.timeout = 0  # a message that never times out needs no fetch
    assert "hx-get" not in renderer.to_html()


def test_fetching_a_widget_returns_its_current_fragment(app: HelloApp, client: TestClient) -> None:
    status_bar = app.main_view.status_bar
    status_bar_id = _widget_id(status_bar.renderer)
    status_bar.timeout = 3.0
    status_bar.message = "Hello, Bob!"
    # what `show_message`'s timer does on the server, outside any request
    status_bar.clear_message()

    response = client.get(f"/widget/{status_bar_id}")

    assert response.status_code == 200
    assert response.text.startswith(f'<footer id="{status_bar_id}" role="status"')
    assert "Hello, Bob!" not in response.text
    assert "hx-get" not in response.text
    assert client.get("/widget/cui-0-status_bar").status_code == 404

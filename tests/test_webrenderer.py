"""Coverage for the web backend (Starlette + htmx).

Editing a field posts the browser event to `/widget/{id}`; the response carries every
fragment the event changed as an htmx out-of-band swap, except the field itself, which
is never swapped back while the user is typing in it. The hello example and
`examples/pipeform` are driven over HTTP; a few renderer-level cases drive rows
directly through `handle_event`, the function the route calls.
"""

from __future__ import annotations

import enum
import json
import re
import time
from html.parser import HTMLParser
from typing import TYPE_CHECKING, Any, NamedTuple

import pytest

pytest.importorskip("starlette")
pytest.importorskip("httpx")

from attrs import Factory
from starlette.testclient import TestClient
from uvicorn.importer import import_from_string

from composeui.core.model import Model
from composeui.core.registry import RendererType
from composeui.core.renderer import NoRenderedObjectError, RendererContainer
from composeui.core.view import (
    ActionView,
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
from composeui.webcore.webapplication import WebApplication, WebModelApplication
from composeui.webcore.webrenderer import (
    UnsupportedEventError,
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
from examples.pipeform import PipeMainView
from examples.webhello import Colour, GreetingStyle, HelloApp, HelloMainView, NameRowView

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from starlette.applications import Starlette


class _HelloApp(HelloApp):
    """The hello app, keeping each session's main view through the real session hook."""

    def __init__(self) -> None:
        super().__init__()
        self.session_views: list[HelloMainView] = []

    def setup_session(self, main_view: HelloMainView) -> None:
        # no `threading.Timer` clearing the message in the middle of a test
        main_view.status_bar.timeout = 0
        self.session_views.append(main_view)


@pytest.fixture
def app() -> _HelloApp:
    return _HelloApp()


@pytest.fixture
def client(app: _HelloApp) -> Iterator[TestClient]:
    with TestClient(app.create_starlette_app()) as client:
        client.get("/")  # starts the session
        yield client


@pytest.fixture
def main_view(app: _HelloApp, client: TestClient) -> HelloMainView:
    client.get("/")  # the client's own session: still the one view built so far
    (main_view,) = app.session_views
    return main_view


def _widget_id(renderer: Any) -> str:
    assert isinstance(renderer, WebRenderer)
    return renderer.widget_id


def _part(row: Any, name: str) -> WebRenderer[Any]:
    """One of a form row's renderers: "label", "field" or "log"."""
    assert isinstance(row.renderer, RendererContainer)
    renderer = row.renderer.get_renderer(name)
    assert isinstance(renderer, WebRenderer)
    return renderer


def _field_id(row: Any) -> str:
    return _part(row, "field").widget_id


#: elements with no closing tag
_VOID_TAGS = frozenset({"input", "br", "hr", "img", "meta", "link"})


class _Element(NamedTuple):
    """An element found by `_element`: its tag, attributes, text and descendant tags."""

    tag: str
    attributes: dict[str, str | None]
    text: str
    descendants: list[tuple[str, dict[str, str | None]]]


class _ElementFinder(HTMLParser):
    def __init__(self, element_id: str) -> None:
        super().__init__()
        self._id = element_id
        self._depth = 0
        self._text: list[str] = []
        self._descendants: list[tuple[str, dict[str, str | None]]] = []
        self._root: tuple[str, dict[str, str | None]] | None = None
        self.found: _Element | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if self._root is None and attributes.get("id") == self._id:
            self._root = (tag, attributes)
            if tag in _VOID_TAGS:
                self._finish()
            else:
                self._depth = 1
        elif self._depth > 0:
            self._descendants.append((tag, attributes))
            if tag not in _VOID_TAGS:
                self._depth += 1

    def handle_endtag(self, tag: str) -> None:  # well-formed fragments: any end tag closes
        if self._depth > 0:
            self._depth -= 1
            if self._depth == 0:
                self._finish()

    def handle_data(self, data: str) -> None:
        if self._depth > 0:
            self._text.append(data)

    def _finish(self) -> None:
        if self.found is None and self._root is not None:
            tag, attributes = self._root
            self.found = _Element(tag, attributes, "".join(self._text), self._descendants)


def _find(markup: str, element_id: str) -> _Element | None:
    """Parse `markup` and return the element with `element_id` (text unescaped), or None."""
    finder = _ElementFinder(element_id)
    finder.feed(markup)
    finder.close()
    return finder.found


def _element(markup: str, element_id: str) -> _Element:
    element = _find(markup, element_id)
    assert element is not None, f"no element with id {element_id!r}"
    return element


def _swapped(markup: str, element_id: str) -> _Element:
    """Return the element, which must arrive as an htmx out-of-band swap."""
    element = _element(markup, element_id)
    assert element.attributes.get("hx-swap-oob") == "true"
    return element


def _selected(element: _Element) -> list[str | None]:
    """Values of the checked radios / selected options inside `element`."""
    return [
        attributes.get("value")
        for tag, attributes in element.descendants
        if (tag == "input" and "checked" in attributes)
        or (tag == "option" and "selected" in attributes)
    ]


def test_page_shows_the_form_and_docks_an_empty_status_bar(
    main_view: HelloMainView, client: TestClient
) -> None:
    response = client.get("/")

    assert response.status_code == 200
    page = response.text
    assert "<title>Hello ComposeUI</title>" in page
    assert '<meta name="viewport"' in page
    assert '<h1 class="text-lg font-semibold">Hello ComposeUI</h1>' in page
    name = _element(page, _field_id(main_view.form.name))
    assert name.attributes["placeholder"] == "Type your name..."
    status_bar = _element(page, _widget_id(main_view.status_bar.renderer))
    classes = set((status_bar.attributes["class"] or "").split())
    assert status_bar.tag == "footer"
    assert status_bar.text == ""
    assert status_bar.descendants == []
    # a status line docked at the bottom, not a coloured callout showing even when empty
    assert {"fixed", "inset-x-0", "bottom-0"} <= classes
    assert "alert" not in classes


def test_the_browser_never_shows_a_stale_copy_of_the_page(
    main_view: HelloMainView, client: TestClient
) -> None:
    """After a server restart, a reload must show the server's state, not the browser's.

    Without these, Firefox reused the old page (no cache header) or refilled every field
    of the fresh one with what was typed before, next to messages about empty fields.
    """
    page = client.get("/")
    controls = re.findall(r"<(?:input|select)\b[^>]*>", page.text)
    status_bar_id = _widget_id(main_view.status_bar.renderer)
    input_id = _field_id(main_view.form.name)

    assert len(controls) >= 4  # name, age, two radios, colour
    assert all('autocomplete="off"' in control for control in controls)
    assert page.headers["cache-control"] == "no-store"
    event = client.post(f"/widget/{input_id}", data={"value": "Bob", "event": "input"})
    assert event.headers["cache-control"] == "no-store"
    assert client.get(f"/widget/{status_bar_id}").headers["cache-control"] == "no-store"


def test_one_keystroke_fans_out_to_the_log_the_summary_and_the_status_bar(
    main_view: HelloMainView, client: TestClient
) -> None:
    assert main_view.form.name.log_message == "A name is mandatory"
    input_id = _field_id(main_view.form.name)

    body = client.post(f"/widget/{input_id}", data={"value": "Bob", "event": "input"}).text

    assert main_view.form.name.text == "Bob"
    assert "hidden" in _swapped(body, _widget_id(_part(main_view.form.name, "log"))).attributes
    summary = _swapped(body, _widget_id(main_view.summary.renderer))
    assert summary.text == "Bob hasn't said how old they are."
    assert _swapped(body, _widget_id(main_view.status_bar.renderer)).text == "Hello, Bob!"
    assert _find(body, input_id) is None  # the field being typed in is never swapped back


def test_age_is_validated_and_summarised(main_view: HelloMainView, client: TestClient) -> None:
    age_id = _field_id(main_view.form.age)

    body = client.post(f"/widget/{age_id}", data={"value": "-3", "event": "input"}).text

    assert main_view.form.age.value == -3.0
    assert "An age can&#x27;t be negative" in body

    # another error of the same type: only the message changes, and it must still show
    body = client.post(f"/widget/{age_id}", data={"value": "4.5", "event": "input"}).text

    log_id = _widget_id(_part(main_view.form.age, "log"))
    assert _swapped(body, log_id).text == "An age is a whole number of years"

    client.post(f"/widget/{age_id}", data={"value": "41", "event": "input"})

    assert main_view.form.age.log_message == ""
    assert main_view.summary.text == "Nobody is 41 years old."


def test_leaving_the_age_field_with_unparsable_text_shows_the_age_again(
    main_view: HelloMainView, client: TestClient
) -> None:
    age_id = _field_id(main_view.form.age)
    finished = _count(main_view.form.age.editing_finished)
    client.post(f"/widget/{age_id}", data={"value": "4", "event": "input"})
    client.post(f"/widget/{age_id}", data={"value": "4a", "event": "input"})

    body = client.post(f"/widget/{age_id}", data={"value": "4a", "event": "change"}).text

    # the field, otherwise never swapped back, now shows the age its messages describe
    assert main_view.form.age.value == 4.0
    assert _swapped(body, age_id).attributes["value"] == "4.0"
    assert finished == []


def test_change_event_applies_the_text_and_finishes_editing_once(
    main_view: HelloMainView, client: TestClient
) -> None:
    greeting = main_view.form.name
    finished: list[None] = []
    edited: list[str] = []
    greeting.editing_finished.connect(lambda: finished.append(None))

    greeting.text_edited.connect(edited.append)
    input_id = _field_id(greeting)

    # a `change` can overtake a still-debounced `input` carrying the same value
    client.post(f"/widget/{input_id}", data={"value": "Ann", "event": "change"})
    client.post(f"/widget/{input_id}", data={"value": "Ann", "event": "input"})

    assert greeting.text == "Ann"
    assert edited == ["Ann"]
    assert len(finished) == 1


def test_unknown_widget_or_event_is_rejected(main_view: HelloMainView, client: TestClient) -> None:
    assert client.post("/widget/cui-0-input", data={"event": "input"}).status_code == 404
    input_id = _field_id(main_view.form.name)
    assert client.post(f"/widget/{input_id}", data={"event": "click"}).status_code == 400


def test_hidden_and_disabled_views_keep_their_id(main_view: HelloMainView) -> None:
    name = main_view.form.name
    field = _part(name, "field")
    assert isinstance(field, WebInputRenderer)

    name.is_visible = False
    name.is_enabled = False

    element = _element(field.to_html(), field.widget_id)
    assert "hidden" in element.attributes
    assert "disabled" in element.attributes


def test_view_text_is_escaped(main_view: HelloMainView, rows: _RowsMainView) -> None:
    hostile = '"><script>alert(1)</script>'
    main_view.form.name.text = hostile
    rows.note.text = hostile

    field = _part(main_view.form.name, "field")
    label = rows.note.renderer
    assert isinstance(label, WebLabelRenderer)
    for fragment in (field.to_html(), label.to_html()):
        assert "<script>" not in fragment
    # escaped, not dropped: the browser shows exactly the view's text
    assert _element(field.to_html(), field.widget_id).attributes["value"] == hostile
    assert _element(label.to_html(), label.widget_id).text == hostile


def test_a_changed_field_inside_a_changed_group_is_swapped_once(
    pipe_main_view: PipeMainView,
) -> None:
    main_pipe = pipe_main_view.pipe_form.main_pipe
    group, radius = main_pipe.renderer, _part(main_pipe.radius, "field")
    assert isinstance(group, WebRenderer)

    with collect_dirty() as dirty:
        main_pipe.is_enabled = False
        main_pipe.radius.value = 1.0
    body = render_dirty(dirty)

    assert set(dirty) == {group.widget_id, radius.widget_id}
    # htmx would swap it twice otherwise: it only arrives within its group's fragment
    assert body.count(f'id="{radius.widget_id}"') == 1
    assert "hx-swap-oob" not in _element(body, radius.widget_id).attributes
    assert _swapped(body, group.widget_id).tag == "fieldset"


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

    def on_finished() -> None:
        finished.append(None)

    rows.length.text_edited.connect(edited.append)
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

    rows.length.text_edited.connect(edited.append)
    handle_event(field, "input", {"value": "-"})

    with collect_dirty() as dirty:
        rows.length.value = 7.0

    assert list(dirty) == [field.widget_id]
    assert 'value="7.0"' in field.to_html()
    # "-" again is a new edit against the server's 7.0, not a duplicate post
    handle_event(field, "input", {"value": "-"})
    assert edited == ["-", "-"]


def test_float_input_renders_a_decimal_text_field(rows: _RowsMainView) -> None:
    field = _part(rows.length, "field")

    attributes = _element(field.to_html(), field.widget_id).attributes

    # text, not `type="number"`: transient "-" must reach the server as typed
    assert attributes["type"] == "text"
    assert attributes["inputmode"] == "decimal"
    assert attributes["pattern"]
    assert attributes["value"] == "20.0"


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


def test_page_renders_the_choices(main_view: HelloMainView, client: TestClient) -> None:
    page = client.get("/").text
    style_id = _field_id(main_view.form.style)

    style = _element(page, style_id)
    radios = [attributes for tag, attributes in style.descendants if tag == "input"]
    assert style.attributes["role"] == "radiogroup"
    assert [radio["value"] for radio in radios] == ["Casual", "Formal"]
    # one radio set per group: named after the group's own id
    assert {radio["name"] for radio in radios} == {style_id}
    assert _selected(style) == ["Casual"]
    colour = _element(page, _field_id(main_view.form.colour))
    options = [attributes["value"] for tag, attributes in colour.descendants if tag == "option"]
    assert options == ["", "Red", "Green", "Blue"]
    assert _selected(colour) == [""]  # nothing chosen yet: the empty choice


def test_choosing_a_style_regreets_without_swapping_the_radio_group(
    main_view: HelloMainView, client: TestClient
) -> None:
    style_id = _field_id(main_view.form.style)
    _type_name(client, main_view, "Bob")

    body = client.post(f"/widget/{style_id}", data={style_id: "Formal", "event": "change"}).text

    assert main_view.form.style.value is GreetingStyle.FORMAL
    assert _swapped(body, _widget_id(main_view.status_bar.renderer)).text == "Good day, Bob."
    assert _find(body, style_id) is None


def test_choosing_a_colour_updates_the_summary(
    main_view: HelloMainView, client: TestClient
) -> None:
    colour_id = _field_id(main_view.form.colour)
    summary_id = _widget_id(main_view.summary.renderer)

    body = client.post(f"/widget/{colour_id}", data={colour_id: "Blue", "event": "change"}).text

    assert main_view.form.colour.value is Colour.BLUE
    assert _swapped(body, summary_id).text == "Nobody hasn't said how old they are and likes blue."
    assert _find(body, colour_id) is None

    # the empty choice clears the colour again
    body = client.post(f"/widget/{colour_id}", data={colour_id: "", "event": "change"}).text

    assert main_view.form.colour.value is None
    assert _swapped(body, summary_id).text == "Nobody hasn't said how old they are."


def test_an_unknown_label_clears_the_value_instead_of_failing(
    main_view: HelloMainView, client: TestClient
) -> None:
    colour_id = _field_id(main_view.form.colour)
    main_view.form.colour.value = Colour.RED

    response = client.post(f"/widget/{colour_id}", data={colour_id: "Purple", "event": "change"})

    assert response.status_code == 200
    assert main_view.form.colour.value is None


def test_choosing_the_current_value_again_does_not_re_emit(
    main_view: HelloMainView, client: TestClient
) -> None:
    style = main_view.form.style
    style_id = _field_id(style)
    emitted: list[GreetingStyle | None] = []

    style.value_changed.connect(emitted.append)

    for _ in range(2):
        client.post(f"/widget/{style_id}", data={style_id: "Formal", "event": "change"})

    assert emitted == [GreetingStyle.FORMAL]


def test_replacing_the_values_rerenders_the_options(main_view: HelloMainView) -> None:
    style = main_view.form.style
    renderer = _part(style, "field")
    assert isinstance(renderer, WebRadioGroupRenderer)
    style.value = GreetingStyle.FORMAL

    with collect_dirty() as dirty:
        # drops the current value, which `_reconcile_values` clears
        style.values = {"Casual": GreetingStyle.CASUAL}

    assert list(dirty) == [renderer.widget_id]
    assert style.value is None
    group = _element(renderer.to_html(), renderer.widget_id)
    radios = [attributes for tag, attributes in group.descendants if tag == "input"]
    assert [radio.get("value") for radio in radios] == ["Casual"]
    assert _selected(group) == []


def test_a_disabled_radio_group_disables_every_radio(main_view: HelloMainView) -> None:
    style = main_view.form.style
    field = _part(style, "field")
    assert isinstance(field, WebRadioGroupRenderer)

    style.is_enabled = False

    group = _element(field.to_html(), field.widget_id)
    radios = [attributes for tag, attributes in group.descendants if tag == "input"]
    assert len(radios) == 2
    assert all("disabled" in radio for radio in radios)


def test_a_radio_row_label_does_not_point_at_the_group(rows: _RowsMainView) -> None:
    label, field = _part(rows.shape, "label"), _part(rows.shape, "field")

    # a `<div>` isn't labelable: `for=` would point at nothing
    assert "for" not in _element(label.to_html(), label.widget_id).attributes

    handle_event(field, "change", {field.widget_id: "Square"})

    assert rows.shape.value is _Shape.SQUARE


def test_a_timed_message_makes_the_status_bar_fetch_itself_after_the_timeout(
    main_view: HelloMainView,
) -> None:
    status_bar = main_view.status_bar
    renderer = status_bar.renderer
    assert isinstance(renderer, WebStatusBarRenderer)
    status_bar.timeout = 3.0

    def attributes() -> dict[str, str | None]:
        return _element(renderer.to_html(), renderer.widget_id).attributes

    assert "hx-get" not in attributes()  # nothing to clear yet

    status_bar.message = "Saved"

    assert attributes()["hx-get"] == f"/widget/{renderer.widget_id}"
    assert attributes()["hx-trigger"] == "load delay:3250ms"
    assert attributes()["hx-swap"] == "outerHTML"

    status_bar.timeout = 0  # a message that never times out needs no fetch
    assert "hx-get" not in attributes()


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


@pytest.fixture
def pipe_views() -> list[PipeMainView]:
    """Each pipeform session's main view, kept by `pipe_client`'s app."""
    return []


@pytest.fixture
def pipe_web(pipe_views: list[PipeMainView]) -> Starlette:
    """Build the pipeform web app, keeping each session's main view in `pipe_views`."""

    class PipeApp(WebApplication[PipeMainView]):
        def __init__(self) -> None:
            super().__init__(build_main_view=PipeMainView)

        def setup_session(self, main_view: PipeMainView) -> None:
            main_view.status_bar.timeout = 0
            pipe_views.append(main_view)

    web: Starlette = PipeApp().create_starlette_app()
    return web


@pytest.fixture
def pipe_client(pipe_web: Starlette) -> Iterator[TestClient]:
    with TestClient(pipe_web) as client:
        client.get("/")  # starts the session
        yield client


@pytest.fixture
def pipe_main_view(pipe_views: list[PipeMainView], pipe_client: TestClient) -> PipeMainView:
    pipe_client.get("/")  # the client's own session: still the one view built so far
    (main_view,) = pipe_views
    return main_view


def test_clearing_the_name_shows_its_row_message(
    pipe_main_view: PipeMainView, pipe_client: TestClient
) -> None:
    name = pipe_main_view.pipe_form.name
    name_id = _field_id(name)
    pipe_client.post(f"/widget/{name_id}", data={"value": "Tee", "event": "input"})

    body = pipe_client.post(f"/widget/{name_id}", data={"value": "", "event": "input"}).text

    assert "A name is mandatory" in body
    assert f'id="{_widget_id(_part(name, "log"))}" hx-swap-oob="true"' in body


def test_disabling_a_group_disables_its_whole_fieldset(pipe_main_view: PipeMainView) -> None:
    main_pipe = pipe_main_view.pipe_form.main_pipe

    with collect_dirty() as dirty:
        main_pipe.is_enabled = False

    group = main_pipe.renderer
    assert isinstance(group, WebRenderer)
    assert list(dirty.values()) == [group]
    # a disabled fieldset disables every control inside it, like a disabled Qt container
    assert re.match(r'<fieldset id="[^"]+" class="[^"]+" disabled>', group.to_html())


def _type_name(client: TestClient, main_view: HelloMainView, name: str) -> None:
    field_id = _field_id(main_view.form.name)
    response = client.post(f"/widget/{field_id}", data={"value": name, "event": "input"})
    assert response.status_code == 200


def test_each_browser_gets_its_own_main_view(app: _HelloApp) -> None:
    web = app.create_starlette_app()
    with TestClient(web) as alice, TestClient(web) as bob:
        alice.get("/")
        bob.get("/")
        alice_view, bob_view = app.session_views

        _type_name(alice, alice_view, "Alice")

        assert alice_view.form.name.text == "Alice"
        assert bob_view.form.name.text == ""
        assert 'value="Alice"' in alice.get("/").text
        assert 'value="Alice"' not in bob.get("/").text


def test_app_connect_reacts_in_each_browser_on_its_own_views(app: _HelloApp) -> None:
    name = app.main_view.form.name

    @app.connect(view=name, signals=[name.text_edited])
    def echo(_text: str, *, view: NameRowView, main_view: HelloMainView) -> None:
        # connected after the view's own summary update, so it has the last word
        main_view.summary.text = f"Echo: {view.text}"

    web = app.create_starlette_app()
    with TestClient(web) as alice, TestClient(web) as bob:
        alice.get("/")
        bob.get("/")
        alice_view, bob_view = app.session_views

        def type_name(client: TestClient, view: HelloMainView, text: str) -> str:
            """Type `text` as the name; return the summary as swapped into the page."""
            field_id = _field_id(view.form.name)
            response = client.post(f"/widget/{field_id}", data={"value": text, "event": "input"})
            assert response.status_code == 200
            return _swapped(response.text, _widget_id(view.summary.renderer)).text

        assert type_name(alice, alice_view, "Alice") == "Echo: Alice"
        assert bob_view.summary.text != "Echo: Alice"
        assert type_name(bob, bob_view, "Bob") == "Echo: Bob"
        assert alice_view.summary.text == "Echo: Alice"
    assert app.main_view.summary.text != "Echo: Alice"  # the template is never wired


class _Guestbook(Model):
    def __init__(self) -> None:
        self.names: list[str] = []


def test_each_browser_gets_its_own_model() -> None:
    models: list[_Guestbook] = []

    def build_model() -> _Guestbook:
        models.append(_Guestbook())
        return models[-1]

    class GuestbookApp(WebModelApplication[HelloMainView, _Guestbook]):
        def setup_session(self, main_view: HelloMainView) -> None:
            views.append(main_view)

    views: list[HelloMainView] = []
    app = GuestbookApp(build_main_view=HelloMainView, build_model=build_model)
    name = app.main_view.form.name

    @app.connect(view=name, signals=[name.editing_finished])
    def sign(*, view: NameRowView, main_view: HelloMainView, model: _Guestbook) -> None:
        model.names.append(view.text)
        main_view.summary.text = ", ".join(model.names)

    def sign_as(client: TestClient, view: HelloMainView, text: str) -> str:
        """Enter `text` as the name; return the summary as the browser now shows it."""
        field_id = _field_id(view.form.name)
        response = client.post(f"/widget/{field_id}", data={"value": text, "event": "change"})
        assert response.status_code == 200
        return _element(client.get("/").text, _widget_id(view.summary.renderer)).text

    web = app.create_starlette_app()
    with TestClient(web) as alice, TestClient(web) as bob:
        alice.get("/")
        bob.get("/")
        alice_view, bob_view = views

        assert sign_as(alice, alice_view, "Alice") == "Alice"
        assert sign_as(bob, bob_view, "Bob") == "Bob"
        assert sign_as(alice, alice_view, "Ada") == "Alice, Ada"
    # one per session, and none for the template
    assert [model.names for model in models] == [["Alice", "Ada"], ["Bob"]]


def test_a_browser_cannot_reach_another_sessions_widgets(app: _HelloApp) -> None:
    web = app.create_starlette_app()
    with TestClient(web) as alice, TestClient(web) as mallory:
        alice.get("/")
        mallory.get("/")
        alice_view = app.session_views[0]

        # widget ids are guessable (`id()`-based): they must only resolve per session
        alice_field = _field_id(alice_view.form.name)
        response = mallory.post(f"/widget/{alice_field}", data={"value": "x", "event": "input"})

        assert response.status_code == 404
        assert alice_view.form.name.text == ""
        # while the very same id still works for its own session
        _type_name(alice, alice_view, "Alice")
        assert alice_view.form.name.text == "Alice"


def test_a_request_without_a_live_session_reloads_the_page(
    main_view: HelloMainView, app: _HelloApp
) -> None:
    field_id = _field_id(main_view.form.name)
    # e.g. after a server restart: the browser's cookie points at no session any more
    with TestClient(app.create_starlette_app()) as stale:
        posted = stale.post(f"/widget/{field_id}", data={"value": "x", "event": "input"})
        fetched = stale.get(f"/widget/{field_id}")
        uploaded = stale.post("/state", files={"file": ("s.hello", b"{}")})
        # a plain download link isn't htmx: it is sent to the page, which starts a session
        downloaded = stale.get("/state", follow_redirects=False)

    for response in (posted, fetched, uploaded):
        assert response.status_code == 200
        assert response.headers["hx-refresh"] == "true"
        assert response.text == ""
    assert downloaded.status_code == 303
    assert downloaded.headers["location"] == "/"


def test_a_session_is_built_once_and_kept_across_reloads(app: _HelloApp) -> None:
    with TestClient(app.create_starlette_app()) as client:
        client.get("/")
        _type_name(client, app.session_views[0], "Bob")

        page = client.get("/").text

    assert len(app.session_views) == 1
    assert 'value="Bob"' in page


class _ShortLivedHelloApp(_HelloApp):
    session_ttl = 0.0  # every session is already idle for too long by its next request


def test_an_idle_session_expires() -> None:
    app = _ShortLivedHelloApp()
    with TestClient(app.create_starlette_app()) as client:
        client.get("/")
        expired_view = app.session_views[0]

        response = client.post(
            f"/widget/{_field_id(expired_view.form.name)}",
            data={"value": "x", "event": "input"},
        )
        client.get("/")

    assert response.headers["hx-refresh"] == "true"
    assert expired_view.form.name.text == ""
    assert len(app.session_views) == 2  # the reload started a fresh session


def test_a_state_file_opens_in_every_new_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    study = HelloMainView()
    study.form.name.text = "Bob"
    state_file = tmp_path / "study.hello"
    study.save_state(state_file)
    served: list[Starlette] = []
    monkeypatch.setattr("sys.argv", ["webhello", "-f", str(state_file)])
    # the server itself is out of scope: keep the app it would serve
    monkeypatch.setattr(
        "composeui.webcore.webapplication.uvicorn.run",
        lambda app, **_: served.append(app),
    )
    app = _HelloApp()

    app.run()

    with TestClient(served[0]) as alice, TestClient(served[0]) as bob:
        pages = [alice.get("/").text, bob.get("/").text]
    assert [view.form.name.text for view in app.session_views] == ["Bob", "Bob"]
    assert all('value="Bob"' in page for page in pages)


def test_reload_serves_a_factory_rebuilding_the_app_with_the_same_command_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    study = HelloMainView()
    study.form.name.text = "Bob"
    state_file = tmp_path / "study.hello"
    study.save_state(state_file)
    served: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr("sys.argv", ["webhello", "--reload", "-f", str(state_file)])
    monkeypatch.setattr(
        "composeui.webcore.webapplication.uvicorn.run",
        lambda app, **kwargs: served.append((app, kwargs)),
    )
    # restores the variable `run` sets for the reloaded process
    monkeypatch.setenv("COMPOSEUI_WEB_APP", "")

    _HelloApp().run()

    ((import_string, options),) = served
    assert options["reload"] is True
    assert options["factory"] is True
    # what uvicorn's reloaded process does with it, without spawning one
    factory = import_from_string(import_string)
    with TestClient(factory()) as client:
        assert 'value="Bob"' in client.get("/").text


def test_reload_refuses_an_app_it_cannot_rebuild(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["webhello", "--reload"])
    monkeypatch.setattr(
        "composeui.webcore.webapplication.uvicorn.run",
        lambda *_, **__: pytest.fail("served an app the reloader can't rebuild"),
    )
    monkeypatch.setenv("COMPOSEUI_WEB_APP", "")

    with pytest.raises(ValueError, match="takes no arguments"):
        WebApplication(build_main_view=HelloMainView).run()


class _SlowGreetingApp(_HelloApp):
    """A greeting whose message times out while the request that showed it still runs."""

    def __init__(self) -> None:
        super().__init__()
        self.messages_seen_by_the_request: list[str] = []

    def setup_session(self, main_view: HelloMainView) -> None:
        super().setup_session(main_view)
        main_view.status_bar.timeout = 0.05

        # connected after the greeting, so it runs once "Hello, ...!" is shown
        def slow_callback(_text: str) -> None:
            time.sleep(0.3)  # the message's timer fires meanwhile, on its own thread
            self.messages_seen_by_the_request.append(main_view.status_bar.message)

        main_view.form.name.text_edited.connect(slow_callback)


def test_a_message_timer_waits_for_the_request_holding_the_session() -> None:
    app = _SlowGreetingApp()
    with TestClient(app.create_starlette_app()) as client:
        client.get("/")
        main_view = app.session_views[0]

        _type_name(client, main_view, "Bob")

        # the timer couldn't touch the tree mid-request: the clear waited for the lock
        assert app.messages_seen_by_the_request == ["Hello, Bob!"]
        deadline = time.monotonic() + 2
        while main_view.status_bar.message and time.monotonic() < deadline:
            time.sleep(0.01)
        assert main_view.status_bar.message == ""


def test_saving_downloads_the_session_state(main_view: HelloMainView, client: TestClient) -> None:
    _type_name(client, main_view, "Bob")

    response = client.get("/state")

    assert response.status_code == 200
    assert response.headers["content-disposition"] == (
        'attachment; filename="hello-composeui.hello"'
    )
    assert response.headers["cache-control"] == "no-store"
    assert json.loads(response.text)["form"]["name"]["text"] == "Bob"


def test_a_saved_state_opens_in_another_browser(app: _HelloApp) -> None:
    web = app.create_starlette_app()
    with TestClient(web) as alice, TestClient(web) as bob:
        alice.get("/")
        bob.get("/")
        alice_view, bob_view = app.session_views
        _type_name(alice, alice_view, "Alice")
        style_id = _field_id(alice_view.form.style)
        alice.post(f"/widget/{style_id}", data={style_id: "Formal", "event": "change"})
        saved = alice.get("/state").content

        response = bob.post("/state", files={"file": ("study.hello", saved)})

        # a load can change anything: the page reloads instead of swapping fragments
        assert response.headers["hx-refresh"] == "true"
        assert bob_view.form.name.text == "Alice"
        assert bob_view.form.style.value is GreetingStyle.FORMAL
        assert 'value="Alice"' in bob.get("/").text
        # the next save offers the name the state was opened from
        assert 'filename="study.hello"' in bob.get("/state").headers["content-disposition"]


@pytest.mark.parametrize(
    ("filename", "content", "reason"),
    [
        ("study.pipe", b"{}", "expected a .hello file"),
        ("study.hello", b"{not json", "isn&#x27;t a valid .hello file"),
        ("study.hello", b"[1, 2]", "isn&#x27;t a valid .hello file"),
        ("study.hello", b" " * (5 * 1024 * 1024 + 1), "the file is too large"),
        # fails halfway: the valid name must not be applied before the bad age fails
        (
            "study.hello",
            b'{"form": {"name": {"text": "Eve"}, "age": {"value": "abc"}}}',
            "doesn&#x27;t match this application",
        ),
    ],
)
def test_a_rejected_state_file_changes_nothing_and_says_why(
    main_view: HelloMainView, client: TestClient, filename: str, content: bytes, reason: str
) -> None:
    _type_name(client, main_view, "Bob")

    response = client.post("/state", files={"file": (filename, content)})

    assert "hx-refresh" not in response.headers
    status_bar_id = _widget_id(main_view.status_bar.renderer)
    assert f'<footer id="{status_bar_id}" hx-swap-oob="true"' in response.text
    assert reason in response.text
    assert main_view.form.name.text == "Bob"
    assert main_view.state_filepath is None


def test_an_uploaded_file_name_cannot_reach_the_download_header(
    main_view: HelloMainView, client: TestClient
) -> None:
    # built by hand: httpx would percent-encode the quote before it reached the server
    body = (
        b"--b\r\n"
        b'Content-Disposition: form-data; name="file"; filename="evil\\"; x=1; my study.hello"\r\n'
        b"Content-Type: application/octet-stream\r\n\r\n"
        b"{}\r\n--b--\r\n"
    )

    client.post("/state", content=body, headers={"Content-Type": "multipart/form-data; boundary=b"})

    assert main_view.state_filepath is not None
    assert '"' in main_view.state_filepath.name  # the hostile name did reach the server
    disposition = client.get("/state").headers["content-disposition"]
    assert re.fullmatch(r'attachment; filename="[A-Za-z0-9._-]+\.hello"', disposition)


def _action_id(action: Any) -> str:
    return _widget_id(action.renderer)


def _count(signal: Any) -> list[None]:
    """Record each emission of a no-argument signal."""
    emitted: list[None] = []

    def on_triggered() -> None:
        emitted.append(None)

    signal.connect(on_triggered)
    return emitted


def test_the_file_menu_sits_in_the_header(main_view: HelloMainView, client: TestClient) -> None:
    menu = main_view.file_menu
    assert not menu.is_visible  # "popped up" in Qt terms; a dropdown is always shown

    page = client.get("/").text

    header = page[page.index("<header") : page.index("</header>")]
    assert f'<div id="{_widget_id(menu.renderer)}" class="dropdown">' in header
    assert 'role="separator"' in header
    assert f'href="/state?trigger={_action_id(menu.save)}" download' in header
    assert 'type="file" name="file"' in header
    assert f'hx-post="/widget/{_action_id(menu.new)}"' in header


@pytest.mark.parametrize(
    ("action", "key"), [("new", "N"), ("open_file", "O"), ("save", "S"), ("exit_app", "Q")]
)
def test_menu_shortcuts_avoid_the_browsers_own(
    main_view: HelloMainView, client: TestClient, action: str, key: str
) -> None:
    """Ctrl+N/O/S/Q belong to the browser (new window, open, save page, quit Firefox)."""
    page = client.get("/").text
    item_id = _action_id(getattr(main_view.file_menu, action))
    item = page[page.index(f'<li id="{item_id}"') :]
    item = item[: item.index("</li>")]

    assert f'<kbd class="kbd kbd-sm">Alt+Shift+{key}</kbd>' in item
    # what the page's key handler clicks when Alt+Shift+<key> is pressed
    assert f'data-shortcut="Key{key}"' in item
    assert "Ctrl" not in page[page.index("<header") : page.index("</header>")]


def test_save_as_has_no_web_shortcut(main_view: HelloMainView, client: TestClient) -> None:
    # in a browser it downloads just like Save, whose Alt+Shift+S it would collide with
    page = client.get("/").text
    item = page[page.index(f'<li id="{_action_id(main_view.file_menu.save_as)}"') :]
    item = item[: item.index("</li>")]

    assert "<kbd" not in item
    assert "data-shortcut" not in item


def test_an_action_fires_its_triggered_unless_disabled() -> None:
    # a plain action: every File menu one also does more (New, Exit, Save, Open)
    action = ActionView(text="Refresh")
    action.render(RendererType.WEB)
    renderer = action.renderer
    assert isinstance(renderer, WebRenderer)
    triggered = _count(action.triggered)

    handle_event(renderer, "triggered", {})

    assert len(triggered) == 1

    action.is_enabled = False

    with pytest.raises(UnsupportedEventError):  # the route answers 400
        handle_event(renderer, "triggered", {})
    assert len(triggered) == 1


def test_exit_ends_the_session(
    app: _HelloApp, main_view: HelloMainView, client: TestClient
) -> None:
    field_id = _field_id(main_view.form.name)

    response = client.post(
        f"/widget/{_action_id(main_view.file_menu.exit_app)}", data={"event": "triggered"}
    )

    assert response.headers["hx-redirect"] == "/"
    stale = client.post(f"/widget/{field_id}", data={"value": "x", "event": "input"})
    assert stale.headers["hx-refresh"] == "true"
    client.get("/")
    assert len(app.session_views) == 2  # the redirect lands on a fresh session


@pytest.mark.parametrize("action", ["save", "save_as"])
def test_a_save_link_fires_its_action_then_downloads(
    main_view: HelloMainView, client: TestClient, action: str
) -> None:
    save = getattr(main_view.file_menu, action)
    triggered = _count(save.triggered)
    _type_name(client, main_view, "Bob")

    response = client.get(f"/state?trigger={_action_id(save)}")

    assert len(triggered) == 1
    assert "attachment" in response.headers["content-disposition"]
    assert json.loads(response.text)["form"]["name"]["text"] == "Bob"


def test_the_open_upload_fires_its_action_then_loads(
    main_view: HelloMainView, client: TestClient
) -> None:
    open_file = main_view.file_menu.open_file
    triggered = _count(open_file.triggered)
    saved = json.dumps({"form": {"name": {"text": "Zoe"}}}).encode()

    response = client.post(
        "/state",
        files={"file": ("study.hello", saved)},
        data={"trigger": _action_id(open_file)},
    )

    assert len(triggered) == 1
    assert response.headers["hx-refresh"] == "true"
    assert main_view.form.name.text == "Zoe"


def test_triggering_a_checkable_action_toggles_its_check_mark() -> None:
    action = ActionView(text="Wrap", is_checkable=True)
    action.render(RendererType.WEB)
    renderer = action.renderer
    assert isinstance(renderer, WebRenderer)

    # the item comes back as an out-of-band fragment, with its check mark toggled
    assert "<span>✓ Wrap</span>" in handle_event(renderer, "triggered", {})
    assert "<span>Wrap</span>" in handle_event(renderer, "triggered", {})


def test_new_clears_the_form_in_place(
    app: _HelloApp, main_view: HelloMainView, client: TestClient
) -> None:
    form = main_view.form
    triggered = _count(main_view.file_menu.new.triggered)
    _type_name(client, main_view, "Bob")
    client.post(f"/widget/{_field_id(form.age)}", data={"value": "41", "event": "input"})

    response = client.post(
        f"/widget/{_action_id(main_view.file_menu.new)}", data={"event": "triggered"}
    )

    assert len(triggered) == 1
    assert form.name.text == ""
    assert form.age.value is None
    # reset in place: every field New changed comes back out of band, no reload
    assert "hx-refresh" not in response.headers
    for widget_id in (
        _field_id(form.name),
        _field_id(form.age),
        _widget_id(main_view.summary.renderer),
    ):
        assert f'id="{widget_id}" hx-swap-oob="true"' in response.text
    assert "Nobody hasn&#x27;t said how old they are." in response.text
    assert len(app.session_views) == 1


def test_a_pipe_study_from_first_page_to_reopening_it_elsewhere(
    pipe_web: Starlette, pipe_views: list[PipeMainView]
) -> None:
    """One study through the whole web stack, the way a user drives it.

    Every step checks both what the browser receives (each changed fragment out of band,
    never the field being edited) and the views behind it.
    """
    htmx = {"HX-Request": "true"}
    with TestClient(pipe_web, headers=htmx) as alice, TestClient(pipe_web, headers=htmx) as bob:
        page = alice.get("/").text
        (view,) = pipe_views
        form = view.pipe_form
        name_id, material_id = _field_id(form.name), _field_id(form.material)
        edge_id, radius_id = _field_id(form.edge_type), _field_id(form.main_pipe.radius)
        name_log_id = _widget_id(_part(form.name, "log"))
        fillet_id, chamfer_id = _widget_id(form.fillet.renderer), _widget_id(form.chamfer.renderer)
        form_log_id = _widget_id(form.log_view.renderer)

        def post(widget_id: str, data: dict[str, str]) -> str:
            response = alice.post(f"/widget/{widget_id}", data=data)
            assert response.status_code == 200
            assert _find(response.text, widget_id) is None  # never the edited field
            return response.text

        # the page as first served: rows, titled groups, edge options hidden
        for label in ("Name", "Material", "Radius", "Half Length", "Edge Type"):
            assert f">{label}</label>" in page
        assert '<legend class="fieldset-legend">Main Pipe</legend>' in page
        assert _element(page, name_log_id).text == "A name is mandatory"
        assert _selected(_element(page, material_id)) == ["Steel"]
        assert _selected(_element(page, edge_id)) == ["Normal"]
        for group_id in (fillet_id, chamfer_id):
            assert "hidden" in _element(page, group_id).attributes
        assert "hidden" in _element(page, form_log_id).attributes

        # a name clears its row's message
        body = post(name_id, {"value": "Tee", "event": "input"})
        assert form.name.text == "Tee"
        assert "hidden" in _swapped(body, name_log_id).attributes

        # another material changes nothing else on the page
        assert post(material_id, {material_id: "Copper", "event": "change"}) == ""
        assert form.material.value is not None
        assert form.material.value.value == "Copper"

        # Fillet shows its group and says so in the status bar
        body = post(edge_id, {edge_id: "Fillet", "event": "change"})
        assert "hidden" not in _swapped(body, fillet_id).attributes
        assert _swapped(body, _widget_id(view.status_bar.renderer)).text == (
            "Edge type changed: Fillet"
        )
        assert _find(body, chamfer_id) is None  # still hidden: unchanged

        # a main radius below the incident one fails the cross-field check, which is
        # wired to `editing_finished`: typing alone doesn't run it...
        assert _find(post(radius_id, {"value": "5", "event": "input"}), form_log_id) is None
        log = _swapped(post(radius_id, {"value": "5", "event": "change"}), form_log_id)
        assert "hidden" not in log.attributes
        assert "incident radius" in log.text
        # ...until it is fixed
        post(radius_id, {"value": "60", "event": "input"})
        assert (
            "hidden"
            in _swapped(post(radius_id, {"value": "60", "event": "change"}), form_log_id).attributes
        )
        assert form.log_view.log_message == ""

        # saved, then opened in another browser's session
        saved = alice.get("/state").content
        bob.get("/")
        reopened = pipe_views[1].pipe_form
        assert (
            bob.post("/state", files={"file": ("tee.pipe", saved)}).headers["hx-refresh"] == "true"
        )
        _assert_shows_the_tee_study(bob.get("/").text, reopened)


def _assert_shows_the_tee_study(page: str, form: Any) -> None:
    """Check a page and its pipe form hold the study the end-to-end test built."""
    assert _element(page, _field_id(form.name)).attributes["value"] == "Tee"
    assert "hidden" in _element(page, _widget_id(_part(form.name, "log"))).attributes
    assert _selected(_element(page, _field_id(form.material))) == ["Copper"]
    assert _selected(_element(page, _field_id(form.edge_type))) == ["Fillet"]
    assert "hidden" not in _element(page, _widget_id(form.fillet.renderer)).attributes
    assert _element(page, _field_id(form.main_pipe.radius)).attributes["value"] == "60.0"
    assert "hidden" in _element(page, _widget_id(form.log_view.renderer)).attributes
    assert form.name.text == "Tee"
    assert form.main_pipe.radius.value == 60.0


def test_the_page_loads_nothing_from_another_host(client: TestClient) -> None:
    """Styles and scripts are served by the app itself, so it also works offline."""
    page = client.get("/").text

    assert re.findall(r'(?:src|href)="(?:https?:)?//[^"]*"', page) == []
    assert client.get("/static/app.css").status_code == 200


def test_every_class_the_renderers_use_is_in_the_built_stylesheet(
    main_view: HelloMainView, client: TestClient, pipe_client: TestClient
) -> None:
    """Catches a class added in Python without rebuilding `static/app.css` (`make css`)."""
    markup = [client.get("/").text, pipe_client.get("/").text]
    for log_type in LogType:  # each log colour
        log = LogView(log_message="x", log_type=log_type)
        log.render(RendererType.WEB)
        assert isinstance(log.renderer, WebRenderer)
        markup.append(log.renderer.to_html())
    main_view.file_menu.new.is_enabled = False  # a disabled menu item
    markup.append(client.get("/").text)
    classes = {
        name
        for page in markup
        for value in re.findall(r'class="([^"]*)"', page)
        for name in value.split()
    }
    stylesheet = client.get("/static/app.css").text

    missing = sorted(
        name for name in classes if not re.search(rf"\.{re.escape(name)}(?![\w-])", stylesheet)
    )
    assert len(classes) > 40
    assert missing == []


def test_form_fields_are_linked_to_their_label_and_message(
    main_view: HelloMainView, client: TestClient
) -> None:
    """Screen readers read a row's message with its field, and know when it's invalid."""
    form = main_view.form
    page = client.get("/").text

    name = _element(page, _field_id(form.name))
    assert name.attributes["aria-describedby"] == _widget_id(_part(form.name, "log"))
    assert name.attributes["aria-invalid"] == "true"  # starts on "A name is mandatory"
    age = _element(page, _field_id(form.age))
    assert age.attributes["aria-describedby"] == _widget_id(_part(form.age, "log"))
    assert "aria-invalid" not in age.attributes
    # `<label for>` can't name a radio group's `<div>`: the group points at its label
    style = _element(page, _field_id(form.style))
    assert style.attributes["aria-labelledby"] == _widget_id(_part(form.style, "label"))

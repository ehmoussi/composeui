"""Coverage for the web backend (Starlette + htmx).

Editing a field posts the browser event to `/widget/{id}`; the response carries every
fragment the event changed as an htmx out-of-band swap, except the field itself, which
is never swapped back while the user is typing in it. The hello example and
`examples/pipeform.py` are driven over HTTP; a few renderer-level cases drive rows
directly through `handle_event`, the function the route calls.
"""

from __future__ import annotations

import enum
import json
import re
import time
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
from examples.webhello import Colour, GreetingStyle, HelloApp, HelloMainView

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from starlette.applications import Starlette

    from examples.pipeform import PipeMainView


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


def test_page_renders_the_input_and_the_status_bar(
    main_view: HelloMainView, client: TestClient
) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "<title>Hello ComposeUI</title>" in response.text
    assert f'id="{_field_id(main_view.form.name)}"' in response.text
    assert 'placeholder="Type your name..."' in response.text
    assert f'id="{_widget_id(main_view.status_bar.renderer)}"' in response.text


def test_page_shows_the_title_and_docks_an_empty_status_bar(
    main_view: HelloMainView, client: TestClient
) -> None:
    response = client.get("/")

    assert '<h1 class="text-lg font-semibold">Hello ComposeUI</h1>' in response.text
    assert '<meta name="viewport"' in response.text
    status_bar_id = _widget_id(main_view.status_bar.renderer)
    status_bar = response.text[response.text.index(f'<footer id="{status_bar_id}"') :]
    status_bar = status_bar[: status_bar.index("</footer>")]
    # a status line, not a coloured callout: an empty message must not show a bar
    assert "alert" not in status_bar
    assert "fixed inset-x-0 bottom-0" in status_bar
    assert status_bar.endswith(">")


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


def test_typing_updates_the_status_bar_out_of_band(
    main_view: HelloMainView, client: TestClient
) -> None:
    input_id = _field_id(main_view.form.name)

    response = client.post(f"/widget/{input_id}", data={"value": "Bob", "event": "input"})

    assert response.status_code == 200
    assert main_view.form.name.text == "Bob"
    assert main_view.status_bar.message == "Hello, Bob!"
    status_bar_id = _widget_id(main_view.status_bar.renderer)
    assert f'<footer id="{status_bar_id}" hx-swap-oob="true"' in response.text
    assert "Hello, Bob!" in response.text
    # the field being typed in is never swapped back
    assert input_id not in response.text


def test_one_keystroke_fans_out_to_the_log_the_summary_and_the_status_bar(
    main_view: HelloMainView, client: TestClient
) -> None:
    assert main_view.form.name.log_message == "A name is mandatory"
    input_id = _field_id(main_view.form.name)

    body = client.post(f"/widget/{input_id}", data={"value": "Bob", "event": "input"}).text

    swapped = {
        renderer.widget_id
        for renderer in (
            _part(main_view.form.name, "log"),
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


def test_age_is_validated_and_summarised(main_view: HelloMainView, client: TestClient) -> None:
    age_id = _field_id(main_view.form.age)

    body = client.post(f"/widget/{age_id}", data={"value": "-3", "event": "input"}).text

    assert main_view.form.age.value == -3.0
    assert "An age can&#x27;t be negative" in body

    client.post(f"/widget/{age_id}", data={"value": "41", "event": "input"})

    assert main_view.form.age.log_message == ""
    assert main_view.summary.text == "Nobody is 41 years old."


def test_leaving_the_age_field_with_unparsable_text_shows_the_age_again(
    main_view: HelloMainView, client: TestClient
) -> None:
    age_id = _field_id(main_view.form.age)
    finished: list[None] = []

    def on_finished() -> None:
        finished.append(None)

    main_view.form.age.editing_finished.connect(on_finished)
    client.post(f"/widget/{age_id}", data={"value": "4", "event": "input"})
    client.post(f"/widget/{age_id}", data={"value": "4a", "event": "input"})

    body = client.post(f"/widget/{age_id}", data={"value": "4a", "event": "change"}).text

    # the field, otherwise never swapped back, now shows the age its messages describe
    assert main_view.form.age.value == 4.0
    assert f'<input id="{age_id}" hx-swap-oob="true"' in body
    assert 'value="4.0"' in body
    assert finished == []


def test_change_event_applies_the_text_and_finishes_editing_once(
    main_view: HelloMainView, client: TestClient
) -> None:
    greeting = main_view.form.name
    finished: list[None] = []
    edited: list[str] = []
    greeting.editing_finished.connect(lambda: finished.append(None))

    # a def, not `edited.append`: signal logging needs the callback's `__code__`
    def on_edited(text: str) -> None:
        edited.append(text)

    greeting.text_edited.connect(on_edited)
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


def test_changes_outside_a_request_are_not_collected(main_view: HelloMainView) -> None:
    status_bar = main_view.status_bar

    status_bar.message = "from a timer thread"

    assert isinstance(status_bar.renderer, WebStatusBarRenderer)
    assert "from a timer thread" in status_bar.renderer.to_html()


def test_changes_inside_a_request_mark_the_renderer_dirty_once(main_view: HelloMainView) -> None:
    name = main_view.form.name

    with collect_dirty() as dirty:
        name.placeholder = "Name"
        name.text = "Zoe"

    assert list(dirty.values()) == [_part(name, "field")]


def test_hidden_and_disabled_views_keep_their_id(main_view: HelloMainView) -> None:
    name = main_view.form.name
    field = _part(name, "field")
    assert isinstance(field, WebInputRenderer)

    name.is_visible = False
    name.is_enabled = False

    fragment = field.to_html()
    assert f'id="{field.widget_id}" hidden' in fragment
    assert fragment.endswith(" disabled>")


def test_view_text_is_escaped(main_view: HelloMainView) -> None:
    name = main_view.form.name

    name.text = '"><script>alert(1)</script>'

    fragment = _part(name, "field").to_html()
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


def test_page_renders_the_choices(main_view: HelloMainView, client: TestClient) -> None:
    page = client.get("/").text
    style_id = _field_id(main_view.form.style)
    colour_id = _field_id(main_view.form.colour)

    assert f'<div id="{style_id}" role="radiogroup"' in page
    assert page.count('type="radio" class="radio radio-sm" value="') == 2
    assert f'value="Casual" checked name="{style_id}"' in page
    assert f'value="Formal" name="{style_id}"' in page
    # nothing chosen yet: the combobox starts on its empty choice
    assert f'<select id="{colour_id}"' in page
    assert '<option value="" selected></option><option value="Red">Red</option>' in page


def test_choosing_a_style_regreets_without_swapping_the_radio_group(
    main_view: HelloMainView, client: TestClient
) -> None:
    input_id = _field_id(main_view.form.name)
    style_id = _field_id(main_view.form.style)
    client.post(f"/widget/{input_id}", data={"value": "Bob", "event": "input"})

    body = client.post(f"/widget/{style_id}", data={style_id: "Formal", "event": "change"}).text

    assert main_view.form.style.value is GreetingStyle.FORMAL
    assert main_view.status_bar.message == "Good day, Bob."
    assert "Good day, Bob." in body
    assert style_id not in body


def test_choosing_a_colour_updates_the_summary(
    main_view: HelloMainView, client: TestClient
) -> None:
    colour_id = _field_id(main_view.form.colour)

    body = client.post(f"/widget/{colour_id}", data={colour_id: "Blue", "event": "change"}).text

    assert main_view.form.colour.value is Colour.BLUE
    assert "and likes blue." in body
    assert colour_id not in body

    # the empty choice clears the colour again
    client.post(f"/widget/{colour_id}", data={colour_id: "", "event": "change"})

    assert main_view.form.colour.value is None
    assert main_view.summary.text == "Nobody hasn't said how old they are."


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

    def on_changed(value: GreetingStyle | None) -> None:
        emitted.append(value)

    style.value_changed.connect(on_changed)

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
    fragment = renderer.to_html()
    assert "Formal" not in fragment
    assert "checked" not in fragment


def test_a_disabled_radio_group_disables_every_radio(main_view: HelloMainView) -> None:
    style = main_view.form.style
    field = _part(style, "field")
    assert isinstance(field, WebRadioGroupRenderer)

    style.is_enabled = False

    assert field.to_html().count(" disabled>") == 2


def test_a_radio_row_label_does_not_point_at_the_group(rows: _RowsMainView) -> None:
    label, field = _part(rows.shape, "label"), _part(rows.shape, "field")

    assert "for=" not in label.to_html()
    assert f'name="{field.widget_id}"' in field.to_html()

    handle_event(field, "change", {field.widget_id: "Square"})

    assert rows.shape.value is _Shape.SQUARE


def test_a_timed_message_makes_the_status_bar_fetch_itself_after_the_timeout(
    main_view: HelloMainView,
) -> None:
    status_bar = main_view.status_bar
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
    assert response.text.startswith(f'<footer id="{status_bar_id}" role="status"')
    assert "Hello, Bob!" not in response.text
    assert "hx-get" not in response.text
    assert client.get("/widget/cui-0-status_bar").status_code == 404


@pytest.fixture
def pipe_views() -> list[PipeMainView]:
    """Each pipeform session's main view, kept by `pipe_client`'s app."""
    return []


@pytest.fixture
def pipe_client(pipe_views: list[PipeMainView]) -> Iterator[TestClient]:
    # pipeform also builds its Qt and Textual apps, so it needs those extras too
    pipeform = pytest.importorskip("examples.pipeform")

    class PipeApp(pipeform.WebPipeApp):  # type: ignore[misc,name-defined]
        def setup_session(self, main_view: PipeMainView) -> None:
            main_view.status_bar.timeout = 0
            pipe_views.append(main_view)

    with TestClient(PipeApp().create_starlette_app()) as client:
        client.get("/")  # starts the session
        yield client


@pytest.fixture
def pipe_main_view(pipe_views: list[PipeMainView], pipe_client: TestClient) -> PipeMainView:
    pipe_client.get("/")  # the client's own session: still the one view built so far
    (main_view,) = pipe_views
    return main_view


def test_pipeform_renders_its_rows_groups_and_hidden_edge_options(
    pipe_main_view: PipeMainView, pipe_client: TestClient
) -> None:
    form = pipe_main_view.pipe_form

    page = pipe_client.get("/").text

    for label in ("Name", "Material", "Radius", "Half Length", "Edge Type"):
        assert f">{label}</label>" in page
    assert '<legend class="fieldset-legend">Main Pipe</legend>' in page
    assert f'value="Normal" checked name="{_field_id(form.edge_type)}"' in page
    assert '<option value="Steel" selected>' in page
    for group in (form.chamfer, form.fillet):
        assert f'<fieldset id="{_widget_id(group.renderer)}" hidden' in page
    # the cross-field log has nothing to say yet
    assert f'<p id="{_widget_id(form.log_view.renderer)}" hidden' in page


def test_choosing_chamfer_reveals_its_group_and_reports_it(
    pipe_main_view: PipeMainView, pipe_client: TestClient
) -> None:
    form = pipe_main_view.pipe_form
    edge_id = _field_id(form.edge_type)
    chamfer_id = _widget_id(form.chamfer.renderer)

    body = pipe_client.post(f"/widget/{edge_id}", data={edge_id: "Chamfer", "event": "change"}).text

    assert form.chamfer.is_visible
    assert f'<fieldset id="{chamfer_id}" hx-swap-oob="true" class=' in body
    assert "Edge type changed: Chamfer" in body
    assert edge_id not in body
    assert _widget_id(form.fillet.renderer) not in body  # still hidden: unchanged


def test_a_cross_field_check_runs_once_editing_finishes(
    pipe_main_view: PipeMainView, pipe_client: TestClient
) -> None:
    form = pipe_main_view.pipe_form
    radius_id = _field_id(form.main_pipe.radius)
    log_id = _widget_id(form.log_view.renderer)

    typed = pipe_client.post(f"/widget/{radius_id}", data={"value": "5", "event": "input"}).text
    # wired to `editing_finished`: typing alone doesn't run the form's checks
    assert log_id not in typed

    body = pipe_client.post(f"/widget/{radius_id}", data={"value": "5", "event": "change"}).text

    assert f'<p id="{log_id}" hx-swap-oob="true" aria-live' in body
    assert "The incident radius cant&#x27;be greater than the main radius" in body


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

"""Coverage for the web backend (Starlette + htmx).

Editing a field posts the browser event to `/widget/{id}`; the response carries every
fragment the event changed as an htmx out-of-band swap, except the field itself, which
is never swapped back while the user is typing in it. The hello example and
`examples/pipeform` are driven over HTTP; a few renderer-level cases drive rows
directly through `handle_event`, the function the route calls.
"""

from __future__ import annotations

import enum
import hashlib
import html
import json
import math
import os
import re
import sys
import threading
import time
import types
from html.parser import HTMLParser
from importlib.util import find_spec
from typing import TYPE_CHECKING, Any, NamedTuple

import pytest

pytest.importorskip("starlette")
pytest.importorskip("httpx")

from attrs import Factory
from starlette.testclient import TestClient
from uvicorn.importer import import_from_string

from composeui.core import chartimage
from composeui.core.model import Model, RefusedError
from composeui.core.registry import RendererType
from composeui.core.renderer import NoRenderedObjectError, RendererContainer
from composeui.core.sqlitemodel import SqliteModel, SqliteTable
from composeui.core.view import (
    ActionView,
    ButtonVariant,
    ButtonView,
    ChartKind,
    ChartView,
    DialogView,
    EditRefusedError,
    LabelRowFloatInputView,
    LabelRowInputView,
    LabelRowRadioGroupView,
    LabelView,
    LogType,
    LogView,
    MainView,
    Menu,
    PageView,
    Router,
    SaveAsAction,
    SelectionMode,
    SeparatorAction,
    Series,
    StatusBar,
    TableView,
    View,
    define_view,
    replace_cell,
)
from composeui.webcore.page import JOBS_POLL_MS
from composeui.webcore.webapplication import WebApplication, WebModelApplication
from composeui.webcore.webrenderer import (
    CHART_MAX_POINTS,
    RESERVED_ROUTES,
    UnsupportedEventError,
    WebActionRenderer,
    WebChartRenderer,
    WebFloatInputRenderer,
    WebInputRenderer,
    WebLabelRenderer,
    WebLogRenderer,
    WebMainRenderer,
    WebMarkdownRenderer,
    WebRadioGroupRenderer,
    WebRenderer,
    WebStatusBarRenderer,
    WebTableRenderer,
    collect_dirty,
    handle_event,
    render_dirty,
)
from examples import pipeform
from examples.batman import BatmanMainView
from examples.pipechart import PipeChartMainView
from examples.pipeform import PipeMainView
from examples.webhello import Colour, GreetingStyle, HelloApp, HelloMainView, NameRowView
from tests.charts import ChartPagesMainView
from tests.dialogs import DialogsMainView
from tests.horizontal import HorizontalMainView
from tests.markdown import HelpMainView, HelpViewerMainView
from tests.pages import InputsPage, PagesMainView
from tests.tables import EditableTableMainView, Room, RoomsMainView, SortedRoomsMainView
from tests.toolbar import ToolBarMainView
from tests.translated import Size, TranslatedMainView
from tests.vertical import VerticalMainView

if TYPE_CHECKING:
    import argparse
    from collections.abc import Iterator
    from pathlib import Path

    from starlette.applications import Starlette

    from composeui.core.jobs import Job


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
    assert re.search(r"<h1[^>]*>Hello ComposeUI</h1>", page)
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
    rows.table.headers = [hostile]
    rows.table.rows = [[hostile]]

    field = _part(main_view.form.name, "field")
    label, table = rows.note.renderer, rows.table.renderer
    assert isinstance(label, WebLabelRenderer)
    assert isinstance(table, WebTableRenderer)
    for fragment in (field.to_html(), label.to_html(), table.to_html()):
        assert "<script>" not in fragment
    # escaped, not dropped: the browser shows exactly the view's text
    assert _element(field.to_html(), field.widget_id).attributes["value"] == hostile
    assert _element(label.to_html(), label.widget_id).text == hostile
    assert _element(table.to_html(), table.widget_id).text == hostile * 2


def test_markdown_is_shown_as_html_its_own_markup_escaped() -> None:
    main_view = HelpMainView()
    main_view.render(RendererType.WEB)
    renderer = main_view.help.renderer
    assert isinstance(renderer, WebMarkdownRenderer)
    element = _element(renderer.to_html(), renderer.widget_id)
    assert (element.tag, element.attributes["class"]) == ("div", "cui-markdown")
    assert [tag for tag, _ in element.descendants] == ["h1", "ul", "li", "li"]
    assert element.text == "Help\n\nOpen a study\nRun it\n\n"

    with collect_dirty() as dirty:
        main_view.help.text = (
            "## Results\n\n<script>alert(1)</script>\n\n"
            "[the report](https://example.com/report) [no](javascript:alert(1))"
        )
        element = _swapped(render_dirty(dirty), renderer.widget_id)
    assert [(tag, attributes) for tag, attributes in element.descendants if tag != "p"] == [
        ("h2", {}),
        ("a", {"href": "https://example.com/report"}),
    ]
    # shown as text, not run: the browser shows the tag the text has
    assert "<script>alert(1)</script>" in element.text
    assert "<script>" not in renderer.to_html()


@pytest.fixture
def help_views() -> list[HelpMainView]:
    """Each session's main view, kept by `help_client`'s app."""
    return []


@pytest.fixture
def help_client(help_views: list[HelpMainView]) -> Iterator[TestClient]:
    class HelpApp(WebApplication[HelpMainView]):
        def __init__(self) -> None:
            super().__init__(build_main_view=HelpMainView)

        def setup_session(self, main_view: HelpMainView) -> None:
            main_view.status_bar.timeout = 0
            help_views.append(main_view)

    with TestClient(HelpApp().create_starlette_app()) as client:
        yield client


def test_a_pick_file_action_uploads_the_file_and_hands_it_over(
    help_views: list[HelpMainView], help_client: TestClient
) -> None:
    page = help_client.get("/").text
    (main_view,) = help_views
    action = main_view.help_menu.open_help
    action_id = _widget_id(action.renderer)
    (picker,) = [a for tag, a in _element(page, action_id).descendants if tag == "input"]
    assert picker["type"] == "file"
    assert picker["accept"] == ".md,.markdown"
    assert picker["hx-post"] == f"/widget/{action_id}/file"
    picked: list[tuple[Path, bool]] = []
    action.file_picked.connect(lambda path: picked.append((path, path.is_file())))
    help_id = _widget_id(main_view.help.renderer)

    response = help_client.post(
        f"/widget/{action_id}/file", files={"file": ("notes.md", b"# Notes", "text/markdown")}
    )
    assert response.status_code == 200
    assert _swapped(response.text, help_id).text == "Notes\n"
    assert main_view.help.text == "# Notes"
    # a copy under its name while the callbacks run, gone after
    ((path, was_there),) = picked
    assert (path.name, was_there) == ("notes.md", True)
    assert not path.exists()

    # refused: another type, or no file at all
    response = help_client.post(
        f"/widget/{action_id}/file", files={"file": ("notes.txt", b"plain", "text/plain")}
    )
    status = _swapped(response.text, _widget_id(main_view.status_bar.renderer))
    assert status.text == "Can't open 'notes.txt': expected a .md or .markdown file."
    assert main_view.help.text == "# Notes"
    assert help_client.post(f"/widget/{action_id}/file").status_code == 400
    # another action takes no file, and an unknown widget is none of the session's
    open_id = _widget_id(main_view.file_menu.open_file.renderer)
    files = {"file": ("notes.md", b"# Other", "text/markdown")}
    assert help_client.post(f"/widget/{open_id}/file", files=files).status_code == 400
    assert help_client.post("/widget/cui-0/file", files=files).status_code == 404
    assert len(picked) == 1


def test_a_changed_field_inside_a_changed_group_is_swapped_once(
    pipe_main_view: PipeMainView,
) -> None:
    main_pipe = pipe_main_view.pages.inputs.pipe_form.main_pipe
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
    app_title = "Rows"
    extension = ".rows"

    name: _NameRowView = Factory(_NameRowView)
    length: LabelRowFloatInputView = Factory(LabelRowFloatInputView)
    note: LabelView = Factory(LabelView)
    form_log: LogView = Factory(LogView)
    shape: _ShapeRowView = Factory(_ShapeRowView)
    table: TableView = Factory(TableView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
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
    # keyed by the enum members' names, which no language changes
    assert [radio["value"] for radio in radios] == ["CASUAL", "FORMAL"]
    # one radio set per group: named after the group's own id
    assert {radio["name"] for radio in radios} == {style_id}
    assert _selected(style) == ["CASUAL"]
    colour = _element(page, _field_id(main_view.form.colour))
    options = [attributes["value"] for tag, attributes in colour.descendants if tag == "option"]
    assert options == ["", "RED", "GREEN", "BLUE"]
    assert _selected(colour) == [""]  # nothing chosen yet: the empty choice


def test_choosing_a_style_regreets_without_swapping_the_radio_group(
    main_view: HelloMainView, client: TestClient
) -> None:
    style_id = _field_id(main_view.form.style)
    _type_name(client, main_view, "Bob")

    body = client.post(f"/widget/{style_id}", data={style_id: "FORMAL", "event": "change"}).text

    assert main_view.form.style.value is GreetingStyle.FORMAL
    assert _swapped(body, _widget_id(main_view.status_bar.renderer)).text == "Good day, Bob."
    assert _find(body, style_id) is None


def test_choosing_a_colour_updates_the_summary(
    main_view: HelloMainView, client: TestClient
) -> None:
    colour_id = _field_id(main_view.form.colour)
    summary_id = _widget_id(main_view.summary.renderer)

    body = client.post(f"/widget/{colour_id}", data={colour_id: "BLUE", "event": "change"}).text

    assert main_view.form.colour.value is Colour.BLUE
    assert _swapped(body, summary_id).text == "Nobody hasn't said how old they are and likes blue."
    assert _find(body, colour_id) is None

    # the empty choice clears the colour again
    body = client.post(f"/widget/{colour_id}", data={colour_id: "", "event": "change"}).text

    assert main_view.form.colour.value is None
    assert _swapped(body, summary_id).text == "Nobody hasn't said how old they are."


def test_an_unknown_choice_clears_the_value_instead_of_failing(
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
        client.post(f"/widget/{style_id}", data={style_id: "FORMAL", "event": "change"})

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
    assert [radio.get("value") for radio in radios] == ["CASUAL"]
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

    handle_event(field, "change", {field.widget_id: "SQUARE"})

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
    name = pipe_main_view.pages.inputs.pipe_form.name
    name_id = _field_id(name)
    pipe_client.post(f"/widget/{name_id}", data={"value": "Tee", "event": "input"})

    body = pipe_client.post(f"/widget/{name_id}", data={"value": "", "event": "input"}).text

    assert "A name is mandatory" in body
    assert f'id="{_widget_id(_part(name, "log"))}" hx-swap-oob="true"' in body


def test_the_checkbox_is_named_by_its_text_and_its_group_by_the_row_label(
    pipe_main_view: PipeMainView, pipe_client: TestClient
) -> None:
    insulated = pipe_main_view.pages.inputs.pipe_form.insulated
    label_id, field_id = _widget_id(_part(insulated, "label")), _field_id(insulated)

    page = pipe_client.get("/").text

    field = _element(page, field_id)
    assert field.attributes["role"] == "group"
    assert field.attributes["aria-labelledby"] == label_id
    assert field.attributes["aria-describedby"] == _widget_id(_part(insulated, "log"))
    # a `<div>` isn't labelable: `for=` would point at nothing
    assert "for" not in _element(page, label_id).attributes
    (box,) = [attributes for tag, attributes in field.descendants if tag == "input"]
    assert box["type"] == "checkbox"
    assert "checked" not in box
    assert field.text == "Insulated pipe"  # inside the box's own `<label>`


def test_toggling_the_checkbox_enables_its_row_without_swapping_the_box(
    pipe_main_view: PipeMainView, pipe_client: TestClient
) -> None:
    form = pipe_main_view.pages.inputs.pipe_form
    field_id = _field_id(form.insulated)
    thickness_id = _field_id(form.insulation_thickness)
    toggled: list[bool] = []
    form.insulated.toggled.connect(toggled.append)

    def toggle(**checked: str) -> str:
        return pipe_client.post(f"/widget/{field_id}", data={"event": "change", **checked}).text

    body = toggle(checked="on")

    assert form.insulated.is_checked is True
    assert "disabled" not in _swapped(body, thickness_id).attributes
    assert _find(body, field_id) is None

    toggle(checked="on")  # posted twice (e.g. a retry): no second toggle
    body = toggle()  # an unchecked box posts no value

    assert form.insulated.is_checked is False
    assert "disabled" in _swapped(body, thickness_id).attributes
    assert toggled == [True, False]


def test_checking_the_box_on_the_server_swaps_it_checked(pipe_main_view: PipeMainView) -> None:
    insulated = pipe_main_view.pages.inputs.pipe_form.insulated
    field = _part(insulated, "field")

    with collect_dirty() as dirty:
        insulated.is_checked = True

    assert field.widget_id in dirty
    assert _selected(_swapped(render_dirty(dirty), field.widget_id)) == ["on"]


def test_finishing_a_dimension_edit_swaps_the_summary_table(
    pipe_main_view: PipeMainView, pipe_client: TestClient
) -> None:
    radius_id = _field_id(pipe_main_view.pages.inputs.pipe_form.main_pipe.radius)
    summary_id = _widget_id(pipe_main_view.pages.results.summary.renderer)

    body = pipe_client.post(f"/widget/{radius_id}", data={"value": "35", "event": "change"}).text

    summary = _swapped(body, summary_id)
    assert [tag for tag, _ in summary.descendants].count("th") == 4
    assert "Main Pipe352020" in summary.text  # the main pipe's row, cell after cell


def test_disabling_a_group_disables_its_whole_fieldset(pipe_main_view: PipeMainView) -> None:
    main_pipe = pipe_main_view.pages.inputs.pipe_form.main_pipe

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


class _Signatures(SqliteTable):
    create = "CREATE TABLE signature(id INTEGER PRIMARY KEY, name TEXT NOT NULL);"

    def sign(self, name: str) -> None:
        with self.connection() as db:
            db.execute("INSERT INTO signature(name) VALUES (?)", (name,))

    def names(self) -> list[str]:
        with self.connection() as db:
            return [row["name"] for row in db.execute("SELECT name FROM signature ORDER BY id")]


class _SignedGuestbook(SqliteModel):
    def __init__(self) -> None:
        super().__init__()
        self.signatures = self.add_table(_Signatures)


def test_a_saved_study_brings_its_database_to_another_browser() -> None:
    class GuestbookApp(WebModelApplication[HelloMainView, _SignedGuestbook]):
        def setup_session(self, main_view: HelloMainView) -> None:
            main_view.status_bar.timeout = 0
            views.append(main_view)

    def show_signatures(main_view: HelloMainView, model: _SignedGuestbook) -> None:
        # whatever changes the signatures, an upload included, the summary follows
        def show() -> None:
            main_view.summary.text = ", ".join(model.signatures.names())

        model.signatures.changed.connect(show)

    views: list[HelloMainView] = []
    # nothing but its session keeps a model
    app = GuestbookApp(
        build_main_view=HelloMainView, build_model=_SignedGuestbook, setup_model=show_signatures
    )
    name = app.main_view.form.name

    @app.connect(view=name, signals=[name.editing_finished])
    def sign(*, view: NameRowView, model: _SignedGuestbook) -> None:
        model.signatures.sign(view.text)

    def sign_as(client: TestClient, view: HelloMainView, text: str) -> None:
        field_id = _field_id(view.form.name)
        response = client.post(f"/widget/{field_id}", data={"value": text, "event": "change"})
        assert response.status_code == 200

    web = app.create_starlette_app()
    with TestClient(web) as alice, TestClient(web) as bob:
        alice.get("/")
        bob.get("/")
        alice_view, bob_view = views
        sign_as(alice, alice_view, "Alice")
        sign_as(alice, alice_view, "Ada")
        saved = alice.get("/state")
        assert saved.headers["content-type"] == "application/zip"

        response = bob.post("/state", files={"file": ("study.hello", saved.content)})

        assert response.headers["hx-refresh"] == "true"
        assert bob_view.form.name.text == "Ada"
        assert bob_view.summary.text == "Alice, Ada"
        sign_as(bob, bob_view, "Bob")
        assert bob_view.summary.text == "Alice, Ada, Bob"
        # the views' state alone isn't a study of this app: it would lose the signatures
        views_only = json.dumps(HelloMainView().state_data()).encode()
        response = bob.post("/state", files={"file": ("study.hello", views_only)})
        assert "isn&#x27;t a valid .hello file" in response.text
        sign_as(bob, bob_view, "Eve")
        assert bob_view.summary.text == "Alice, Ada, Bob, Eve"


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


@define_view
class _GreetedMainView(HelloMainView):
    """The hello app, greeting a name of its own command-line option."""

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--greet", metavar="NAME")

    def apply_arguments(self, args: argparse.Namespace) -> None:
        if args.greet is not None:
            self.form.name.text = args.greet


def test_an_app_s_own_options_apply_to_every_new_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    served: list[Starlette] = []
    monkeypatch.setattr("sys.argv", ["webhello", "--greet", "Ada", "--port", "8001"])
    monkeypatch.setattr(
        "composeui.webcore.webapplication.uvicorn.run",
        lambda app, **_: served.append(app),
    )
    views: list[_GreetedMainView] = []

    class GreetedApp(WebApplication[_GreetedMainView]):
        def setup_session(self, main_view: _GreetedMainView) -> None:
            views.append(main_view)

    GreetedApp(build_main_view=_GreetedMainView).run()

    with TestClient(served[0]) as alice, TestClient(served[0]) as bob:
        pages = [alice.get("/").text, bob.get("/").text]
    assert [view.form.name.text for view in views] == ["Ada", "Ada"]
    assert all('value="Ada"' in page for page in pages)


def test_reload_serves_the_app_the_program_builds_again_in_a_new_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    study = PipeMainView()
    study.pages.inputs.pipe_form.name.text = "Main line"
    state_file = tmp_path / "study.pipe"
    study.save_state(state_file)
    served: list[tuple[str, dict[str, Any]]] = []
    # `python -m examples.pipeform --backend web --reload -f study.pipe`, whose app is
    # built inline by `main()`, which also takes `--backend` out of the command line
    monkeypatch.setitem(sys.modules, "__main__", types.ModuleType("__main__"))
    monkeypatch.setattr(sys.modules["__main__"], "__spec__", find_spec("examples.pipeform"))
    monkeypatch.setattr(
        "sys.argv", ["pipeform", "--backend", "web", "--reload", "-f", str(state_file)]
    )
    monkeypatch.setattr(
        "composeui.webcore.webapplication.uvicorn.run",
        lambda app, **kwargs: served.append((app, kwargs)),
    )
    # restores the variable `run` sets for the reloaded process
    monkeypatch.setenv("COMPOSEUI_WEB_ENTRY", "")

    pipeform.main()

    ((import_string, options),) = served
    assert options["reload"] is True
    assert options["factory"] is True
    # what uvicorn's reloaded process does with it, without spawning one
    factory = import_from_string(import_string)
    with TestClient(factory()) as client:
        page = client.get("/").text
    assert "<title>Pipe Form</title>" in page
    assert 'value="Main line"' in page


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
        alice.post(f"/widget/{style_id}", data={style_id: "FORMAL", "event": "change"})
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


def test_the_file_menu_is_buttons_in_the_header(
    main_view: HelloMainView, client: TestClient
) -> None:
    menu = main_view.file_menu
    assert not menu.is_visible  # "popped up" in Qt terms; ignored, the buttons always show

    page = client.get("/").text

    header = page[page.index("<header") : page.index("</header>")]
    assert _element(header, _widget_id(menu.renderer)).tag == "div"
    new = _element(header, _action_id(menu.new))
    assert new.attributes["hx-post"] == f"/widget/{_action_id(menu.new)}"
    open_file = _element(header, _action_id(menu.open_file))
    assert ("input", "file") in [(tag, attrs.get("type")) for tag, attrs in open_file.descendants]
    save = _element(header, _action_id(menu.save))
    assert (save.tag, save.attributes["href"]) == ("a", f"/state?trigger={_action_id(menu.save)}")
    assert "download" in save.attributes
    # nothing left for a dropdown: the separator only set Exit apart
    menu_html = header[header.index(f'id="{_widget_id(menu.renderer)}"') :]
    assert "<ul" not in menu_html[: menu_html.index(f'id="{_action_id(menu.save)}"')]
    assert 'role="separator"' not in header


def test_an_app_without_studies_has_no_file_buttons() -> None:
    views: list[HelpViewerMainView] = []

    class ViewerApp(WebApplication[HelpViewerMainView]):
        def setup_session(self, main_view: HelpViewerMainView) -> None:
            views.append(main_view)

    app = ViewerApp(build_main_view=HelpViewerMainView)
    with TestClient(app.create_starlette_app()) as client:
        page = client.get("/").text
    header = page[page.index("<header") : page.index("</header>")]
    assert "Open Help" in header
    assert not any(text in header for text in (">New<", ">Open<", ">Save<", "/state"))
    (main_view,) = views
    assert main_view.file_menu.renderer is None  # never rendered


def test_another_menu_is_a_dropdown_under_its_title() -> None:
    @define_view
    class ViewMenu(Menu):
        zoom_in: ActionView = Factory(lambda: ActionView(text="Zoom in"))
        separator: SeparatorAction = Factory(SeparatorAction)
        zoom_out: ActionView = Factory(lambda: ActionView(text="Zoom out"))

    menu = ViewMenu(title="View")
    menu.render(RendererType.WEB)
    assert isinstance(menu.renderer, WebRenderer)

    markup = menu.renderer.to_html()

    assert re.search(r'role="button"[^>]*aria-haspopup="menu">View<', markup)
    dropdown = markup[markup.index("<ul") : markup.index("</ul>")]
    for action in (menu.zoom_in, menu.zoom_out):
        assert _element(dropdown, _action_id(action)).tag == "li"
    assert 'role="separator"' in dropdown


@pytest.mark.parametrize(("action", "key"), [("new", "N"), ("open_file", "O"), ("save", "S")])
def test_menu_shortcuts_avoid_the_browsers_own(
    main_view: HelloMainView, client: TestClient, action: str, key: str
) -> None:
    """Ctrl+N/O/S belong to the browser (new window, open file, save page)."""
    page = client.get("/").text
    button = _element(page, _action_id(getattr(main_view.file_menu, action)))
    elements = [(button.tag, button.attributes), *button.descendants]

    assert f"(Alt+Shift+{key})" in str(button.attributes.get("title"))
    # what the page's key handler clicks when Alt+Shift+<key> is pressed
    assert f"Key{key}" in [attributes.get("data-shortcut") for _, attributes in elements]
    assert "Ctrl" not in page[page.index("<header") : page.index("</header>")]


@pytest.mark.parametrize("action", ["save_as", "exit_app"])
def test_actions_a_browser_already_has_are_left_out(
    main_view: HelloMainView, client: TestClient, action: str
) -> None:
    """Save As downloads just like Save; a web page is left by closing its tab."""
    page = client.get("/").text
    left_out = _element(page, _action_id(getattr(main_view.file_menu, action)))

    # kept as a hidden placeholder, so a later change to the action still has a target
    assert "hidden" in left_out.attributes
    assert left_out.descendants == []
    assert "data-shortcut" not in left_out.attributes


def test_save_as_alone_in_its_menu_is_its_download_button() -> None:
    @define_view
    class ExportMenu(Menu):
        save_as: SaveAsAction = Factory(SaveAsAction)

    export = ExportMenu(title="Export")
    export.render(RendererType.WEB)
    assert isinstance(export.renderer, WebRenderer)

    button = _element(export.renderer.to_html(), _action_id(export.save_as))

    assert button.tag == "a"
    assert "download" in button.attributes
    # no Alt+Shift+S: Save's, wherever Save is
    assert "data-shortcut" not in button.attributes


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


def test_the_open_picker_offers_only_the_apps_files(
    main_view: HelloMainView, client: TestClient
) -> None:
    open_file = main_view.file_menu.open_file
    file_inputs = re.compile(r'<input type="file"[^>]*>')

    page = client.get("/").text
    # renamed later: the action's fragment is swapped on its own, and keeps the filter
    open_file.text = "Open study"
    fragment = client.get(f"/widget/{_action_id(open_file)}").text

    assert [re.findall(r'accept="([^"]*)"', tag) for tag in file_inputs.findall(page)] == [
        [".hello"]
    ]
    assert "Open study" in fragment
    assert 'accept=".hello"' in "".join(file_inputs.findall(fragment))


def test_triggering_a_checkable_action_toggles_its_check_mark() -> None:
    action = ActionView(text="Wrap", is_checkable=True)
    action.render(RendererType.WEB)
    renderer = action.renderer
    assert isinstance(renderer, WebRenderer)
    renderer.to_html()  # on the page, as in its menu

    # the item comes back as an out-of-band fragment, with its check mark toggled
    assert ">✓ Wrap</span>" in handle_event(renderer, "triggered", {})
    assert ">Wrap</span>" in handle_event(renderer, "triggered", {})


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
        form = view.pages.inputs.pipe_form
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
        assert ">Main Pipe</legend>" in page
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
        body = post(radius_id, {"value": "5", "event": "change"})
        log = _swapped(body, form_log_id)
        assert "hidden" not in log.attributes
        assert "incident radius" in log.text
        # it marks the two radii it is about through their rows' logs, which the page
        # marks the fields from: the field being typed in is never swapped
        _assert_radii_marked(body, form, marked=True)
        # and a page served meanwhile shows the field invalid from the start
        field_html = _part(form.main_pipe.radius, "field").to_html()
        assert _element(field_html, radius_id).attributes["aria-invalid"] == "true"
        # ...until it is fixed
        post(radius_id, {"value": "60", "event": "input"})
        body = post(radius_id, {"value": "60", "event": "change"})
        assert "hidden" in _swapped(body, form_log_id).attributes
        _assert_radii_marked(body, form, marked=False)
        assert form.log_view.log_message == ""

        # saved, then opened in another browser's session
        saved = alice.get("/state").content
        bob.get("/")
        reopened = pipe_views[1].pages.inputs.pipe_form
        assert (
            bob.post("/state", files={"file": ("tee.pipe", saved)}).headers["hx-refresh"] == "true"
        )
        _assert_shows_the_tee_study(bob.get("/").text, reopened)


def _assert_radii_marked(body: str, form: Any, *, marked: bool) -> None:
    """Check `body` swaps both radii's logs, flagged by a failing form check or not."""
    for row in (form.main_pipe.radius, form.incident_pipe.radius):
        log = _swapped(body, _widget_id(_part(row, "log")))
        assert ("data-form-error" in log.attributes) is marked


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


def test_the_page_names_each_static_file_by_its_content(client: TestClient) -> None:
    """A new stylesheet or script has a new address: a browser can't keep an older copy."""
    page = client.get("/").text

    addresses = re.findall(r'(?:src|href)="(/static/[^"]*)"', page)

    assert sorted(address.split("?")[0] for address in addresses) == [
        "/static/app.css",
        "/static/htmx.min.js",
    ]
    for address in addresses:
        body = client.get(address).content
        assert address.endswith(f"?v={hashlib.sha256(body).hexdigest()[:16]}")


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
    for variant in ButtonVariant:  # each button colour
        button = ButtonView(text="x", variant=variant)
        button.render(RendererType.WEB)
        assert isinstance(button.renderer, WebRenderer)
        markup.append(button.renderer.to_html())
    chart = ChartView(title="x")
    chart.render(RendererType.WEB)
    assert isinstance(chart.renderer, WebRenderer)
    markup.append(chart.renderer.to_html())
    main_view.file_menu.new.is_enabled = False  # a disabled menu item
    markup.append(client.get("/").text)
    classes = {
        name
        for page in markup
        for value in re.findall(r'class="([^"]*)"', page)
        for name in value.split()
    }
    stylesheet = client.get("/static/app.css").text

    def selector(name: str) -> str:
        # all but letters, digits, `_` and `-` is escaped in its selector, e.g.
        # `.sm\:w-auto`, `.text-base-content\/50`, `.has-\[\>\[hidden\]\]\:hidden`
        return "." + re.escape(re.sub(r"([^\w-])", r"\\\1", name))

    missing = sorted(
        name for name in classes if not re.search(rf"{selector(name)}(?![\w-])", stylesheet)
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


@pytest.fixture
def pages_views() -> list[PagesMainView]:
    """Each session's main view, kept by `pages_client`'s app."""
    return []


@pytest.fixture
def pages_client(pages_views: list[PagesMainView]) -> Iterator[TestClient]:
    class PagesApp(WebApplication[PagesMainView]):
        def __init__(self) -> None:
            super().__init__(build_main_view=PagesMainView)

        def setup_session(self, main_view: PagesMainView) -> None:
            pages_views.append(main_view)

    with TestClient(PagesApp().create_starlette_app()) as client:
        yield client


def _shown_routes(page: str) -> list[str]:
    return re.findall(r'<div data-route="([^"]*)">', page)


def test_each_page_has_its_own_address(
    pages_views: list[PagesMainView], pages_client: TestClient
) -> None:
    home = pages_client.get("/", follow_redirects=False)
    assert home.status_code == 303
    assert home.headers["location"] == "/inputs"

    page = pages_client.get("/results").text
    (main_view,) = pages_views
    assert main_view.router.current_route == "results"
    assert _shown_routes(page) == ["results"]
    results_link = _element(page, _widget_id(main_view.router.results.action.renderer))
    inputs_link = _element(page, _widget_id(main_view.router.inputs.action.renderer))
    assert (results_link.text, results_link.attributes["href"]) == ("Results", "/results")
    assert "aria-current" in results_link.attributes
    assert "aria-current" not in inputs_link.attributes

    # no page there, e.g. the browser's own `/favicon.ico`: not found, and no navigation
    for address in ("/settings", "/favicon.ico"):
        assert pages_client.get(address).status_code == 404
    assert main_view.router.current_route == "results"


@pytest.mark.parametrize("reserved", sorted(RESERVED_ROUTES))
def test_a_page_on_an_address_the_backend_uses_stops_the_app_before_serving(
    reserved: str,
) -> None:
    @define_view
    class Page(PageView):
        route = reserved

    @define_view
    class Pages(Router):
        page: Page = Factory(Page)

    @define_view
    class ReservedMainView(MainView):
        app_title = "Reserved"
        extension = ".reserved"

        pages: Pages = Factory(Pages)

    message = re.escape(f"the routes [{reserved!r}]: rename them")
    with pytest.raises(ValueError, match=message):
        WebApplication(build_main_view=ReservedMainView).create_starlette_app()
    with pytest.raises(ValueError, match=message):  # rendered without the app
        ReservedMainView().render(RendererType.WEB)


def test_a_toolbar_link_shows_its_page_and_puts_its_address_in_the_history(
    pages_views: list[PagesMainView], pages_client: TestClient
) -> None:
    pages_client.get("/")
    (main_view,) = pages_views
    results = _widget_id(main_view.router.results.action.renderer)

    response = pages_client.post(f"/widget/{results}", data={"event": "triggered"})
    assert main_view.router.current_route == "results"
    assert response.headers["HX-Push-Url"] == "/results"
    router = _swapped(response.text, _widget_id(main_view.router.renderer))
    shown = [
        attributes["data-route"]
        for tag, attributes in router.descendants
        if tag == "div" and "data-route" in attributes and "hidden" not in attributes
    ]
    assert shown == ["results"]
    assert "aria-current" in _swapped(response.text, results).attributes
    inputs = _swapped(response.text, _widget_id(main_view.router.inputs.action.renderer))
    assert "aria-current" not in inputs.attributes

    # the shown page's link again: no navigation, so nothing new in the history
    again = pages_client.post(f"/widget/{results}", data={"event": "triggered"})
    assert "HX-Push-Url" not in again.headers


@pytest.fixture
def toolbar_views() -> list[ToolBarMainView]:
    """Each session's main view, kept by `toolbar_client`'s app."""
    return []


@pytest.fixture
def toolbar_client(toolbar_views: list[ToolBarMainView]) -> Iterator[TestClient]:
    class ToolBarApp(WebApplication[ToolBarMainView]):
        def __init__(self) -> None:
            super().__init__(build_main_view=ToolBarMainView)

        def setup_session(self, main_view: ToolBarMainView) -> None:
            toolbar_views.append(main_view)

    with TestClient(ToolBarApp().create_starlette_app()) as client:
        yield client


def test_a_toolbar_shows_its_actions_as_header_buttons(
    toolbar_views: list[ToolBarMainView], toolbar_client: TestClient
) -> None:
    page = toolbar_client.get("/").text
    (main_view,) = toolbar_views
    toolbar_view = main_view.toolbar
    toolbar_id = _widget_id(toolbar_view.renderer)
    toolbar = _element(page, toolbar_id)
    assert (toolbar.attributes["role"], toolbar.attributes["aria-label"]) == ("toolbar", "Edit")
    assert [
        attributes.get("role") or tag
        for tag, attributes in toolbar.descendants
        if tag in {"label", "button", "div"}
    ] == ["label", "separator", "button", "button"]
    # Open uploads a study, as the File menu's does
    open_file = _element(page, _action_id(toolbar_view.open_file))
    file_input = next(a for tag, a in open_file.descendants if tag == "input")
    assert file_input["accept"] == ".toolbar"
    run = _element(page, _action_id(toolbar_view.run))
    assert (run.text, run.attributes["title"]) == ("Run", "Run (Alt+Shift+R)")

    response = toolbar_client.post(
        f"/widget/{_action_id(toolbar_view.run)}", data={"event": "triggered"}
    )
    total = _swapped(response.text, _widget_id(main_view.router.results.total.renderer))
    assert total.text == "Ran"
    wrap_id = _action_id(toolbar_view.wrap)
    response = toolbar_client.post(f"/widget/{wrap_id}", data={"event": "triggered"})
    wrap = _swapped(response.text, wrap_id)
    assert wrap.attributes["aria-pressed"] == "true"
    assert "btn-active" in (wrap.attributes["class"] or "").split()

    with collect_dirty() as dirty:
        toolbar_view.is_enabled = False
        swapped = _swapped(render_dirty(dirty), toolbar_id)
    assert all(
        "disabled" in attributes for tag, attributes in swapped.descendants if tag == "button"
    )
    refused = toolbar_client.post(
        f"/widget/{_action_id(toolbar_view.run)}", data={"event": "triggered"}
    )
    assert refused.status_code == 400


def _icon_url(element: _Element) -> str:
    """Get the address of an action's icon file, drawn as an SVG mask or an image."""
    for tag, attributes in element.descendants:
        if tag == "img":
            return attributes["src"] or ""
        match = re.search(r"url\('([^']*)'\)", attributes.get("style") or "")
        if match is not None:
            return match.group(1)
    msg = f"no icon in {element}"
    raise AssertionError(msg)


def test_an_icon_is_served_from_its_content_and_only_when_a_view_names_it(
    toolbar_views: list[ToolBarMainView], toolbar_client: TestClient, tmp_path: Path
) -> None:
    toolbar_client.get("/")
    (main_view,) = toolbar_views
    run_svg = tmp_path / "run.svg"
    run_svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"><circle r="4"/></svg>')
    wrap_png = tmp_path / "wrap.png"
    wrap_png.write_bytes(b"\x89PNG\r\n\x1a\n")
    secret = tmp_path / "secret.txt"
    secret.write_text("not an image")
    main_view.toolbar.run.icon = str(run_svg)
    main_view.toolbar.wrap.icon = str(wrap_png)
    main_view.router.results.icon = str(secret)

    page = toolbar_client.get("/").text
    run_url = _icon_url(_element(page, _action_id(main_view.toolbar.run)))
    wrap_url = _icon_url(_element(page, _action_id(main_view.toolbar.wrap)))
    for url, path, media_type in (
        (run_url, run_svg, "image/svg+xml"),
        (wrap_url, wrap_png, "image/png"),
    ):
        response = toolbar_client.get(url)
        assert response.status_code == 200
        assert response.content == path.read_bytes()
        assert response.headers["content-type"] == media_type
        assert "immutable" in response.headers["cache-control"]
    # the tooltip names a button the phone shows as its icon only
    assert _element(page, _action_id(main_view.toolbar.wrap)).attributes["title"] == "Wrap"
    results_tab = _element(page, _action_id(main_view.router.results.action))
    assert not any(tag in {"img", "span"} for tag, _ in results_tab.descendants)

    # another content: another address, and the old one is gone
    run_svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"><rect width="4"/></svg>')
    os.utime(run_svg, ns=(0, run_svg.stat().st_mtime_ns + 1))
    with collect_dirty() as dirty:
        main_view.toolbar.run.text = "Go"
        swapped = _swapped(render_dirty(dirty), _action_id(main_view.toolbar.run))
    assert _icon_url(swapped) != run_url
    assert toolbar_client.get(run_url).status_code == 404


def test_the_progress_bar_swaps_in_its_count_and_its_unknown_length(
    pages_views: list[PagesMainView], pages_client: TestClient
) -> None:
    page = pages_client.get("/results").text
    (main_view,) = pages_views
    progress = main_view.router.results.progress
    bar_id = _widget_id(progress.renderer)
    bar = _element(page, bar_id)
    assert (bar.tag, bar.attributes["value"], bar.attributes["max"]) == ("progress", "0", "100")
    submit = main_view.router.inputs.submit

    def advance() -> None:
        progress.value = 250

    submit.clicked.connect(advance)
    response = pages_client.post(f"/widget/{_widget_id(submit.renderer)}", data={"event": "click"})
    bar = _swapped(response.text, bar_id)
    assert (bar.attributes["value"], bar.attributes["max"]) == ("100", "100")  # clamped

    progress.maximum = None
    bar = _element(pages_client.get(f"/widget/{bar_id}").text, bar_id)
    # no value: the browser's own bar for a task of unknown length
    assert "value" not in bar.attributes
    assert "max" not in bar.attributes


def test_the_page_asks_for_what_jobs_change_while_they_run(
    pages_views: list[PagesMainView], pages_client: TestClient
) -> None:
    page = pages_client.get("/results").text
    assert "hx-get" not in _element(page, "cui-jobs").attributes  # no job yet
    (main_view,) = pages_views
    results, submit = main_view.router.results, main_view.router.inputs.submit
    total_id = _widget_id(results.total.renderer)
    release = threading.Event()

    def work(_job: Job[int]) -> int:
        release.wait(10)
        return 7

    def show(total: int) -> None:
        results.total.text = f"Total: {total}"

    def start() -> None:
        main_view.jobs.start(work).finished.connect(show)

    submit.clicked.connect(start)
    response = pages_client.post(f"/widget/{_widget_id(submit.renderer)}", data={"event": "click"})
    poller = _swapped(response.text, "cui-jobs").attributes
    assert poller["hx-get"] == "/jobs"
    assert poller["hx-trigger"] == f"load delay:{JOBS_POLL_MS}ms"
    assert poller["hx-swap"] == "outerHTML"
    assert "hx-get" in _element(pages_client.get("/jobs").text, "cui-jobs").attributes

    release.set()
    deadline = time.monotonic() + 10
    while main_view.jobs.is_running and time.monotonic() < deadline:
        time.sleep(0.01)
    polled = pages_client.get("/jobs").text

    assert "hx-get" not in _element(polled, "cui-jobs").attributes  # over: done asking
    assert _swapped(polled, total_id).text == "Total: 7"


# handed over by the view it changes, or by the main view, as an app does
@pytest.mark.parametrize("through_main_view", [False, True])
def test_what_a_thread_changes_comes_with_the_session_s_next_response(
    pages_views: list[PagesMainView], pages_client: TestClient, *, through_main_view: bool
) -> None:
    pages_client.get("/results")
    (main_view,) = pages_views
    results, submit = main_view.router.results, main_view.router.inputs.submit
    bar_id, total_id = _widget_id(results.progress.renderer), _widget_id(results.total.renderer)

    def work(value: int) -> None:
        def advance() -> None:
            results.progress.value = value
            results.total.text = f"Total: {value}"

        renderer = (main_view if through_main_view else results.progress).renderer
        assert renderer is not None
        worker = threading.Thread(target=renderer.call_on_main_thread, args=(advance,))
        worker.start()
        worker.join()

    work(40)
    fetched = pages_client.get(f"/widget/{bar_id}").text
    assert _element(fetched, bar_id).attributes["value"] == "40"
    assert "hx-swap-oob" not in _element(fetched, bar_id).attributes  # the fetch's own swap
    assert _swapped(fetched, total_id).text == "Total: 40"
    # sent once
    assert _find(pages_client.get(f"/widget/{bar_id}").text, total_id) is None

    work(50)
    response = pages_client.post(f"/widget/{_widget_id(submit.renderer)}", data={"event": "click"})
    assert _swapped(response.text, bar_id).attributes["value"] == "50"
    # changed by both, swapped once, as the click left it
    assert response.text.count(f'id="{total_id}"') == 1
    assert _swapped(response.text, total_id).text == "Submitted: "

    work(60)
    assert _element(pages_client.get("/results").text, total_id).text == "Total: 60"
    assert _find(pages_client.get(f"/widget/{bar_id}").text, total_id) is None  # shown already


def test_clicking_the_button_swaps_in_what_its_view_changed(
    pages_views: list[PagesMainView], pages_client: TestClient
) -> None:
    page = pages_client.get("/inputs").text
    (main_view,) = pages_views
    inputs = main_view.router.inputs
    button_id = _widget_id(inputs.submit.renderer)
    button = _element(page, button_id)
    assert (button.tag, button.attributes["type"], button.text) == ("button", "button", "Submit")
    assert "btn-primary" in button.attributes["class"].split()
    inputs.name.text = "<Ada>"

    response = pages_client.post(f"/widget/{button_id}", data={"event": "click"})

    assert response.status_code == 200
    total = _swapped(response.text, _widget_id(main_view.router.results.total.renderer))
    assert total.text == "Submitted: <Ada>"  # escaped in the markup, the text once parsed
    assert _find(response.text, button_id) is None  # the clicked button isn't swapped back

    with collect_dirty() as dirty:
        inputs.submit.variant = ButtonVariant.DANGER
        swapped = _swapped(render_dirty(dirty), button_id)
    assert "btn-error" in swapped.attributes["class"].split()

    inputs.submit.is_enabled = False
    refused = pages_client.post(f"/widget/{button_id}", data={"event": "click"})
    assert refused.status_code == 400
    main_view.router.results.total.text = ""
    pages_client.post(f"/widget/{button_id}", data={"event": "click"})
    assert main_view.router.results.total.text == ""


@define_view
class _StatePage(InputsPage):
    route = "state"


@define_view
class _StateRouter(Router):
    state: _StatePage = Factory(_StatePage)


@define_view
class _StateMainView(MainView):
    app_title = "State"
    extension = ".state"

    router: _StateRouter = Factory(_StateRouter)


def test_a_route_cannot_take_an_address_of_the_backend() -> None:
    with pytest.raises(ValueError, match="'state'"):
        _StateMainView().render(RendererType.WEB)


@pytest.fixture
def dialog_views() -> list[DialogsMainView]:
    """Each session's main view, kept by `dialog_client`'s app."""
    return []


@pytest.fixture
def dialog_client(dialog_views: list[DialogsMainView]) -> Iterator[TestClient]:
    class DialogsApp(WebApplication[DialogsMainView]):
        def __init__(self) -> None:
            super().__init__(build_main_view=DialogsMainView)

        def setup_session(self, main_view: DialogsMainView) -> None:
            dialog_views.append(main_view)

    with TestClient(DialogsApp().create_starlette_app()) as client:
        client.get("/")  # starts the session
        yield client


@pytest.fixture
def dialogs_main_view(
    dialog_views: list[DialogsMainView], dialog_client: TestClient
) -> DialogsMainView:
    dialog_client.get("/")  # the client's own session: still the one view built so far
    (main_view,) = dialog_views
    return main_view


def test_an_action_opens_a_dialog_whose_answers_close_it(
    dialogs_main_view: DialogsMainView, dialog_client: TestClient
) -> None:
    dialog_id = _widget_id(dialogs_main_view.confirm_clear.renderer)
    name_id = _widget_id(dialogs_main_view.name.renderer)
    clear_id = _widget_id(dialogs_main_view.edit_menu.clear.renderer)

    def post(widget_id: str, event: str) -> str:
        return dialog_client.post(f"/widget/{widget_id}", data={"event": event}).text

    closed = _element(dialog_client.get("/").text, dialog_id)
    assert closed.tag == "dialog"
    assert "hidden" in closed.attributes

    body = post(clear_id, "triggered")
    dialog = _swapped(body, dialog_id)
    assert "hidden" not in dialog.attributes
    assert dialog.attributes["hx-trigger"] == "cancel"  # Escape
    title_id = dialog.attributes["aria-labelledby"]
    text_id = dialog.attributes["aria-describedby"]
    assert title_id is not None
    assert text_id is not None
    assert _element(body, title_id).text == "Clear the name"
    assert _element(body, text_id).text == "The name will be lost."
    buttons = [
        attributes.get("hx-vals") for tag, attributes in dialog.descendants if tag == "button"
    ]
    assert buttons == ['{"event": "reject"}', '{"event": "accept"}']

    body = post(dialog_id, "dismiss")  # Escape rejects a confirmation
    assert "hidden" in _swapped(body, dialog_id).attributes
    assert _find(body, name_id) is None

    post(clear_id, "triggered")
    body = post(dialog_id, "accept")
    assert "hidden" in _swapped(body, dialog_id).attributes
    assert _swapped(body, name_id).text == ""

    assert post(dialog_id, "accept") == ""  # a second click on the closed dialog


def test_a_disabled_dialog_cannot_be_answered(
    dialogs_main_view: DialogsMainView, dialog_client: TestClient
) -> None:
    dialog = dialogs_main_view.confirm_clear
    dialog_id = _widget_id(dialog.renderer)
    dialog.is_enabled = False
    dialog.text = "<b>busy</b>"
    dialog.open()

    page = dialog_client.get("/").text
    element = _element(page, dialog_id)
    assert "hx-trigger" not in element.attributes
    assert element.attributes["oncancel"] == "event.preventDefault()"
    buttons = [attributes for tag, attributes in element.descendants if tag == "button"]
    assert all("disabled" in attributes for attributes in buttons)
    assert "<b>busy</b>" in element.text
    assert all(tag != "b" for tag, _ in element.descendants)

    dialog_client.post(f"/widget/{dialog_id}", data={"event": "accept"})
    assert dialog.is_visible
    assert dialogs_main_view.name.text == "Ada"


@define_view
class _NotePage(PageView):
    route = "note"

    note: DialogView = Factory(DialogView)


@define_view
class _NotePages(Router):
    first: InputsPage = Factory(InputsPage)
    note: _NotePage = Factory(_NotePage)


@define_view
class _NoteMainView(MainView):
    app_title = "Notes"
    extension = ".notes"

    pages: _NotePages = Factory(_NotePages)


@pytest.fixture
def notes() -> Iterator[tuple[TestClient, _NoteMainView]]:
    """Serve an app with a dialog on its second page; yield a client and its main view."""
    views: list[_NoteMainView] = []

    class NotesApp(WebApplication[_NoteMainView]):
        def __init__(self) -> None:
            super().__init__(build_main_view=_NoteMainView)

        def setup_session(self, main_view: _NoteMainView) -> None:
            views.append(main_view)

    with TestClient(NotesApp().create_starlette_app()) as client:
        client.get("/")
        (main_view,) = views
        yield client, main_view


def _disable_on_submit(main_view: _NoteMainView, container: View) -> str:
    """Return the id of the first page's button, whose click disables `container`."""

    def disable() -> None:
        container.is_enabled = False

    main_view.pages.first.submit.clicked.connect(disable)
    return _widget_id(main_view.pages.first.submit.renderer)


def test_a_page_dialog_shows_outside_the_pages_hidden_slots(
    notes: tuple[TestClient, _NoteMainView],
) -> None:
    """A page that isn't shown hides its content: its dialog would never show."""
    client, main_view = notes
    main_view.pages.note.note.open()
    page = client.get("/inputs").text

    dialog_id = _widget_id(main_view.pages.note.note.renderer)
    assert "hidden" not in _element(page, dialog_id).attributes
    router = _element(page, _widget_id(main_view.pages.renderer))
    assert all(attributes.get("id") != dialog_id for _, attributes in router.descendants)


@pytest.mark.parametrize("disabled", ["page", "router"])
def test_disabling_a_page_disables_its_dialog_drawn_apart_from_it(
    notes: tuple[TestClient, _NoteMainView], disabled: str
) -> None:
    client, main_view = notes
    dialog = main_view.pages.note.note
    dialog.open()
    container = main_view.pages.note if disabled == "page" else main_view.pages
    submit_id = _disable_on_submit(main_view, container)
    body = client.post(f"/widget/{submit_id}", data={"event": "click"}).text

    dialog_id = _widget_id(dialog.renderer)
    swapped = _swapped(body, dialog_id)
    assert "hx-trigger" not in swapped.attributes  # Escape doesn't dismiss it
    buttons = [attributes for tag, attributes in swapped.descendants if tag == "button"]
    assert all("disabled" in attributes for attributes in buttons)
    # a stale page's answer is ignored, as a disabled dialog's own
    client.post(f"/widget/{dialog_id}", data={"event": "accept"})
    assert dialog.is_visible


def test_disabling_a_router_disables_its_pages_but_not_their_links(
    notes: tuple[TestClient, _NoteMainView],
) -> None:
    client, main_view = notes
    submit_id = _disable_on_submit(main_view, main_view.pages)
    body = client.post(f"/widget/{submit_id}", data={"event": "click"}).text

    router = _swapped(body, _widget_id(main_view.pages.renderer))
    (submit,) = [
        attributes for _, attributes in router.descendants if attributes.get("id") == submit_id
    ]
    assert "disabled" in submit
    assert client.post(f"/widget/{submit_id}", data={"event": "click"}).status_code == 400
    # as Qt's toolbar, apart from the stack of pages: the pages can still be switched
    page = client.get("/").text
    for routed in (main_view.pages.first, main_view.pages.note):
        link = _element(page, _widget_id(routed.action.renderer))
        assert "aria-disabled" not in link.attributes
        assert "hx-post" in link.attributes


@pytest.fixture
def tables() -> Iterator[tuple[TestClient, HorizontalMainView]]:
    """Serve an app with tables side by side; yield a client and its main view."""
    views: list[HorizontalMainView] = []

    class TablesApp(WebApplication[HorizontalMainView]):
        def setup_session(self, main_view: HorizontalMainView) -> None:
            views.append(main_view)

    app = TablesApp(build_main_view=HorizontalMainView)
    with TestClient(app.create_starlette_app()) as client:
        client.get("/")
        (view,) = views
        yield client, view


def _rows_with(markup: str, table_id: str, attribute: str) -> list[str | None]:
    """Ids of the swapped table's rows whose `attribute` is true."""
    rows = [attributes for _, attributes in _swapped(markup, table_id).descendants]
    return [row["id"] for row in rows if row.get(attribute) == "true"]


def test_clicking_a_table_row_selects_it_and_swaps_the_table_to_show_it(
    tables: tuple[TestClient, HorizontalMainView],
) -> None:
    client, view = tables
    table = view.tables.narrow
    table_id = _widget_id(table.renderer)
    emitted: list[list[int]] = []
    table.selection_changed.connect(emitted.append)

    def select(row: str) -> Any:
        return client.post(f"/widget/{table_id}", data={"event": "select", "row": row})

    body = select("1").text
    assert table.selected_rows == [1]
    assert emitted == [[1]]
    assert _rows_with(body, table_id, "aria-current") == [f"{table_id}-row-1"]

    select("1")  # the selected row again
    assert emitted == [[1]]

    # a row a stale page still shows: the table comes back as it now is
    body = select("7").text
    assert table.selected_rows == [1]
    assert _rows_with(body, table_id, "aria-current") == [f"{table_id}-row-1"]

    table.is_enabled = False
    assert select("2").status_code == 400
    assert table.selected_rows == [1]
    assert emitted == [[1]]


def test_each_click_adds_or_removes_its_row_in_a_table_selecting_several(
    tables: tuple[TestClient, HorizontalMainView],
) -> None:
    client, view = tables
    table = view.tables.narrow
    table.selection_mode = SelectionMode.MULTIPLE
    table_id = _widget_id(table.renderer)
    emitted: list[list[int]] = []
    table.selection_changed.connect(emitted.append)

    def select(row: str) -> str:
        return client.post(f"/widget/{table_id}", data={"event": "select", "row": row}).text

    page = client.get("/").text
    grid = next(tag for tag in _element(page, table_id).descendants if tag[0] == "table")
    assert grid[1]["role"] == "grid"
    assert grid[1]["aria-multiselectable"] == "true"

    select("2")
    body = select("0")
    assert table.selected_rows == [0, 2]
    assert _rows_with(body, table_id, "aria-selected") == [f"{table_id}-row-{i}" for i in (0, 2)]
    assert _rows_with(body, table_id, "aria-current") == []
    body = select("2")
    assert table.selected_rows == [0]
    assert _rows_with(body, table_id, "aria-selected") == [f"{table_id}-row-0"]
    assert emitted == [[2], [0, 2], [0]]


class _Places(NamedTuple):
    """The editable table's view and its fragment's id, a client, and the edits emitted."""

    client: TestClient
    table: TableView
    table_id: str
    edited: list[tuple[int, int, str, list[str]]]

    def post(self, event: str, row: str, column: str, text: str = "") -> Any:
        data = {"event": event, "row": row, "column": column, "text": text}
        return self.client.post(f"/widget/{self.table_id}", data=data)

    def edit(self, row: str, column: str, text: str) -> str:
        """Edit a cell as the user does, and return the table the edit swaps back."""
        self.post("start_edit", row, column)
        return str(self.post("edit", row, column, text).text)

    def fields(self, markup: str) -> list[dict[str, str | None]]:
        descendants = _swapped(markup, self.table_id).descendants
        return [attributes for tag, attributes in descendants if tag == "input"]

    def texts(self, markup: str) -> list[str]:
        return [_element(markup, f"{self.table_id}-row-{row}").text for row in range(2)]


def _editable_cells(markup: str, table_id: str) -> int:
    descendants = _element(markup, table_id).descendants
    return sum("data-edit" in attributes for _, attributes in descendants)


@pytest.fixture
def places() -> Iterator[_Places]:
    """Serve an app with an editable table, recording each edit with its row as it was."""
    views: list[EditableTableMainView] = []

    class PlacesApp(WebApplication[EditableTableMainView]):
        def setup_session(self, main_view: EditableTableMainView) -> None:
            views.append(main_view)

    app = PlacesApp(build_main_view=EditableTableMainView)
    with TestClient(app.create_starlette_app()) as client:
        client.get("/")
        (view,) = views
        table = view.places
        edited: list[tuple[int, int, str, list[str]]] = []

        def record(row: int, column: int, text: str) -> None:
            # the row as it was: the edit is applied once the callbacks have run
            edited.append((row, column, text, table.rows[row]))

        table.cell_edited.connect(record)
        yield _Places(client, table, _widget_id(table.renderer), edited)


def test_editing_a_cell_swaps_in_its_field_until_its_text_is_posted(places: _Places) -> None:
    table, table_id = places.table, places.table_id
    page = places.client.get("/").text
    # only the notes are editable, the harbour's too though its row is short of it
    assert _editable_cells(page, table_id) == 2

    table.selected_rows = [1]
    (field,) = places.fields(places.post("start_edit", "1", "1").text)
    assert (field["aria-label"], field["value"]) == ("Note", "")
    assert "autofocus" in field
    body = places.post("edit", "1", "1", "Busy").text
    assert table.rows == [["Lake", "Calm"], ["Harbour", "Busy"]]
    assert places.edited == [(1, 1, "Busy", ["Harbour"])]
    # the row moved nowhere: it stays selected
    assert table.selected_rows == [1]
    # the cell is text again
    assert places.fields(body) == []
    assert places.texts(body) == ["LakeCalm", "HarbourBusy"]
    # a cell no field is editing takes no text: e.g. leaving the field after Enter
    places.post("edit", "1", "1", "Busy")
    places.post("edit", "0", "1", "Pond")
    assert table.rows == [["Lake", "Calm"], ["Harbour", "Busy"]]
    assert len(places.edited) == 1

    # the place isn't editable, and the row a stale page shows is gone: the table
    # comes back as it now is, no field in it
    for row, column in (("0", "0"), ("7", "1")):
        assert places.fields(places.post("start_edit", row, column).text) == []

    # disabled, the notes are text only, and a stale page's posts are refused
    table.is_enabled = False
    assert _editable_cells(places.client.get("/").text, table_id) == 0
    assert places.post("start_edit", "0", "1").status_code == 400


def test_rows_answering_an_edit_are_shown_its_row_still_selected(places: _Places) -> None:
    table, table_id = places.table, places.table_id

    def answer(row: int, column: int, text: str) -> None:
        if text == "Windy":  # applied, the rows sorted by note: the lake moves last
            rows = replace_cell(table.rows, row, column, text)
            table.rows = sorted(rows, key=lambda cells: cells[1:])
        else:
            raise EditRefusedError

    table.cell_edited.connect(answer)
    table.selected_rows = [0]
    body = places.edit("0", "1", "Windy")
    assert table.rows == [["Harbour"], ["Lake", "Windy"]]
    assert _rows_with(body, table_id, "aria-current") == [f"{table_id}-row-1"]
    assert places.texts(places.edit("1", "1", "Foggy")) == ["Harbour", "LakeWindy"]
    assert len(places.edited) == 2


def test_a_refusal_in_an_edit_refuses_it_and_says_why(places: _Places) -> None:
    table = places.table
    rows = table.rows

    def refuse(_row: int, _column: int, _text: str) -> None:
        reason = "too foggy"
        with table.refusing("Can't note it: {error}"):
            raise RefusedError(reason)

    table.cell_edited.connect(refuse)
    body = places.edit("1", "1", "Foggy")

    assert table.rows == rows
    assert "Foggy" not in "".join(places.texts(body))
    assert html.escape("Can't note it: too foggy") in body


def test_a_record_table_shows_an_edit_as_its_new_record_or_refuses_it() -> None:
    views: list[RoomsMainView] = []

    class RoomsApp(WebApplication[RoomsMainView]):
        def setup_session(self, main_view: RoomsMainView) -> None:
            views.append(main_view)

    with TestClient(RoomsApp(build_main_view=RoomsMainView).create_starlette_app()) as client:
        client.get("/")
        (view,) = views
        rooms = _Places(client, view.rooms, _widget_id(view.rooms.renderer), [])

        # the new record's cell, not the text as typed
        assert rooms.texts(rooms.edit("1", "1", "21")) == ["Hall18False", "Kitchen21.02True"]
        assert view.rooms.records[1] == Room("Kitchen", 21.0, 2, is_heated=True)
        body = rooms.edit("1", "1", "warm")
        assert rooms.texts(body) == ["Hall18False", "Kitchen21.02True"]
        assert html.escape('Temperature: "warm" isn\'t a valid value') in body


def test_disabling_a_container_disables_the_views_in_it() -> None:
    views: list[VerticalMainView] = []

    class ColumnApp(WebApplication[VerticalMainView]):
        def setup_session(self, main_view: VerticalMainView) -> None:
            views.append(main_view)

    app = ColumnApp(build_main_view=VerticalMainView)
    with TestClient(app.create_starlette_app()) as client:
        client.get("/")
        (view,) = views
        row, column = view.tables, view.tables.column
        column.table.rows = [["North"], ["South"]]

        def disable_the_row(_rows: list[int]) -> None:
            row.is_enabled = False

        column.table.selection_changed.connect(disable_the_row)
        table_id, button_id = _widget_id(column.table.renderer), _widget_id(column.button.renderer)
        body = client.post(f"/widget/{table_id}", data={"event": "select", "row": "0"}).text

        # the row swaps whole, the views of the column inside it disabled
        swapped = _swapped(body, _widget_id(row.renderer))
        (button,) = [
            attributes for _, attributes in swapped.descendants if attributes.get("id") == button_id
        ]
        assert "disabled" in button
        assert not any(
            "hx-post" in attributes for tag, attributes in swapped.descendants if tag == "tr"
        )
        # a stale page's posts are refused, as a disabled button's or table's own
        clicked: list[bool] = []
        column.button.clicked.connect(lambda: clicked.append(True))
        assert client.post(f"/widget/{button_id}", data={"event": "click"}).status_code == 400
        selected = client.post(f"/widget/{table_id}", data={"event": "select", "row": "1"})
        assert selected.status_code == 400
        assert (column.table.selected_rows, clicked) == ([0], [])


class _ShapesApp(WebApplication[TranslatedMainView]):
    def __init__(self) -> None:
        super().__init__(build_main_view=TranslatedMainView)
        self.session_views: list[TranslatedMainView] = []

    def setup_session(self, main_view: TranslatedMainView) -> None:
        self.session_views.append(main_view)


def test_every_session_shows_the_language_asked_on_the_command_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    served: list[Starlette] = []
    monkeypatch.setattr("sys.argv", ["shapes", "--language", "fr"])
    monkeypatch.setattr(
        "composeui.webcore.webapplication.uvicorn.run",
        lambda app, **_: served.append(app),
    )
    app = _ShapesApp()

    app.run()

    with TestClient(served[0]) as client:
        page = client.get("/").text
    view = app.session_views[0]
    assert '<html lang="fr">' in page
    size = _element(page, _field_id(view.shape.size))
    assert [attributes["value"] for tag, attributes in size.descendants if tag == "option"] == [
        "SMALL",
        "LARGE",
    ]
    assert size.text == "PetiteGrande"
    assert _selected(size) == ["LARGE"]
    assert _element(page, _widget_id(_part(view.shape.size, "label"))).text == (
        "Taille de la forme"
    )

    # back to the text as written, e.g. from a language menu
    with collect_dirty() as dirty:
        view.set_language("en")

    combobox = _part(view.shape.size, "field")
    assert combobox.widget_id in dirty
    assert "Large</option>" in combobox.to_html()
    assert view.shape.size.value is Size.LARGE


def test_the_language_menu_swaps_in_the_translated_widgets(
    pipe_main_view: PipeMainView, pipe_client: TestClient
) -> None:
    menu = pipe_main_view.language_menu
    main_pipe_id = _widget_id(pipe_main_view.pages.inputs.pipe_form.main_pipe.renderer)

    response = pipe_client.post(
        f"/widget/{_action_id(menu.action('fr'))}", data={"event": "triggered"}
    )

    assert "hx-refresh" not in response.headers
    assert "Conduite principale" in _swapped(response.text, main_pipe_id).text
    assert pipe_main_view.language == "fr"
    # the page's script sets `<html lang>` and `<title>` from it
    marker = _swapped(response.text, "cui-page").attributes
    assert (marker["data-language"], marker["data-title"]) == ("fr", "Formulaire de conduite")
    assert "Formulaire de conduite" in _swapped(response.text, "cui-brand").text
    assert menu.action("fr").is_checked is True


def test_the_page_is_in_the_app_s_source_language_until_set(
    pipe_main_view: PipeMainView, pipe_client: TestClient
) -> None:
    page = pipe_client.get("/").text

    assert '<html lang="en">' in page
    assert "<title>Pipe Form</title>" in page
    marker = _element(page, "cui-page").attributes
    assert (marker["data-language"], marker["data-title"]) == ("en", "Pipe Form")
    # an event leaving the language alone doesn't send it again
    response = pipe_client.post(
        f"/widget/{_action_id(pipe_main_view.language_menu.action('en'))}",
        data={"event": "triggered"},
    )
    assert _find(response.text, "cui-page") is None
    assert _find(response.text, "cui-brand") is None


@define_view
class _LonePageMainView(MainView):
    app_title = "Lone page"
    extension = ".lone"
    #: outside a router: no toolbar shows its entry
    page: InputsPage = Factory(InputsPage)


def test_a_page_outside_a_router_swaps_nothing_for_its_entry() -> None:
    main_view = _LonePageMainView()
    main_view.render(RendererType.WEB)
    assert isinstance(main_view.renderer, WebMainRenderer)
    page = main_view.renderer.page_html()
    action = main_view.page.action.renderer
    assert isinstance(action, WebActionRenderer)
    assert action.widget_id not in page
    new = main_view.file_menu.new.renderer
    assert isinstance(new, WebActionRenderer)
    assert new.widget_id in page

    with collect_dirty() as dirty:
        main_view.page.title = "Entrées"
        main_view.file_menu.new.text = "Nouveau"

    assert list(dirty) == [new.widget_id]


@pytest.fixture
def chart_views() -> list[PipeChartMainView]:
    """Each session's main view, kept by `chart_client`'s app."""
    return []


@pytest.fixture
def chart_client(chart_views: list[PipeChartMainView]) -> Iterator[TestClient]:
    class ChartApp(WebApplication[PipeChartMainView]):
        def __init__(self) -> None:
            super().__init__(build_main_view=PipeChartMainView)

        def setup_session(self, main_view: PipeChartMainView) -> None:
            chart_views.append(main_view)

    with TestClient(ChartApp().create_starlette_app()) as client:
        yield client


def _chart_spec(markup: str, chart: ChartView) -> dict[str, Any]:
    plot = _element(markup, f"{_widget_id(chart.renderer)}-plot")
    spec: dict[str, Any] = json.loads(plot.attributes["data-chart"] or "")
    return spec


def test_the_chart_sends_its_series_for_the_page_to_draw(
    chart_views: list[PipeChartMainView], chart_client: TestClient
) -> None:
    page = chart_client.get("/").text
    (main_view,) = chart_views
    chart = main_view.chart
    figure = _element(page, _widget_id(chart.renderer))
    assert figure.tag == "figure"
    assert _chart_spec(page, chart) == {
        "title": "Pressure Drop",
        "x": {"label": "Flow Rate (L/s)", "unit": "L/s", "log": False},
        "y": {"label": "Pressure Drop (kPa)", "unit": "kPa", "log": False},
        "series": [],
        "pairs": [],
    }

    chart.series = [
        Series(name="Pressure", x=[0, 1, 2], y=[1, math.nan, math.inf]),
        Series(name="Temperature", x=[0, 1, 2], y=[5, 6, 7]),
    ]
    markup = chart_client.get(f"/widget/{_widget_id(chart.renderer)}").text
    spec = _chart_spec(markup, chart)
    # uPlot's columns, the x shared; no NaN in JSON: a gap is null
    assert spec["data"] == [[0, 1, 2], [1, None, None], [5, 6, 7]]
    assert spec["series"] == [
        # the theme's colors, no fill
        {"name": "Pressure", "kind": "line", "color": None, "fill": False},
        {"name": "Temperature", "kind": "line", "color": None, "fill": False},
    ]
    plot = _element(markup, f"{_widget_id(chart.renderer)}-plot")
    assert plot.attributes["role"] == "img"
    assert plot.attributes["aria-label"] == (
        "Pressure Drop: Pressure, Temperature against Flow Rate (L/s)"
    )

    chart.series = [
        Series(name="Model", x=[2, 0, 1], y=[4, 0, 1]),  # sorted for uPlot
        Series(name="Measured", x=[0.5], y=[0.4]),
    ]
    spec = _chart_spec(chart_client.get(f"/widget/{_widget_id(chart.renderer)}").text, chart)
    # each series by its own x, joined by the page
    assert spec["pairs"] == [[[0, 1, 2], [0, 1, 4]], [[0.5], [0.4]]]


def test_each_series_is_sent_with_how_it_is_drawn(
    chart_views: list[PipeChartMainView], chart_client: TestClient
) -> None:
    chart_client.get("/")
    (main_view,) = chart_views
    main_view.add_curve()
    main_view.add_measurements()
    chart = main_view.chart

    spec = _chart_spec(chart_client.get(f"/widget/{_widget_id(chart.renderer)}").text, chart)
    assert [series["kind"] for series in spec["series"]] == ["line", "scatter"]
    assert len(spec["pairs"][1][0]) == 6  # the measured flow rates, their own x

    with collect_dirty() as dirty:
        chart.kind = ChartKind.SCATTER
        spec = _chart_spec(render_dirty(dirty), chart)
    assert [series["kind"] for series in spec["series"]] == ["scatter", "scatter"]


def test_a_long_series_is_thinned_keeping_its_peaks_and_gaps() -> None:
    count = 100_000
    y = [math.sin(index / 50) for index in range(count)]
    y[500], y[70_000] = 5.0, -5.0  # spikes the thinning must keep
    y[30_000] = math.nan
    chart = ChartView(series=[Series(name="Signal", x=range(count), y=y)])
    chart.render(RendererType.WEB)
    assert isinstance(chart.renderer, WebChartRenderer)

    spec = json.loads(chart.renderer.chart_json())

    xs, ys = spec["data"]
    assert len(xs) <= CHART_MAX_POINTS
    assert xs == sorted(xs)
    assert max(ys, key=lambda v: -math.inf if v is None else v) == 5.0
    assert min(ys, key=lambda v: math.inf if v is None else v) == -5.0
    assert ys[xs.index(30_000)] is None  # the gap stays a gap


def test_a_new_series_list_swaps_the_figure(
    chart_views: list[PipeChartMainView], chart_client: TestClient
) -> None:
    chart_client.get("/")
    (main_view,) = chart_views
    add = main_view.buttons.add

    response = chart_client.post(f"/widget/{_widget_id(add.renderer)}", data={"event": "click"})

    figure = _swapped(response.text, _widget_id(main_view.chart.renderer))
    assert figure.tag == "figure"
    spec = _chart_spec(response.text, main_view.chart)
    assert spec["series"] == [{"name": "D = 50 mm", "kind": "line", "color": None, "fill": False}]


def test_the_page_loads_the_chart_script_only_from_its_own_script(
    client: TestClient, chart_client: TestClient
) -> None:
    """No tag loads the chart library with the page: its script does, once a chart shows."""
    for page in (client.get("/").text, chart_client.get("/").text):
        assert re.findall(r"<script src=\"[^\"]*uPlot", page) == []
    (address,) = re.findall(r'"(/static/uPlot\.iife\.min\.js[^"]*)"', client.get("/").text)
    assert chart_client.get(address).is_success


def test_the_server_compresses_what_it_sends(client: TestClient) -> None:
    response = client.get("/static/app.css", headers={"Accept-Encoding": "gzip"})

    assert response.headers["Content-Encoding"] == "gzip"


def test_a_bar_chart_sends_its_categories_and_each_series_bars() -> None:
    main_view = ChartPagesMainView()
    main_view.render(RendererType.WEB)
    energy = main_view.router.chart.energy
    assert isinstance(energy.renderer, WebChartRenderer)

    markup = energy.renderer.to_html()

    spec = _chart_spec(markup, energy)
    assert spec["categories"] == ["Kitchen", "Bedroom", "Office"]
    # x, the categories' indexes; no cooling in the bedroom
    assert spec["data"] == [[0, 1, 2], [120, 80, 95], [30, None, 45]]
    assert spec["series"] == [
        {
            "name": "Heating",
            "kind": "bar",
            "color": None,
            "fill": False,
            "offset": pytest.approx(-0.2),
            "width": 0.4,
        },
        {
            "name": "Cooling",
            "kind": "bar",
            "color": None,
            "fill": False,
            "offset": pytest.approx(0.2),
            "width": 0.4,
        },
    ]
    plot = _element(markup, f"{_widget_id(energy.renderer)}-plot")
    assert plot.attributes["aria-label"] == "Energy: Heating, Cooling for Kitchen, Bedroom, Office"


def test_a_log_axis_sends_only_what_it_can_show() -> None:
    main_view = ChartPagesMainView()
    main_view.render(RendererType.WEB)
    page = main_view.router.chart
    chart, energy = page.chart, page.energy
    assert isinstance(chart.renderer, WebChartRenderer)
    assert isinstance(energy.renderer, WebChartRenderer)
    chart.series = [Series(name="Decay", x=[0, 1, 10, 100], y=[5, -1, 10, 100])]
    chart.x_log = chart.y_log = True
    energy.series = [Series(name="Heating", x=[0, 1, 2], y=[1000, 0, 50])]
    energy.x_log = energy.y_log = True

    spec = json.loads(chart.renderer.chart_json())
    assert (spec["x"]["log"], spec["y"]["log"]) == (True, True)
    # no x of 0 on a log axis: left out; a y of -1: a gap
    assert spec["data"] == [[1, 10, 100], [None, 10, 100]]
    bars = json.loads(energy.renderer.chart_json())
    assert (bars["x"]["log"], bars["y"]["log"]) == (False, True)  # x: its categories
    assert bars["data"] == [[0, 1, 2], [1000, None, 50]]


def test_the_chart_s_corner_downloads_its_image_at_the_zoom_asked(
    chart_views: list[PipeChartMainView],
    chart_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("matplotlib")
    page = chart_client.get("/").text
    (main_view,) = chart_views
    main_view.add_curve()
    chart_id = _widget_id(main_view.chart.renderer)
    figure = _element(page, chart_id)
    links = [element for element in figure.descendants if element[0] == "a"]
    ((_, link),) = links
    assert link["href"] == f"/widget/{chart_id}/image?format=pdf"
    assert "download" in link
    assert (
        "select",
        {
            "class": "select select-xs join-item w-auto",
            "aria-label": "Image format",
            "data-chart-format": None,
        },
    ) in figure.descendants
    drawn: list[chartimage.ImageOptions] = []
    draw = chartimage.chart_image_bytes

    def chart_image_bytes(
        chart: ChartView, image_format: str, options: chartimage.ImageOptions
    ) -> bytes:
        drawn.append(options)
        return draw(chart, image_format, options)

    monkeypatch.setattr(chartimage, "chart_image_bytes", chart_image_bytes)

    response = chart_client.get(
        f"/widget/{chart_id}/image", params={"format": "svg", "x_min": 0.5, "x_max": "1.5"}
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/svg+xml"
    assert response.headers["content-disposition"] == (
        "attachment; filename=\"Pressure Drop.svg\"; filename*=UTF-8''Pressure%20Drop.svg"
    )
    assert "Flow Rate (L/s)" in response.text
    (options,) = drawn
    assert (options.x_range, options.y_range) == ((0.5, 1.5), None)
    bad = chart_client.get(f"/widget/{chart_id}/image", params={"format": "jpg"})
    assert bad.status_code == 400
    assert (
        chart_client.get(
            f"/widget/{chart_id}/image", params={"x_min": "a", "x_max": "1"}
        ).status_code
        == 400
    )
    assert (
        chart_client.get(f"/widget/{_widget_id(main_view.buttons.add.renderer)}/image").status_code
        == 404
    )


def test_without_matplotlib_the_page_draws_the_chart_s_png(
    chart_views: list[PipeChartMainView],
    chart_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(chartimage, "is_available", lambda: False)
    page = chart_client.get("/").text
    (main_view,) = chart_views
    chart_id = _widget_id(main_view.chart.renderer)
    figure = _element(page, chart_id)

    tags = [tag for tag, _ in figure.descendants]
    assert "select" not in tags
    assert "a" not in tags
    (button,) = [attributes for tag, attributes in figure.descendants if tag == "button"]
    assert button["data-chart-png"] == "Pressure Drop.png"
    assert chart_client.get(f"/widget/{chart_id}/image").status_code == 404


def test_a_click_on_the_chart_reaches_the_view() -> None:
    main_view = BatmanMainView()
    main_view.render(RendererType.WEB)
    chart = main_view.chart
    assert isinstance(chart.renderer, WebChartRenderer)

    with collect_dirty() as dirty:
        chart.renderer.dispatch("click", {"x": "0", "y": "0.5"})
        message = _swapped(render_dirty(dirty), _widget_id(main_view.message.renderer))
    assert message.text == "I'm Batman"
    for form in ({"x": "a", "y": "0"}, {"x": "nan", "y": "0"}, {}):
        with pytest.raises(UnsupportedEventError):
            chart.renderer.dispatch("click", form)
    chart.is_enabled = False
    with pytest.raises(UnsupportedEventError):
        chart.renderer.dispatch("click", {"x": "0", "y": "0"})


def test_a_series_sends_its_own_color_and_fill() -> None:
    main_view = BatmanMainView()
    main_view.render(RendererType.WEB)
    assert isinstance(main_view.chart.renderer, WebChartRenderer)

    spec = json.loads(main_view.chart.renderer.chart_json())

    assert [(series["color"], series["fill"]) for series in spec["series"]] == [
        ("#ffd700", True),
        ("#ffd700", True),
        ("#000000", True),
        ("#000000", True),
    ]


def test_the_chart_s_plot_is_as_tall_as_its_view_says() -> None:
    chart = ChartView(title="Pressure")
    chart.render(RendererType.WEB)
    assert isinstance(chart.renderer, WebChartRenderer)
    plot_id = f"{_widget_id(chart.renderer)}-plot"
    assert _element(chart.renderer.to_html(), plot_id).attributes["class"] == "h-72 w-full"

    with collect_dirty() as dirty:
        chart.height = 420
        plot = _element(render_dirty(dirty), plot_id)  # the figure swapped, at its height

    assert plot.attributes["style"] == "height: 420px"
    assert plot.attributes["class"] == "w-full"


class _SortedRooms(NamedTuple):
    """The sortable, filterable table's view and its fragment's id, and a client."""

    client: TestClient
    view: SortedRoomsMainView
    table_id: str

    def post(self, event: str, **values: str) -> str:
        data = {"event": event, **values}
        response = self.client.post(f"/widget/{self.table_id}", data=data)
        assert response.status_code == 200
        return str(response.text)

    def shown(self, markup: str) -> list[str | None]:
        """Get the ids of the rows the swapped body shows, in order."""
        body = _swapped(markup, f"{self.table_id}-body")
        return [attributes.get("id") for tag, attributes in body.descendants if tag == "tr"]

    def row_ids(self, *rows: int) -> list[str | None]:
        return [f"{self.table_id}-row-{row}" for row in rows]


@pytest.fixture
def sorted_rooms() -> Iterator[_SortedRooms]:
    views: list[SortedRoomsMainView] = []

    class SortedRoomsApp(WebApplication[SortedRoomsMainView]):
        def setup_session(self, main_view: SortedRoomsMainView) -> None:
            views.append(main_view)

    app = SortedRoomsApp(build_main_view=SortedRoomsMainView)
    with TestClient(app.create_starlette_app()) as client:
        client.get("/")
        (view,) = views
        yield _SortedRooms(client, view, _widget_id(view.rooms.renderer))


def test_a_sortable_header_posts_its_sort_swapping_only_the_headers_and_the_body(
    sorted_rooms: _SortedRooms,
) -> None:
    table_id = sorted_rooms.table_id

    def sort_state(markup: str) -> list[str | None]:
        head = _swapped(markup, f"{table_id}-head")
        return [attributes.get("aria-sort") for tag, attributes in head.descendants if tag == "th"]

    body = sorted_rooms.post("sort", column="2")  # the occupants
    assert sort_state(body) == ["none", "none", "ascending", "none"]
    # each row keeps its id from its index in the rows, the empty cell last
    assert sorted_rooms.shown(body) == sorted_rooms.row_ids(2, 3, 1, 0)
    # the table isn't swapped whole: its search field stays as the user left it
    assert _find(body, table_id) is None
    assert _find(body, f"{table_id}-search") is None
    body = sorted_rooms.post("sort", column="2")
    assert sort_state(body)[2] == "descending"
    body = sorted_rooms.post("sort", column="2")
    assert sort_state(body)[2] == "none"
    assert sorted_rooms.shown(body) == sorted_rooms.row_ids(0, 1, 2, 3)

    # a table sorting and filtering by no column: plain headers, no bar
    page = sorted_rooms.client.get("/").text
    notes_id = _widget_id(sorted_rooms.view.notes.renderer)
    notes = _element(page, notes_id)
    assert not any(tag == "button" for tag, _ in notes.descendants)
    assert "hidden" in _element(page, f"{notes_id}-bar").attributes
    assert _element(page, f"{table_id}-bar").attributes["role"] == "search"


def test_the_search_swaps_the_body_and_the_count_never_its_field(
    sorted_rooms: _SortedRooms,
) -> None:
    table_id = sorted_rooms.table_id
    body = sorted_rooms.post("search", search="ROOM")
    assert sorted_rooms.shown(body) == sorted_rooms.row_ids(3)
    count = _swapped(body, f"{table_id}-count")
    assert (count.text, count.attributes["aria-live"]) == ("1 of 4", "polite")
    assert _find(body, f"{table_id}-search") is None

    body = sorted_rooms.post("search", search="nowhere")
    (no_match,) = [
        attributes
        for tag, attributes in _swapped(body, f"{table_id}-body").descendants
        if tag == "td"
    ]
    assert no_match["colspan"] == "4"
    assert "No rows match the filters" in body


def test_the_filter_editor_adds_a_filter_as_a_chip_or_says_why_it_can_t(
    sorted_rooms: _SortedRooms,
) -> None:
    table, table_id = sorted_rooms.view.rooms, sorted_rooms.table_id
    value_id = f"{table_id}-value"

    body = sorted_rooms.post("open_editor")
    _swapped(body, f"{table_id}-bar")
    field = _element(body, value_id)
    assert "autofocus" in field.attributes
    assert field.attributes["aria-describedby"] == f"{value_id}-error"

    # a value that doesn't parse: only its message is swapped in, the field left alone
    body = sorted_rooms.post("add_filter", column="1", value="warm")
    error = _swapped(body, f"{value_id}-error")
    assert (error.text, error.attributes["data-log"]) == ('"warm" isn\'t a number', "error")
    assert "hidden" not in error.attributes
    assert _find(body, value_id) is None
    assert table.filters == {}

    body = sorted_rooms.post("add_filter", column="1", value=">=20")
    assert table.filters == {1: ">=20"}
    assert sorted_rooms.shown(body) == sorted_rooms.row_ids(1, 3)
    bar = _swapped(body, f"{table_id}-bar")
    # the editor closed, the filter's chip taking the focus: it edits the filter
    assert _find(body, value_id) is None
    chip = _element(body, f"{table_id}-chip-1")
    assert chip.text == "Temperature: >=20"
    assert chip.attributes["title"] == "Edit the filter on Temperature"
    assert "autofocus" in chip.attributes
    assert "autofocus" not in _element(body, f"{table_id}-add-filter").attributes
    labels = [attributes.get("aria-label") for tag, attributes in bar.descendants]
    assert "Remove the filter on Temperature" in labels

    # its chip opens the editor on it; a second filter on its column replaces it
    body = sorted_rooms.post("open_editor", column="1")
    assert _element(body, value_id).attributes["value"] == ">=20"
    sorted_rooms.post("add_filter", column="1", value=">=21")
    sorted_rooms.post("open_editor")
    sorted_rooms.post("add_filter", column="3", value="true")
    assert table.filters == {1: ">=21", 3: "true"}
    sorted_rooms.post("remove_filter", column="1")
    assert table.filters == {3: "true"}
    sorted_rooms.post("open_editor")
    body = sorted_rooms.post("close_editor")
    assert _find(body, value_id) is None
    sorted_rooms.post("clear_filters")
    assert table.filters == {}

    # disabled, the table refuses a stale page's posts
    table.is_enabled = False
    response = sorted_rooms.client.post(
        f"/widget/{table_id}", data={"event": "sort", "column": "0"}
    )
    assert response.status_code == 400


def test_the_filter_editor_s_toggle_makes_the_value_a_regular_expression(
    sorted_rooms: _SortedRooms,
) -> None:
    table, table_id = sorted_rooms.view.rooms, sorted_rooms.table_id

    def toggle(markup: str) -> tuple[dict[str, str | None], dict[str, str | None]]:
        """Get the toggle's label and its checkbox."""
        tags = _element(markup, f"{table_id}-editor").descendants
        label = next(attributes for tag, attributes in tags if "data-filter-pattern" in attributes)
        box = next(attributes for tag, attributes in tags if attributes.get("name") == "pattern")
        return label, box

    label, box = toggle(sorted_rooms.post("open_editor"))  # the first column, text
    assert "hidden" not in label
    assert (box["type"], box["aria-label"]) == ("checkbox", "Regular expression")
    # a number column takes comparisons: the page hides the toggle for it
    label, _ = toggle(sorted_rooms.post("open_editor", column="1"))
    assert "hidden" in label

    body = sorted_rooms.post("add_filter", column="0", value="^(hall|attic)$", pattern="1")
    assert table.filters == {0: "/^(hall|attic)$/"}
    assert sorted_rooms.shown(body) == sorted_rooms.row_ids(0, 2)
    assert _element(body, f"{table_id}-chip-0").text == "Room matches ^(hall|attic)$"
    # reopened: the toggle on, the pattern as typed
    body = sorted_rooms.post("open_editor", column="0")
    _, box = toggle(body)
    assert "checked" in box
    assert _element(body, f"{table_id}-value").attributes["value"] == "^(hall|attic)$"
    # a pattern that doesn't compile is refused, saying why; a number column takes none
    body = sorted_rooms.post("add_filter", column="0", value="(hall", pattern="1")
    assert _swapped(body, f"{table_id}-value-error").text == (
        '"(hall" isn\'t a valid regular expression'
    )
    sorted_rooms.post("add_filter", column="1", value=">=20", pattern="1")
    assert table.filters == {0: "/^(hall|attic)$/", 1: ">=20"}


def test_a_click_and_an_edit_on_a_sorted_filtered_table_reach_their_rows(
    sorted_rooms: _SortedRooms,
) -> None:
    table = sorted_rooms.view.rooms
    table.filters = {3: "true"}
    emitted: list[list[int]] = []
    table.selection_changed.connect(emitted.append)

    sorted_rooms.post("select", row="3")
    assert table.selected_records == [Room("Bedroom", 21, 9, is_heated=True)]
    # a row the filters hide, which a stale page still shows: not selected
    sorted_rooms.post("select", row="0")
    assert (table.selected_rows, emitted) == ([3], [[3]])

    sorted_rooms.post("start_edit", row="3", column="0")
    body = sorted_rooms.post("edit", row="3", column="0", text="Study")
    assert table.records[3] == Room("Study", 21, 9, is_heated=True)
    assert table.selected_rows == [3]
    assert _rows_with(body, sorted_rooms.table_id, "aria-current") == sorted_rooms.row_ids(3)

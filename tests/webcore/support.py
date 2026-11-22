"""Helpers shared by the web tests."""

from __future__ import annotations

import base64
import enum
import json
import re
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

import pytest
from typing_extensions import override

pytest.importorskip("starlette")
# Starlette's test client: httpx2, which needs Python 3.11, or httpx before it
pytest.importorskip("httpx2" if sys.version_info >= (3, 11) else "httpx")

import attrs
from attrs import Factory
from starlette.testclient import TestClient

from composeui.core.renderer import RendererContainer
from composeui.core.view import (
    DialogView,
    ImageView,
    LabelRowFloatInputView,
    LabelRowInputView,
    LabelRowIntInputView,
    LabelRowRadioGroupView,
    LabelView,
    ListSource,
    LogView,
    MainView,
    PageView,
    Router,
    SourceTableView,
    TableView,
    View,
    child,
    define_view,
)
from composeui.webcore.routes import SESSION_KEY
from composeui.webcore.session import WebSession
from composeui.webcore.webapplication import WebApplication
from composeui.webcore.webrenderer import (
    WebRenderer,
)
from examples.batman import BatmanMainView
from examples.markdownviewer import MarkdownViewerMainView
from examples.pipecatalogue import (
    PipeCatalogueMainView,
)
from examples.pipechart import PipeChartMainView
from examples.pipeform import PipeMainView
from examples.pipesweep import PipeSweepMainView
from examples.taskview import TaskMainView
from examples.webhello import HelloMainView
from tests.bookings import BookingMainView
from tests.buildings import SiteMainView, SitePlanMainView
from tests.charts import ChartPagesMainView
from tests.choices import ChoicesMainView
from tests.console import RunMainView
from tests.datafiles import DataFileMainView
from tests.dialogs import DialogsMainView
from tests.downloading import ReportMainView
from tests.drawings import DrawingMainView
from tests.expander import RecordMainView
from tests.formdialog import PipeMainView as EditedPipeMainView
from tests.grid import GridMainView
from tests.horizontal import HorizontalMainView
from tests.listview import PipesMainView
from tests.lonerows import LoneRowsMainView
from tests.maps import MapMainView
from tests.markdown import HelpMainView
from tests.metrics import JobsMainView
from tests.pages import InputsPage, PagesMainView
from tests.ranges import RangesMainView
from tests.sidebar import SidebarMainView
from tests.splitter import SplitterMainView, VerticalSplitterMainView
from tests.studyfiles import StudyFileMainView, StudyFilesTableMainView
from tests.tables import (
    CellWidgetsMainView,
    DataFilesTableMainView,
    EditableTableMainView,
    SortedRoomsMainView,
    StyledTablesMainView,
)
from tests.tabs import TabsMainView
from tests.toolbar import ToolBarMainView
from tests.vertical import VerticalMainView
from tests.workers import OpacityMainView, WorkersMainView

if TYPE_CHECKING:
    from starlette.applications import Starlette
    from starlette.types import ASGIApp

    from composeui.core.application import WebSettings


class _Browser(TestClient):
    """A client sending what a browser does from the app's own page: where it comes from.

    Without `Sec-Fetch-Site` (or `Origin`), every POST would be refused as cross-origin.
    """

    def __init__(self, app: ASGIApp, headers: dict[str, str] | None = None) -> None:
        super().__init__(app, headers={"Sec-Fetch-Site": "same-origin", **(headers or {})})


class _HelloApp(WebApplication[HelloMainView]):
    """The hello app, keeping each session's main view through the real session hook."""

    def __init__(self, settings: WebSettings | None = None) -> None:
        super().__init__(build_main_view=HelloMainView, settings=settings)
        self.session_views: list[HelloMainView] = []

    @override
    def setup_session(self, main_view: HelloMainView) -> None:
        # no `threading.Timer` clearing the message in the middle of a test
        main_view.status_bar.timeout = 0
        self.session_views.append(main_view)


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

    @override
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

    @override
    def handle_endtag(self, tag: str) -> None:  # well-formed fragments: any end tag closes
        if self._depth > 0:
            self._depth -= 1
            if self._depth == 0:
                self._finish()

    @override
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


#: text breaking out of an element's text, a quoted attribute (either quote) or an entity
_HOSTILE = "'\" cui-xss='1' \"<cui-xss>&amp;"


class _HostileFinder(HTMLParser):
    """Collects where `_HOSTILE` became markup, reached a script, or shows changed, in a page.

    Shown changed, it was escaped twice (`&lt;` shown) or cut. An attribute holding JSON
    (`data-chart`, `hx-vals`) is read as JSON: its strings show the text.
    """

    def __init__(self) -> None:
        super().__init__()
        self.found: list[str] = []
        self.shown = 0

    @override
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "cui-xss":
            self.found.append("<cui-xss>")
        for name, value in attrs:
            if name == "cui-xss":
                self.found.append(f"<{tag} cui-xss>")
            # escaping doesn't help there: the browser unescapes it, then runs it
            is_script = name.startswith(("on", "hx-on")) or (value or "").startswith("js:")
            if is_script and "cui-xss" in (value or ""):
                self.found.append(f"<{tag} {name}>")
            for text in _json_strings(value or ""):
                self._check_shown(text, f"<{tag} {name}>")

    @override
    def handle_data(self, data: str) -> None:
        self._check_shown(data, "text")

    def _check_shown(self, text: str, where: str) -> None:
        self.shown += text.count(_HOSTILE)
        if "cui-xss" in text.replace(_HOSTILE, ""):
            self.found.append(f"{where} {text!r}")


def _json_strings(value: str) -> list[str]:
    """Get the strings in `value` if it is a JSON object or array, else `value` itself."""
    if not value.startswith(("{", "[")):
        return [value]
    try:
        data = json.loads(value)
    except ValueError:
        return [value]
    strings: list[str] = []
    stack = [data]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            strings.append(item)
        elif isinstance(item, dict):
            stack.extend([*item.keys(), *item.values()])
        elif isinstance(item, list):
            stack.extend(item)
    return strings


@attrs.frozen
class _Note:
    text: str


@define_view
class _NotesMainView(MainView):
    """A large table whose header, cell, search and filter are hostile text."""

    notes: SourceTableView = child(SourceTableView, filterable_columns=["text"])

    @override
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.notes.source = ListSource(_Note, {"text": _HOSTILE}, [_Note(_HOSTILE)])
        # the bar's search and chip show it too, the row still shown
        self.notes.search = _HOSTILE
        self.notes.filters = {"text": "=" + _HOSTILE}


@define_view
class _PicturesMainView(MainView):
    """An image's description is its `alt`, and its only text without an image."""

    picture: ImageView = child(ImageView, image=b"\x89PNG\r\n\x1a\n", description="A curve")
    no_picture: ImageView = child(ImageView, description="Nothing yet")


#: main views showing every kind of view, between them
_MAIN_VIEW_TYPES: list[type[MainView]] = [
    HelloMainView,
    ChoicesMainView,
    RangesMainView,
    ReportMainView,
    DataFileMainView,
    PipeMainView,
    BatmanMainView,
    PipeChartMainView,
    DrawingMainView,
    PipeCatalogueMainView,
    PipeSweepMainView,
    MarkdownViewerMainView,
    TaskMainView,
    BookingMainView,
    SiteMainView,
    SitePlanMainView,
    ChartPagesMainView,
    MapMainView,
    DataFileMainView,
    DialogsMainView,
    EditedPipeMainView,
    RecordMainView,
    PipesMainView,
    HelpMainView,
    JobsMainView,
    PagesMainView,
    SidebarMainView,
    TabsMainView,
    ToolBarMainView,
    WorkersMainView,
    OpacityMainView,
    LoneRowsMainView,
    GridMainView,
    HorizontalMainView,
    VerticalMainView,
    SplitterMainView,
    VerticalSplitterMainView,
    EditableTableMainView,
    SortedRoomsMainView,
    CellWidgetsMainView,
    DataFilesTableMainView,
    StyledTablesMainView,
    StudyFileMainView,
    StudyFilesTableMainView,
    RunMainView,
    _NotesMainView,
    _PicturesMainView,
]


@define_view
class _NameRowView(LabelRowInputView):
    @override
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
    @override
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
    hour: LabelRowIntInputView = child(LabelRowIntInputView, label="Hour", value=8)
    note: LabelView = Factory(LabelView)
    form_log: LogView = Factory(LogView)
    shape: _ShapeRowView = Factory(_ShapeRowView)
    table: TableView = Factory(TableView)

    @override
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.length.label = "Length"
        self.length.value = 20.0


def _pick_file(
    session: WebSession,
    widget_id: str,
    name: str,
    content: bytes,
    media_type: str = "",
) -> tuple[str, str | None] | None:
    """Hand the session a file as the route does, once the file has arrived."""
    with tempfile.TemporaryDirectory() as directory:
        received = Path(directory, "upload")
        received.write_bytes(content)
        return session.pick_file(widget_id, name, received, None, media_type)


def _pick_cell_file(
    session: WebSession, table_id: str, row: int, name: str, content: bytes
) -> tuple[str, str | None] | None:
    """Hand the session a file for a table's cell, of the row and column 1, as the route does."""
    with tempfile.TemporaryDirectory() as directory:
        received = Path(directory, "upload")
        received.write_bytes(content)
        return session.pick_file(table_id, name, received, {"row": str(row), "column": "1"})


def _listed(markup: str, field: WebRenderer[Any]) -> list[tuple[str, str]]:
    """Get the items the field's list of the server's files shows: (event, name)."""
    items = _element(markup, f"{field.widget_id}-files-list")
    values = [json.loads(a["hx-vals"] or "") for tag, a in items.descendants if tag == "button"]
    return [(value["event"], value["name"]) for value in values]


def _shows_files(renderer: WebRenderer[Any]) -> bool:
    dialog = _find(renderer.to_html(), f"{renderer.widget_id}-files")
    return dialog is not None and "hidden" not in dialog.attributes


def _type_name(client: TestClient, main_view: HelloMainView, name: str) -> None:
    field_id = _field_id(main_view.form.name)
    response = client.post(f"/widget/{field_id}", data={"value": name, "event": "input"})
    assert response.status_code == 200


class _Clock:
    """The store's `time`, whose `monotonic` is `now`: moved by the test, not waited for."""

    #: the clock time (`time`) when `now` is 0
    START = 1_800_000_000.0

    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def time(self) -> float:
        return self.START + self.now


def _action_id(action: Any) -> str:
    return _widget_id(action.renderer)


def _count(signal: Any) -> list[None]:
    """Record each emission of a no-argument signal."""
    emitted: list[None] = []

    def on_triggered() -> None:
        emitted.append(None)

    signal.connect(on_triggered)
    return emitted


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


def _session_of(starlette_app: Starlette, client: TestClient) -> WebSession:
    """Get the session that `client`'s cookie names, as the app's middleware signed it."""
    signed = client.cookies["session"]
    session_id = json.loads(base64.b64decode(signed.split(".")[0]))[SESSION_KEY]
    session = starlette_app.state.sessions.get(session_id)
    assert isinstance(session, WebSession)
    return session


def _contains(element: _Element, element_id: str) -> bool:
    """Whether `element` holds an element with the id `element_id`."""
    return any(attributes.get("id") == element_id for _, attributes in element.descendants)


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


def _disable_on_submit(main_view: _NoteMainView, container: View) -> str:
    """Return the id of the first page's button, whose click disables `container`."""

    def disable() -> None:
        container.is_enabled = False

    main_view.pages.first.submit.clicked.connect(disable)
    return _widget_id(main_view.pages.first.submit.renderer)

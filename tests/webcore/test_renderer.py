"""Tests of what every web renderer shares."""

from __future__ import annotations

import ast
import contextlib
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from typing_extensions import override

pytest.importorskip("starlette")
# Starlette's test client: httpx2, which needs Python 3.11, or httpx before it
pytest.importorskip("httpx2" if sys.version_info >= (3, 11) else "httpx")

import attrs

from composeui.core.registry import RendererType
from composeui.core.renderer import NoRenderedObjectError, RendererContainer
from composeui.core.view import (
    CheckBoxView,
    CheckListView,
    ComboBoxView,
    DateRangeInputView,
    DialogView,
    FilePathInputMixin,
    FileUploadMixin,
    FolderPathInputMixin,
    InputView,
    MainView,
    MarkdownView,
    RangeSliderView,
    SavePathInputMixin,
    SliderView,
    StatusBar,
    TableView,
    TabPage,
    TabView,
    UploadedFile,
    View,
    child,
    define_view,
)
from composeui.webcore._renderers.content import (
    WebLabelRenderer,
    WebStatusBarRenderer,
)
from composeui.webcore._renderers.inputs import WebInputRenderer
from composeui.webcore._renderers.navigation import WebMainRenderer
from composeui.webcore._renderers.tables import WebTableRenderer
from composeui.webcore.renderers import RENDERERS
from composeui.webcore.session import WebSession
from composeui.webcore.webrenderer import (
    UnsupportedEventError,
    WebRenderer,
)
from examples.webhello import HelloMainView

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator


from tests.webcore.support import (
    _HOSTILE,
    _MAIN_VIEW_TYPES,
    _element,
    _HostileFinder,
    _part,
    _RowsMainView,
)


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


def _views(view: View) -> Iterator[View]:
    yield view
    for child_view in view.children_views:
        yield from _views(child_view)


def test_the_listed_main_views_show_every_web_renderer() -> None:
    """A new widget joins the escaping test only once a listed main view shows it.

    Each one shows its kind, its role, as the `data-cui` that an app's stylesheet selects.
    """
    shown: set[str] = set()
    for main_view_type in _MAIN_VIEW_TYPES:
        main_view = main_view_type()
        main_view.render(RendererType.WEB)
        assert isinstance(main_view.renderer, WebMainRenderer)
        shown |= set(re.findall(r'data-cui="([a-z_]+)"', main_view.renderer.page_html()))

    roles = {key: getattr(renderer, "_role", None) for key, renderer in RENDERERS.items()}
    assert sorted(key for key, role in roles.items() if role and role not in shown) == []


def _poison(main_view: MainView) -> None:
    """Set every text of every view under `main_view` to `_HOSTILE`."""
    for view in _views(main_view):
        view_type = type(view)
        assert attrs.has(view_type)
        for field in attrs.fields(view_type):
            value = getattr(view, field.name)
            hostile: Any
            if isinstance(view, TableView) and field.name == "search":
                continue  # it would hide every row: see `_states`
            if isinstance(value, str):
                hostile = _HOSTILE
            elif not value or not isinstance(value, list):
                continue
            elif all(isinstance(item, str) for item in value):
                hostile = [_HOSTILE] * len(value)  # e.g. headers, choices
            elif all(
                isinstance(row, list) and all(isinstance(x, str) for x in row) for row in value
            ):
                hostile = [[_HOSTILE] * len(row) for row in value]  # e.g. rows
            else:
                continue
            if isinstance(view, MarkdownView) and field.name == "text":
                # Markdown reads `&amp;` as an entity: one more to show it
                hostile = _HOSTILE.replace("&amp;", "&amp;amp;")
            # a main view's title is its class's; a value a combo box doesn't offer
            with contextlib.suppress(attrs.exceptions.FrozenAttributeError, ValueError):
                setattr(view, field.name, hostile)


def _states(main_view: MainView) -> Iterator[str]:
    """Bring `main_view` to each state that shows other text, naming it once there.

    As first shown; then with what only shows on demand: dialogs, a list of the server's
    files, a cell's field, an upload's files, a table's search, its filter editor, and the
    error or chip of each column filtered.
    """
    yield "as first shown"
    tables: list[tuple[TableView, WebTableRenderer]] = []
    for view in _views(main_view):
        if isinstance(view, DialogView):
            view.open()
        path_types = (FilePathInputMixin, FolderPathInputMixin, SavePathInputMixin)
        if isinstance(view, path_types) and view.server_roots:
            _part(view, "field").dispatch("browse", {})
        if isinstance(view, FileUploadMixin):  # a file's name, or how many with `multiple`
            hostile = UploadedFile(_HOSTILE, 1, "", Path("hostile"))
            view.take_files([hostile] * (2 if view.multiple else 1))
        renderer = view.renderer
        if isinstance(view, TableView) and isinstance(renderer, WebTableRenderer):
            tables.append((view, renderer))
            _open_cell(view, renderer)
    yield "dialogs open, a cell edited, the server's files listed, files given"
    for view, renderer in tables:
        view.search = _HOSTILE  # last: it hides every row
        for column in view.filterable_columns:
            renderer.dispatch("open_editor", {"column": str(column)})
            renderer.dispatch("add_filter", {"column": str(column), "value": _HOSTILE})
            yield f"column {column} filtered"
            renderer.dispatch("open_editor", {"column": str(column)})
            yield f"column {column}'s filter edited"


def _open_cell(table: TableView, renderer: WebTableRenderer) -> None:
    """Edit the first row's first plain editable cell, and list a path cell's server files."""
    if not table.rows:
        return
    for column in table.editable_columns:
        widget = table.cell_widgets.get(column)
        if widget is not None and widget.server_roots:
            renderer.dispatch("browse", {"row": "0", "column": str(column)})
        elif widget is None:
            renderer.dispatch("start_edit", {"row": "0", "column": str(column)})
            return


@pytest.mark.parametrize("main_view_type", _MAIN_VIEW_TYPES)
def test_every_view_text_is_escaped(main_view_type: type[MainView]) -> None:
    """Catches a renderer that leaves a view text unescaped, or escapes it twice.

    Every text field of every view, in each state that shows other text (`_states`).
    """
    main_view = main_view_type()
    main_view.render(RendererType.WEB)
    assert isinstance(main_view.renderer, WebMainRenderer)
    _poison(main_view)

    for state in _states(main_view):
        finder = _HostileFinder()
        finder.feed(main_view.renderer.page_html())
        assert finder.found == [], state
        assert finder.shown > 0, state  # escaped, not dropped


def _is_text_built(node: ast.expr) -> bool:
    """Tell whether `node` builds a text from values, which `Markup` would then not escape."""
    if isinstance(node, (ast.JoinedStr, ast.BinOp)):
        return True
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "format"
        and isinstance(node.func.value, ast.Constant)
    )


def test_the_web_backend_builds_its_html_with_markup() -> None:
    """A text put in HTML by an f-string, or built before `Markup`, goes unescaped.

    `Markup(template).format(...)` escapes each value.
    """
    webcore = Path(__file__).parents[2] / "src/composeui/webcore"
    found: list[str] = []
    # the modules writing HTML, the renderers moved out of `webrenderer.py` included
    modules = [webcore / "webrenderer.py", webcore / "page.py"]
    for path in [*modules, *sorted((webcore / "_renderers").glob("*.py"))]:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.JoinedStr):
                text = "".join(
                    value.value
                    for value in node.values
                    if isinstance(value, ast.Constant) and isinstance(value.value, str)
                )
                if any(mark in text for mark in ("<", '="', "='")):
                    found.append(f"{path.relative_to(webcore)}:{node.lineno} f-string")
            elif isinstance(node, ast.Attribute) and ast.unparse(node) == "html.escape":
                found.append(f"{path.relative_to(webcore)}:{node.lineno} html.escape")
            elif (
                isinstance(node, ast.Call)
                and ast.unparse(node.func) in {"Markup", "markupsafe.Markup"}
                and any(_is_text_built(argument) for argument in node.args)
            ):
                found.append(f"{path.relative_to(webcore)}:{node.lineno} Markup of a built text")
    assert found == []


class _ScriptFinder(HTMLParser):
    """Collects the markup that runs code: what the page's policy refuses (`headers.py`)."""

    def __init__(self) -> None:
        super().__init__()
        self.found: list[str] = []

    @override
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script" and "src" not in dict(attrs):
            self.found.append("<script>")
        for name, value in attrs:
            is_code = (value or "").startswith(("js:", "javascript:"))
            is_filter = name == "hx-trigger" and "[" in (value or "")  # evaluated by htmx
            if name.startswith(("on", "hx-on")) or is_code or is_filter:
                self.found.append(f"<{tag} {name}={value!r}>")


@pytest.mark.parametrize("main_view_type", _MAIN_VIEW_TYPES)
def test_no_markup_runs_code(main_view_type: type[MainView]) -> None:
    """The page's script does what inline handlers and htmx's evaluated values would."""
    main_view = main_view_type()
    main_view.render(RendererType.WEB)
    assert isinstance(main_view.renderer, WebMainRenderer)

    finder = _ScriptFinder()
    finder.feed(main_view.renderer.page_html())
    assert finder.found == []


def test_widget_id_requires_a_render() -> None:
    renderer = WebStatusBarRenderer(StatusBar())
    with pytest.raises(NoRenderedObjectError):
        _ = renderer.widget_id


class _DisabledCombo(ComboBoxView[str]):
    pass


@define_view
class _DisabledTabs(TabView):
    first: TabPage = child(TabPage, title="First")
    second: TabPage = child(TabPage, title="Second")


@define_view
class _DisabledControlsMainView(MainView):
    text: InputView = child(InputView, text="before")
    check: CheckBoxView = child(CheckBoxView)
    slider: SliderView = child(SliderView, maximum=10)
    combo: _DisabledCombo = attrs.Factory(
        lambda: _DisabledCombo(values={"A": "a", "B": "b"}, value="a")
    )
    tabs: _DisabledTabs = child(_DisabledTabs)
    choices: CheckListView[str] = attrs.Factory(
        lambda: CheckListView[str](values={"A": "a", "B": "b"})
    )
    hours: RangeSliderView = child(RangeSliderView)
    days: DateRangeInputView = child(DateRangeInputView)


_DISABLED_EVENTS: dict[str, tuple[str, dict[str, str], Callable[[Any], object], object]] = {
    "text": ("change", {"value": "after"}, lambda view: view.text.text, "before"),
    "check": ("change", {"checked": "on"}, lambda view: view.check.is_checked, False),
    "slider": ("change", {"value": "5"}, lambda view: view.slider.value, 0),
    "combo": ("change", {}, lambda view: view.combo.value, "a"),  # see `_posted`
    "tabs": ("select", {"index": "1"}, lambda view: view.tabs.current_index, 0),
    "choices": ("toggle", {"key": "a", "checked": "on"}, lambda view: view.choices.selected, []),
    "hours": ("input", {"low": "5", "high": "50"}, lambda view: view.hours.value, (0, 100)),
    "days": (
        "input",
        {"end": "0", "value": "09/01/2014"},
        lambda view: view.days.value,
        (None, None),
    ),
}


def _posted(control: Any, form: dict[str, str]) -> dict[str, str]:
    """Get what a control posts: a combo box names its field after its widget."""
    return form or {control.renderer.widget_id: "b"}


def _disabled_session() -> tuple[_DisabledControlsMainView, WebSession, list[object]]:
    view = _DisabledControlsMainView()
    session = WebSession(view)
    signals: list[object] = []
    view.text.text_changed.connect(signals.append)
    view.check.toggled.connect(signals.append)
    view.slider.value_changed.connect(signals.append)
    view.combo.value_changed.connect(signals.append)
    view.tabs.current_changed.connect(signals.append)
    view.choices.selected_changed.connect(signals.append)
    view.hours.value_changed.connect(signals.append)
    view.days.value_changed.connect(signals.append)
    return view, session, signals


@pytest.mark.parametrize("name", _DISABLED_EVENTS)
@pytest.mark.parametrize("how", ["disabled", "hidden"])
def test_a_disabled_or_hidden_control_refuses_its_events(name: str, how: str) -> None:
    view, session, signals = _disabled_session()
    event, form, value_of, before = _DISABLED_EVENTS[name]
    control = getattr(view, name)
    assert isinstance(control.renderer, WebRenderer)
    if how == "disabled" and name == "tabs":
        view.tabs.second.is_enabled = False
    elif how == "disabled":
        control.is_enabled = False
    else:
        control.is_visible = False

    with pytest.raises(UnsupportedEventError):
        session.handle_event(control.renderer.widget_id, event, _posted(control, form))

    assert value_of(view) == before
    assert signals == []
    session.close()


def test_a_control_accepts_its_events_while_enabled() -> None:
    view, session, signals = _disabled_session()
    for name, (event, form, value_of, before) in _DISABLED_EVENTS.items():
        control = getattr(view, name)
        session.handle_event(control.renderer.widget_id, event, _posted(control, form))
        assert value_of(view) != before, name
    assert len(signals) == len(_DISABLED_EVENTS)
    session.close()


def _web_renderers(view: View) -> Iterator[WebRenderer[Any]]:
    """Get the web renderers of `view` and of its children, depth first."""
    renderer = view.renderer
    if isinstance(renderer, RendererContainer):
        yield from (part for part in renderer.renderers if isinstance(part, WebRenderer))
    elif isinstance(renderer, WebRenderer):
        yield renderer
    for child_view in view.children_views:
        yield from _web_renderers(child_view)


@pytest.mark.parametrize("main_view_type", _MAIN_VIEW_TYPES)
def test_every_widget_refuses_an_event_it_doesn_t_take(main_view_type: type[MainView]) -> None:
    """Catches a renderer applying, or ignoring, an event the browser has no reason to send.

    The route answers it 400: a request sent by hand, or by a page of another version.
    """
    main_view = main_view_type()
    main_view.render(RendererType.WEB)
    taken: list[str] = []

    for renderer in _web_renderers(main_view):
        try:
            renderer.dispatch("not-an-event", {})
        except UnsupportedEventError:
            continue
        taken.append(type(renderer).__name__)

    assert taken == []


@pytest.mark.parametrize("main_view_type", _MAIN_VIEW_TYPES)
def test_a_main_view_rendered_again_keeps_every_widget_id(main_view_type: type[MainView]) -> None:
    view = main_view_type()
    view.render(RendererType.WEB)
    before = [renderer.widget_id for renderer in _web_renderers(view)]

    view.render(RendererType.WEB)

    # it also builds the pages and tabs not shown, which wait to be shown otherwise
    after = [renderer.widget_id for renderer in _web_renderers(view)]
    assert set(before) <= set(after)
    assert len(after) == len(set(after))  # each view's renderers once


def test_a_renderer_outside_any_session_calls_back_at_once() -> None:
    view = HelloMainView()
    view.render(RendererType.WEB)
    called: list[None] = []

    renderer = view.form.name.renderer
    assert renderer is not None
    renderer.call_on_main_thread(lambda: called.append(None))

    assert called == [None]

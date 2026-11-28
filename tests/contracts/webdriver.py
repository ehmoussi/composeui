"""The web driver: the posts the page sends, through the Starlette test client.

The page posts a field's text on `input`, debounced, and again on `change`, when the field
loses the focus after a change, with the values of its box (`hx-vals`, a date range's end),
and a text area's line breaks as the form encodes them, CRLF. A check box posts on
`change`, and a slider its value, or a range its two positions, on `input` and `change`.
A radio button or a drop-down list posts its choice's key on `change`, a choice's box
its key and its state, the search field its text, a tree's button its node's path. What the
page's scripts do is for `tests/test_browser.py`.
"""

from __future__ import annotations

import asyncio
import json
import time
from contextlib import asynccontextmanager
from html.parser import HTMLParser
from typing import TYPE_CHECKING, Literal, NamedTuple, Optional

from typing_extensions import override

from composeui.webcore.webapplication import WebApplication
from tests.webcore.support import _Browser, _element, _widget_id

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable, Mapping

    from starlette.testclient import TestClient

    from composeui.core.view import MainView, View


class WebDriver:
    def __init__(self) -> None:
        self._client: Optional[TestClient] = None
        self._part = 0  # the text box typed in, which posts `change` once left

    @asynccontextmanager
    async def open(self, main_view: MainView) -> AsyncGenerator[None, None]:
        app = WebApplication(build_main_view=lambda: main_view)
        with _Browser(app.create_starlette_app()) as client:
            client.get("/")  # starts the session, which renders the view
            self._client = client
            yield

    @asynccontextmanager
    async def by_code(self) -> AsyncGenerator[None, None]:
        yield  # a post is handled before its response: nothing waits

    async def wait_until(self, condition: Callable[[], bool]) -> None:
        assert self._client is not None
        deadline = time.monotonic() + 10
        # a thread changes the session under its lock: read it after a request, which waits
        # for the lock, as the page's poller does
        self._client.get("/_composeui/jobs")
        while not condition() and time.monotonic() < deadline:
            await asyncio.sleep(0.01)
            self._client.get("/_composeui/jobs")
        assert condition()

    async def type(self, view: View, text: str, *, part: int = 0) -> None:
        self._post(view, part, "input", text)
        self._part = part

    async def leave(self, view: View) -> None:
        self._post(view, self._part, "change", self.shown_text(view, part=self._part))

    def shown_text(self, view: View, *, part: int = 0) -> str:
        return _shown_text(self._text_boxes(view)[part])

    def edits(self, text: str) -> list[str]:
        return [text]  # the page posts the field's text once

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

    async def pick(self, view: View, label: str) -> None:
        (control,) = [c for c in self._choices(view) if c.text == label]
        self._send(
            view, {_widget_id(view.renderer): str(control.attributes["value"]), "event": "change"}
        )

    def chosen(self, view: View) -> Optional[str]:
        picked = [
            control
            for control in self._choices(view)
            if "checked" in control.attributes or "selected" in control.attributes
        ]
        assert len(picked) <= 1
        # a drop-down list's empty choice, while none is picked
        return picked[0].text if picked and picked[0].attributes["value"] != "" else None

    async def search(self, view: View, text: str) -> None:
        self._send(view, {"event": "search", "search": text})

    async def check(self, view: View, label: str) -> None:
        (box,) = [box for box in self._boxes(view) if box.text == label]
        values: dict[str, str] = json.loads(str(box.attributes["hx-vals"]))
        # an unchecked box posts no value
        self._send(view, values if "checked" in box.attributes else {**values, "checked": "on"})

    def checks(self, view: View) -> list[tuple[str, bool]]:
        return [(box.text, "checked" in box.attributes) for box in self._boxes(view)]

    def check_all_state(self, view: View) -> Optional[bool]:
        (box,) = [
            control
            for control in self._controls(view)
            if control.attributes.get("id") == f"{_widget_id(view.renderer)}-all-box"
        ]
        # partly checked, as the page's script shows it
        return None if "data-indeterminate" in box.attributes else "checked" in box.attributes

    async def select_node(self, view: View, labels: tuple[str, ...]) -> None:
        self._send(view, json.loads(str(self._tree_buttons(view, "node")[labels]["hx-vals"])))

    async def toggle_node(self, view: View, labels: tuple[str, ...]) -> None:
        self._send(view, json.loads(str(self._tree_buttons(view, "toggle")[labels]["hx-vals"])))

    def selected_node(self, view: View) -> Optional[tuple[str, ...]]:
        selected = [
            labels
            for labels, attributes in self._tree_buttons(view, "node").items()
            if attributes.get("aria-current") == "true"
        ]
        assert len(selected) <= 1
        return selected[0] if selected else None

    def expanded_nodes(self, view: View) -> list[tuple[str, ...]]:
        return [
            labels
            for labels, attributes in self._tree_buttons(view, "toggle").items()
            if attributes.get("aria-expanded") == "true"
        ]

    def _controls(self, view: View) -> list[_Control]:
        assert self._client is not None
        finder = _ControlFinder(_widget_id(view.renderer))
        finder.feed(self._client.get("/").text)
        return finder.controls

    def _choices(self, view: View) -> list[_Control]:
        """Find the radio buttons or the options of `view`, each with its label."""
        return [
            control
            for control in self._controls(view)
            if control.tag == "option" or control.attributes.get("type") == "radio"
        ]

    def _boxes(self, view: View) -> list[_Control]:
        """Find the boxes of `view`'s choices shown, each with its label: not the check-all box."""
        return [
            control
            for control in self._controls(view)
            if control.attributes.get("type") == "checkbox"
            and '"toggle"' in str(control.attributes.get("hx-vals"))
        ]

    def _tree_buttons(
        self, view: View, kind: Literal["node", "toggle"]
    ) -> dict[tuple[str, ...], Mapping[str, Optional[str]]]:
        """Find the buttons of `view`'s tree shown, by the labels down to their node.

        A node's button holds its label; its arrow, before it, is named after it.
        """
        buttons: dict[tuple[str, ...], Mapping[str, Optional[str]]] = {}
        above: list[str] = []
        for control in self._controls(view):
            if control.tag != "button":
                continue
            label = control.attributes.get("aria-label") or control.text
            labels = (*above[: control.depth], label)
            above[control.depth :] = [label]
            is_toggle = "aria-expanded" in control.attributes
            if is_toggle == (kind == "toggle"):
                buttons[labels] = control.attributes
        return buttons

    def _inputs(self, view: View) -> list[Mapping[str, Optional[str]]]:
        assert self._client is not None
        field = _element(self._client.get("/").text, _widget_id(view.renderer))
        return [attributes for tag, attributes in field.descendants if tag == "input"]

    def _text_boxes(self, view: View) -> list[tuple[str, dict[str, Optional[str]], str]]:
        """Find the boxes that the user types in, in order: each one's tag, attributes, text.

        The field, or its own: a date's, a file path's, a date range's two, a text editor's
        text area.
        """
        assert self._client is not None
        page = self._client.get("/").text
        field = _element(page, _widget_id(view.renderer))
        if any(tag == "textarea" for tag, _ in field.descendants):
            field = _element(page, f"{_widget_id(view.renderer)}-text")
        if field.tag == "textarea":  # the field itself, its text the area's
            return [(field.tag, field.attributes, field.text)]
        boxes = [
            (tag, attributes, "")
            for tag, attributes in [(field.tag, field.attributes), *field.descendants]
            if tag == "input" and attributes.get("name") == "value"
        ]
        assert boxes
        return boxes

    def _post(self, view: View, part: int, event: str, text: str) -> None:
        _, attributes, _ = self._text_boxes(view)[part]
        if "readonly" in attributes:  # a browser neither types in it nor posts it
            return
        box_values: dict[str, str] = json.loads(attributes.get("hx-vals") or "{}")
        value = text.replace("\n", "\r\n")
        self._send(view, {**box_values, "value": value, "event": event})

    def _send(self, view: View, form: Mapping[str, str]) -> None:
        assert self._client is not None
        response = self._client.post(f"/_composeui/widget/{_widget_id(view.renderer)}", data=form)
        assert response.status_code == 200


def _shown_text(box: tuple[str, dict[str, Optional[str]], str]) -> str:
    tag, attributes, text = box
    if tag == "textarea":
        # a browser drops a new line just after `<textarea>`
        return text.removeprefix("\n")
    value = attributes["value"]
    assert value is not None
    return value


class _Control(NamedTuple):
    tag: str
    attributes: dict[str, Optional[str]]
    text: str  # its label: the text after it in its label, or in it
    depth: int  # the lists it is in, in the element: a tree node's depth


class _ControlFinder(HTMLParser):
    """Find the inputs, options and buttons in an element, each with its label."""

    _VOID = frozenset({"input", "img", "br", "hr", "meta", "link", "source"})

    def __init__(self, element_id: str) -> None:
        super().__init__()
        self._element_id = element_id
        self._open: list[str] = []  # the tags open in the element, from it
        self.controls: list[_Control] = []
        self._labeled: Optional[int] = None  # the control whose label the text is
        self._text: list[str] = []

    @override
    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        attributes = dict(attrs)
        if not self._open and attributes.get("id") != self._element_id:
            return
        if tag in ("input", "option", "button"):
            self._finish()
            depth = self._open[1:].count("ul")  # the element's own list left out
            self.controls.append(_Control(tag, attributes, "", depth))
            self._labeled = len(self.controls) - 1
        if tag not in self._VOID:
            self._open.append(tag)

    @override
    def handle_endtag(self, tag: str) -> None:
        if not self._open:
            return
        if tag in ("label", "option", "button"):  # the end of a control's label
            self._finish()
        self._open.pop()

    @override
    def handle_data(self, data: str) -> None:
        if self._labeled is not None:
            self._text.append(data)

    def _finish(self) -> None:
        if self._labeled is not None:
            control = self.controls[self._labeled]
            self.controls[self._labeled] = control._replace(text="".join(self._text).strip())
        self._labeled, self._text = None, []

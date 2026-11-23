"""Tests of the web forms and their rows."""

from __future__ import annotations

import re
import sys

import pytest

pytest.importorskip("starlette")
# Starlette's test client: httpx2, which needs Python 3.11, or httpx before it
pytest.importorskip("httpx2" if sys.version_info >= (3, 11) else "httpx")

from typing import TYPE_CHECKING

from composeui.core.registry import RendererType
from composeui.webcore._renderers.navigation import WebMainRenderer
from composeui.webcore.changes import collect_dirty
from composeui.webcore.webrenderer import (
    WebRenderer,
)
from tests.lonerows import LoneRowsMainView
from tests.webcore.support import (
    _contains,
    _element,
    _field_id,
    _part,
    _RowsMainView,
    _swapped,
    _widget_id,
)

if TYPE_CHECKING:
    from starlette.testclient import TestClient

    from examples.pipeform import PipeMainView
    from examples.webhello import HelloMainView
    from tests.folderform import StudyMainView


def test_a_form_row_outside_a_form_shows_as_a_form_shows_it() -> None:
    main_view = LoneRowsMainView()
    main_view.render(RendererType.WEB)
    assert isinstance(main_view.renderer, WebMainRenderer)
    hour, name, note = main_view.sidebar.hour, main_view.column.name, main_view.note

    page = main_view.renderer.page_html()

    # in a sidebar, a column, and the main view itself: each part, as in a form
    for row, parts in ((hour, ["label", "field"]), (name, ["label", "field"]), (note, ["field"])):
        for part in parts:
            assert _part(row, part).widget_id in page
    label, log = _part(name, "label"), _part(name, "log")
    with collect_dirty() as dirty:
        name.label = "Full name"
        name.log_message = "A name is needed."
    # each part swapped in on its own, as in a form
    assert set(dirty) == {label.widget_id, log.widget_id}
    assert "Full name" in label.to_html()
    assert "A name is needed." in log.to_html()


def test_form_label_points_at_its_field_and_escapes_the_text(rows: _RowsMainView) -> None:
    label, field = _part(rows.name, "label"), _part(rows.name, "field")

    fragment = label.to_html()

    assert f'for="{field.widget_id}"' in fragment
    assert "Name &lt;required&gt;" in fragment

    with collect_dirty() as dirty:
        rows.name.label = "Full name"

    assert list(dirty) == [label.widget_id]


def test_a_row_s_help_button_opens_the_help_that_describes_its_field(
    rows: _RowsMainView,
) -> None:
    label, field = _part(rows.length, "label"), _part(rows.length, "field")
    help_id, log_id = f"{label.widget_id}-help", _widget_id(_part(rows.length, "log"))

    with collect_dirty() as dirty:
        rows.length.help = "In metres, <= 100"

    # the field too: its description gains the help
    assert sorted(dirty) == sorted([label.widget_id, field.widget_id])
    fragment = label.to_html()
    assert "In metres, &lt;= 100" in fragment
    (button,) = [
        attributes
        for tag, attributes in _element(fragment, label.widget_id).descendants
        if tag == "button"
    ]
    assert button["popovertarget"] == help_id
    assert button["aria-label"] == "Help"
    assert button["type"] == "button"  # never submits
    help_text = _element(fragment, help_id)
    assert "popover" in help_text.attributes
    assert help_text.text == "In metres, <= 100"
    # the button is beside the `<label>`, not in it: not part of the field's name
    assert _element(fragment, f"{label.widget_id}-text").text == "Length"
    described_by = _element(field.to_html(), field.widget_id).attributes["aria-describedby"]
    assert described_by == f"{help_id} {log_id}"

    rows.length.help = ""

    assert "<button" not in label.to_html()
    assert _element(field.to_html(), field.widget_id).attributes["aria-describedby"] == log_id


def test_clearing_the_name_shows_its_row_message(
    pipe_main_view: PipeMainView, pipe_client: TestClient
) -> None:
    name = pipe_main_view.pages.inputs.pipe_form.name
    name_id = _field_id(name)
    pipe_client.post(f"/_composeui/widget/{name_id}", data={"value": "Tee", "event": "input"})

    body = pipe_client.post(
        f"/_composeui/widget/{name_id}", data={"value": "", "event": "input"}
    ).text

    assert "A name is mandatory" in body
    assert f'id="{_widget_id(_part(name, "log"))}" hx-swap-oob="true"' in body


def test_disabling_a_group_disables_its_whole_fieldset(pipe_main_view: PipeMainView) -> None:
    main_pipe = pipe_main_view.pages.inputs.pipe_form.main_pipe

    with collect_dirty() as dirty:
        main_pipe.is_enabled = False

    group = main_pipe.renderer
    assert isinstance(group, WebRenderer)
    assert list(dirty.values()) == [group]
    # a disabled fieldset disables every control inside it, like a disabled Qt container
    assert re.match(
        r'<fieldset id="[^"]+" data-cui="group_form" class="[^"]+" disabled>', group.to_html()
    )


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
    assert style.attributes["aria-labelledby"] == f"{_widget_id(_part(form.style, 'label'))}-text"


def test_a_form_shows_its_other_views_between_its_rows_in_their_order(
    study: tuple[TestClient, StudyMainView],
) -> None:
    client, view = study
    form = view.open_dialog.form
    dialog_id = _widget_id(view.open_dialog.renderer)
    ids = [
        _field_id(form.folder),
        _widget_id(form.buttons.up.renderer),
        _widget_id(form.entries.renderer),
        _widget_id(form.log_view.renderer),
    ]

    body = client.post(
        f"/_composeui/widget/{_widget_id(view.open.renderer)}", data={"event": "click"}
    ).text
    form_id = _widget_id(form.renderer)
    assert _contains(_swapped(body, dialog_id), form_id)
    # in the form's fieldset: the folder's row, the button, the table, then the message
    shown = [attributes.get("id") for _, attributes in _element(body, form_id).descendants]
    assert [shown.index(element_id) for element_id in ids] == sorted(
        shown.index(element_id) for element_id in ids
    )

    body = client.post(f"/_composeui/widget/{ids[1]}", data={"event": "click"}).text

    assert view.open_dialog.is_visible  # a button of its form leaves it open
    assert f'id="{dialog_id}"' not in body
    assert _swapped(body, ids[0]).attributes.get("value") == "/studies"
    assert "beam" in _swapped(body, ids[2]).text

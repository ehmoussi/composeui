"""Tests of the web text, number and date inputs."""

from __future__ import annotations

import datetime
import re
import sys

import pytest

pytest.importorskip("starlette")
# Starlette's test client: httpx2, which needs Python 3.11, or httpx before it
pytest.importorskip("httpx2" if sys.version_info >= (3, 11) else "httpx")

from typing import TYPE_CHECKING

from composeui.core.registry import RendererType
from composeui.core.view import ButtonView, DateRangeInputView, MainView, child, define_view
from composeui.webcore._renderers.forms import WebFormLabelRenderer
from composeui.webcore._renderers.inputs import WebFloatInputRenderer
from composeui.webcore.changes import collect_dirty
from composeui.webcore.session import WebSession
from composeui.webcore.webrenderer import (
    UnsupportedEventError,
    handle_event,
    render_dirty,
)
from tests.bookings import BookingMainView
from tests.deck import DeckMainView
from tests.hours import HoursMainView
from tests.memory import MemoryMainView
from tests.ranges import FIRST_DAY, LAST_DAY, RangesMainView
from tests.webcore.support import (
    _count,
    _element,
    _field_id,
    _find,
    _part,
    _RowsMainView,
    _swapped,
    _widget_id,
)

if TYPE_CHECKING:
    from starlette.testclient import TestClient

    from examples.pipeform import PipeMainView
    from examples.webhello import HelloMainView


def test_age_is_validated_and_summarised(main_view: HelloMainView, client: TestClient) -> None:
    age_id = _field_id(main_view.form.age)

    body = client.post(f"/_composeui/widget/{age_id}", data={"value": "-3", "event": "input"}).text

    assert main_view.form.age.value == -3.0
    assert "An age can&#39;t be negative" in body

    # another error of the same type: only the message changes, and it must still show
    body = client.post(f"/_composeui/widget/{age_id}", data={"value": "4.5", "event": "input"}).text

    log_id = _widget_id(_part(main_view.form.age, "log"))
    assert _swapped(body, log_id).text == "An age is a whole number of years"

    client.post(f"/_composeui/widget/{age_id}", data={"value": "41", "event": "input"})

    assert main_view.form.age.log_message == ""
    assert main_view.summary.text == "Nobody is 41 years old."


def test_leaving_the_age_field_with_unparsable_text_shows_the_age_again(
    main_view: HelloMainView, client: TestClient
) -> None:
    age_id = _field_id(main_view.form.age)
    finished = _count(main_view.form.age.editing_finished)
    client.post(f"/_composeui/widget/{age_id}", data={"value": "4", "event": "input"})
    client.post(f"/_composeui/widget/{age_id}", data={"value": "4a", "event": "input"})

    body = client.post(f"/_composeui/widget/{age_id}", data={"value": "4a", "event": "change"}).text

    # the field, otherwise never swapped back, now shows the age its messages describe
    assert main_view.form.age.value == 4.0
    assert _swapped(body, age_id).attributes["value"] == "4"  # its 0 decimals
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
    client.post(f"/_composeui/widget/{input_id}", data={"value": "Ann", "event": "change"})
    client.post(f"/_composeui/widget/{input_id}", data={"value": "Ann", "event": "input"})

    assert greeting.text == "Ann"
    assert edited == ["Ann"]
    assert len(finished) == 1


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

    rows.length.decimals = 0
    assert _element(field.to_html(), field.widget_id).attributes["value"] == "20"


def test_a_date_input_is_typed_in_the_language_s_format_or_picked_in_the_browser() -> None:
    view = BookingMainView()
    view.render(RendererType.WEB)
    view.set_language("fr")
    arrival = view.form.arrival
    label, field = _part(arrival, "label"), _part(arrival, "field")
    assert isinstance(label, WebFormLabelRenderer)
    changes: list[datetime.date | None] = []
    arrival.value_changed.connect(changes.append)
    texts: list[str] = []
    arrival.text_changed.connect(texts.append)
    arrival.text_edited.connect(lambda text: texts.append(f"typed {text}"))
    date_input = _element(field.to_html(), field.widget_id)
    (text,) = (attributes for tag, attributes in date_input.descendants if tag == "input")
    assert (text["type"], text["value"], text["placeholder"]) == (
        "text",
        "18/10/2026",
        "dd/mm/yyyy",
    )
    assert text["aria-labelledby"] == label.text_id
    (button,) = (attributes for tag, attributes in date_input.descendants if tag == "button")
    assert button["aria-label"] == "Choisir une date"
    # the calendar, a popover the button opens, on the date and within the range
    (calendar,) = (
        attributes for tag, attributes in date_input.descendants if tag == "calendar-date"
    )
    assert [calendar[name] for name in ("value", "min", "max")] == [
        "2026-10-18",
        "2026-10-01",
        "2026-12-31",
    ]
    (popover,) = (
        attributes for tag, attributes in date_input.descendants if "popover" in attributes
    )
    assert popover["id"] == button["popovertarget"]
    month_buttons = [a["aria-label"] for tag, a in date_input.descendants if "slot" in a]
    assert month_buttons == ["Mois précédent", "Mois suivant"]

    fragments = handle_event(field, "input", {"value": "25/10/20"})
    assert (arrival.value, changes) == (datetime.date(2026, 10, 18), [])  # not a date yet
    fragments = handle_event(field, "input", {"value": "1/11/2026"})
    assert (arrival.value, changes) == (datetime.date(2026, 11, 1), [datetime.date(2026, 11, 1)])
    assert field.widget_id not in fragments  # never swapped back while typed in
    fragments = handle_event(field, "change", {"value": "1/11/2026"})
    assert len(changes) == 1
    # left: shown as the format writes it, the calendar on the date too
    swapped = _swapped(fragments, field.widget_id)
    assert [a["value"] for tag, a in swapped.descendants if tag in ("input", "calendar-date")] == [
        "01/11/2026",
        "2026-11-01",
    ]

    fragments = handle_event(field, "pick", {"picked": "2026-12-24"})
    assert (arrival.value, changes[-1]) == (datetime.date(2026, 12, 24),) * 2
    assert texts[-1] == "24/12/2026"  # picked, not typed
    handle_event(field, "pick", {"picked": "2026-12-24"})  # the same day: nothing new
    handle_event(field, "pick", {"picked": ""})  # no day picked
    assert (len(changes), texts.count("24/12/2026")) == (2, 1)
    swapped = _swapped(fragments, field.widget_id)
    assert next(a["value"] for tag, a in swapped.descendants if tag == "input") == "24/12/2026"
    fragments = handle_event(field, "change", {"value": "31/02/2026"})  # no such day
    swapped = _swapped(fragments, field.widget_id)
    assert next(a["value"] for tag, a in swapped.descendants if tag == "input") == "24/12/2026"
    handle_event(field, "change", {"value": ""})
    assert (arrival.value, changes[-1]) == (None, None)
    assert len(changes) == 3


def test_int_input_takes_whole_numbers_and_puts_the_value_back_on_anything_else(
    rows: _RowsMainView,
) -> None:
    field = _part(rows.hour, "field")
    attributes = _element(field.to_html(), field.widget_id).attributes
    assert (attributes["type"], attributes["inputmode"]) == ("text", "numeric")
    assert attributes["value"] == "8"

    handle_event(field, "input", {"value": "-"})
    assert rows.hour.value == 8
    handle_event(field, "input", {"value": "15"})
    assert rows.hour.value == 15
    handle_event(field, "input", {"value": "15.5"})
    assert rows.hour.value == 15

    fragments = handle_event(field, "change", {"value": "15.5"})

    # left with a decimal: the field, otherwise never swapped back, shows 15 again
    assert _swapped(fragments, field.widget_id).attributes["value"] == "15"


def test_a_parsed_field_writes_its_value_again_once_left_or_keeps_text_it_can_t_read() -> None:
    view = MemoryMainView()
    view.render(RendererType.WEB)
    memory = view.form.memory
    field = _part(memory, "field")
    assert _element(field.to_html(), field.widget_id).attributes["value"] == "4096 MB"

    handle_event(field, "input", {"value": "4gb"})
    assert memory.value == 4000
    fragments = handle_event(field, "change", {"value": "4gb"})
    assert _swapped(fragments, field.widget_id).attributes["value"] == "4 GB"

    fragments = handle_event(field, "change", {"value": "4 XB"})
    assert (memory.text, memory.value) == ("4 XB", None)
    # not put back, as an int field's is: the user fixes it
    assert _find(fragments, field.widget_id) is None


def test_a_date_range_swaps_the_end_that_followed_never_the_one_typed_in() -> None:
    view = RangesMainView()
    view.render(RendererType.WEB)
    days = view.days
    field = _part(days, "field")
    changes: list[tuple[datetime.date | None, datetime.date | None]] = []
    days.value_changed.connect(changes.append)
    start_id, end_id = f"{field.widget_id}-start", f"{field.widget_id}-end"
    page = field.to_html()
    assert _element(page, f"{start_id}-field").attributes["value"] == "09/01/2014"
    assert _element(page, f"{end_id}-field").attributes["aria-label"] == "End"

    answer = handle_event(field, "input", {"end": "1", "value": "08/31/2014"})

    august = datetime.date(2014, 8, 31)
    assert (days.value, changes) == ((august, august), [(august, august)])
    _swapped(answer, start_id)
    assert _element(answer, f"{start_id}-field").attributes["value"] == "08/31/2014"
    assert _find(answer, end_id) is None  # the field typed in stays
    answer = handle_event(field, "change", {"end": "1", "value": "8/31/2014"})  # left
    _swapped(answer, end_id)
    assert _element(answer, f"{end_id}-field").attributes["value"] == "08/31/2014"
    handle_event(field, "pick", {"end": "1", "picked": "2014-09-09"})
    handle_event(field, "input", {"end": "0", "value": "09/0"})  # not a date yet
    assert days.value == (august, datetime.date(2014, 9, 9))
    handle_event(field, "input", {"end": "0", "value": ""})  # emptied: open on that side
    handle_event(field, "change", {"end": "0", "value": ""})  # the same text: no change
    assert (days.value, len(changes)) == ((None, datetime.date(2014, 9, 9)), 3)
    with pytest.raises(UnsupportedEventError):
        handle_event(field, "input", {"end": "2", "value": "09/01/2014"})


@define_view
class _TripMainView(MainView):
    days: DateRangeInputView = child(DateRangeInputView, value=(FIRST_DAY, LAST_DAY))
    open_start: ButtonView = child(ButtonView, text="Any day until the first")
    move_end: ButtonView = child(ButtonView, text="Any day until the fifteenth")


def test_a_date_range_set_by_a_callback_comes_swapped_with_the_response() -> None:
    main_view = _TripMainView()
    session = WebSession(main_view)
    days = main_view.days
    changes: list[tuple[datetime.date | None, datetime.date | None]] = []
    days.value_changed.connect(changes.append)
    main_view.open_start.clicked.connect(lambda: setattr(days, "value", (None, FIRST_DAY)))
    fifteenth = datetime.date(2014, 9, 15)
    main_view.move_end.clicked.connect(lambda: setattr(days, "value", (None, fifteenth)))
    field_id = _widget_id(days.renderer)

    def click_and_read(button: ButtonView) -> list[str | None]:
        response = session.handle_event(_widget_id(button.renderer), "click", {})
        assert response is not None
        field = _swapped(response[0], field_id)  # an open page gets the dates without a reload
        return [
            attributes["value"]
            for tag, attributes in field.descendants
            if tag == "input" and attributes.get("name") == "value"
        ]

    # typed first: the page holds the user's text, which the app's dates replace
    session.handle_event(field_id, "input", {"end": "1", "value": "09/20/2014"})
    typed = [(FIRST_DAY, datetime.date(2014, 9, 20))]

    assert (click_and_read(main_view.open_start), changes) == (["", "09/01/2014"], typed)
    # the end alone of a range already open
    assert (click_and_read(main_view.move_end), changes) == (["", "09/15/2014"], typed)


def test_a_text_area_takes_the_lines_posted_and_finishes_editing_once(
    pipe_main_view: PipeMainView, pipe_client: TestClient
) -> None:
    comment = pipe_main_view.pages.inputs.pipe_form.comment
    field_id = _field_id(comment)
    edited: list[str] = []
    finished: list[None] = []
    comment.text_edited.connect(edited.append)
    comment.editing_finished.connect(lambda: finished.append(None))

    # a form's encoding ends the lines with CRLF; `change` posts the text again
    for event in ("input", "change"):
        pipe_client.post(
            f"/_composeui/widget/{field_id}", data={"value": "North\r\nside", "event": event}
        )

    assert comment.text == "North\nside"
    assert edited == ["North\nside"]
    assert finished == [None]


def test_a_text_area_set_on_the_server_keeps_its_first_new_line(
    pipe_main_view: PipeMainView,
) -> None:
    comment = pipe_main_view.pages.inputs.pipe_form.comment
    field = _part(comment, "field")

    with collect_dirty() as dirty:
        comment.text = "\nindented <b>"

    area = _swapped(render_dirty(dirty), field.widget_id)
    assert area.tag == "textarea"
    # a browser drops a new line just after `<textarea>`: it must not be the text's
    assert area.text == "\n\nindented <b>"


def _text_of_class(markup: str, name: str) -> str:
    """Get the text of the one element of the class `name`, which holds no other element."""
    (found,) = re.finditer(rf'class="{name}"[^>]*>([^<]*)<', markup)
    return found[1]


def test_a_text_editor_set_on_the_server_comes_swapped_with_its_lines_and_file_name() -> None:
    view = DeckMainView()
    view.render(RendererType.WEB)
    deck_id = _widget_id(view.deck.renderer)

    with collect_dirty() as dirty:
        view.deck.text = "\nP ncpus 4"
    html = render_dirty(dirty)
    area = _element(html, f"{deck_id}-text")
    # a browser drops a new line just after `<textarea>`: it must not be the text's
    assert (area.tag, area.text) == ("textarea", "\n\nP ncpus 4")
    assert _element(html, f"{deck_id}-name").text == "study.export"  # its file's name, in its bar
    # a number for each of its lines; the caret at the start, as the field comes
    assert _text_of_class(html, "cui-editor-lines") == "1\n2"
    assert _text_of_class(html, "cui-editor-position") == "Line 1, column 1"

    with collect_dirty() as dirty:
        view.deck.export_filename = "run.export"
    html = render_dirty(dirty)
    _swapped(html, deck_id)
    # the page's script saves the area's text under that name
    descendants = _element(html, deck_id).descendants
    (save,) = [attributes for _, attributes in descendants if "data-save-text" in attributes]
    assert (save["data-save-text"], save["data-filename"]) == (f"{deck_id}-text", "run.export")


def test_number_and_date_fields_take_a_cleared_value_and_report_a_date_once() -> None:
    view = BookingMainView()
    view.render(RendererType.WEB)
    arrival = view.form.arrival
    changes: list[datetime.date | None] = []
    arrival.value_changed.connect(changes.append)
    field = _part(arrival, "field")

    handle_event(field, "change", {"value": "10/18/2026"})  # the date it has
    handle_event(field, "pick", {"picked": "2026-10-18"})  # picked again in the calendar
    handle_event(field, "change", {"value": ""})  # cleared
    hours = HoursMainView()
    hours.render(RendererType.WEB)
    handle_event(_part(hours.form.opening, "field"), "change", {"value": ""})

    assert changes == [None]
    assert hours.form.opening.value is None

"""Tests of the Textual text, number and date inputs."""

from __future__ import annotations

import pytest

pytest.importorskip("textual")
pytest.importorskip("textual_fspicker")

import datetime
from typing import TYPE_CHECKING, Optional

from attrs import Factory
from rich.text import Text
from textual.widgets import (
    Input,
    TextArea,
)

from composeui.core.registry import RendererType
from composeui.core.view import (
    DateInputView,
    FilePathInputView,
    FloatInputView,
    InputView,
    IntInputView,
    MainView,
    define_view,
)
from composeui.textualcore._renderers.navigation import TextualMainRenderer
from composeui.textualcore.textualrenderer import ROW_INVALID_CLASS, TextualWidgetRenderer
from composeui.textualcore.widgets.composedateinput import (
    ComposeCalendar,
    ComposeDateInput,
    ComposeMonth,
)
from composeui.textualcore.widgets.composefilepathinput import (
    ComposeFilePathInput,
)
from composeui.textualcore.widgets.composeinput import ComposeInput
from composeui.textualcore.widgets.composerange import ComposeDateRangeInput
from examples.pipeform import PipeMainView
from examples.textual_demo import TextualDemoMainView
from tests.bookings import BookingMainView
from tests.hours import HoursMainView
from tests.memory import MemoryMainView
from tests.ranges import FIRST_DAY, RangesMainView

if TYPE_CHECKING:
    from collections.abc import Callable

    from textual.app import App


from tests.textualcore.support import _field_widget


@pytest.mark.asyncio
async def test_a_text_area_takes_several_lines_and_finishes_editing_when_left_after_a_change() -> (
    None
):
    view = PipeMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    comment = view.pages.inputs.pipe_form.comment
    edited: list[str] = []
    finished: list[None] = []
    comment.text_edited.connect(edited.append)
    comment.editing_finished.connect(lambda: finished.append(None))

    async with app.run_test() as pilot:
        area = _field_widget(comment.renderer)
        assert isinstance(area, TextArea)
        area.focus()
        await pilot.press(*"North", "enter", *"side")
        await pilot.pause()

        assert comment.text == "North\nside"
        assert finished == []  # Enter starts a new line
        await pilot.press("tab")
        await pilot.pause()
        assert not area.has_focus  # Tab goes to the next field, not into the text
        assert finished == [None]

        comment.text = "Set by the app"
        await pilot.pause()
        area.focus()
        await pilot.pause()
        await pilot.press("tab")
        await pilot.pause()

        assert area.text == "Set by the app"
        assert edited[-1] == "North\nside"  # the app's text is no edit
        assert finished == [None]  # left without a change


@pytest.mark.asyncio
async def test_a_float_input_shows_its_value_with_at_most_its_decimals() -> None:
    view = TextualDemoMainView()
    size = view.form.size
    size.decimals = 2
    size.value = 2.71828
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None

    async with app.run_test() as pilot:
        widget = _field_widget(size.renderer)
        assert isinstance(widget, Input)
        await pilot.pause()
        # Textual reports the text set too: the rounded text doesn't replace the value
        assert (widget.value, size.value) == ("2.72", 2.71828)

        size.decimals = 0
        await pilot.pause()
        assert (widget.value, size.value) == ("3", 2.71828)

        widget.focus()
        await pilot.press("end", "backspace", *"1.5")
        await pilot.pause()
        assert size.value == 1.5  # what the user types is the value


@pytest.mark.asyncio
async def test_an_int_input_takes_only_whole_numbers_marking_those_out_of_range() -> None:
    view = HoursMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None

    async with app.run_test() as pilot:
        widget = _field_widget(view.form.opening.renderer)
        assert isinstance(widget, Input)
        await pilot.pause()
        assert widget.value == "8"
        widget.focus()
        await pilot.press("end", "backspace", *"1.5a")
        await pilot.pause()
        assert (widget.value, view.form.opening.value) == ("15", 15)  # "." and "a" never typed
        assert not widget.has_class("-invalid")

        await pilot.press("backspace", "backspace", "-")
        await pilot.pause()
        assert view.form.opening.value is None  # emptied; the "-" alone isn't a value
        await pilot.press("backspace", *"30")
        await pilot.pause()
        assert view.form.opening.value == 30
        assert widget.has_class("-invalid")  # past 23


#: clears a Textual field of up to 12 characters, the cursor first at its end
_CLEAR = ("end", *["backspace"] * 12)


@pytest.mark.asyncio
async def test_a_parsed_field_writes_its_value_again_once_editing_ends() -> None:
    view = MemoryMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    memory = view.form.memory

    async with app.run_test() as pilot:
        widget = _field_widget(memory.renderer)
        assert isinstance(widget, Input)
        await pilot.pause()
        assert widget.value == "4096 MB"
        widget.focus()
        await pilot.press(*_CLEAR, *"4gb")
        await pilot.pause()
        assert (widget.value, memory.value) == ("4gb", 4000)  # as typed, until editing ends
        await pilot.press("enter")
        await pilot.pause()
        assert (widget.value, memory.value) == ("4 GB", 4000)


async def _booking_app() -> tuple[BookingMainView, App[None], list[Optional[datetime.date]]]:
    """Get the booking app in French, and the dates its arrival reports, as they come."""
    view = BookingMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    changes: list[Optional[datetime.date]] = []
    view.form.arrival.value_changed.connect(changes.append)
    view.set_language("fr")
    return view, app, changes


@pytest.mark.asyncio
async def test_a_date_input_is_typed_in_the_language_s_format_marking_what_isn_t_allowed() -> None:
    view, app, changes = await _booking_app()
    arrival = view.form.arrival

    async with app.run_test(size=(80, 30)) as pilot:
        field = _field_widget(arrival.renderer)
        assert isinstance(field, ComposeDateInput)
        await pilot.pause()
        assert field.input.value == "18/10/2026"
        field.input.focus()
        await pilot.press(*_CLEAR, *"25/10/20")
        await pilot.pause()
        assert (arrival.value, changes) == (None, [None])  # emptied, then not a date yet
        assert field.input.has_class("-invalid")
        await pilot.press(*"26")
        await pilot.pause()
        assert (arrival.value, changes[-1]) == (datetime.date(2026, 10, 25),) * 2
        assert not field.input.has_class("-invalid")
        await pilot.press(*_CLEAR, *"1/1/2027")
        await pilot.pause()
        assert arrival.value == datetime.date(2027, 1, 1)
        assert field.input.has_class("-invalid")  # past the maximum: marked, not refused

        await pilot.press("backspace", "enter")  # "1/1/202" left: the date back
        await pilot.pause()
        assert field.input.value == "01/01/2027"
        arrival.value = datetime.date(2026, 10, 18)  # set in code: shown, not reported
        await pilot.pause()
        assert field.input.value == "18/10/2026"
        assert changes[-1] == datetime.date(2027, 1, 1)


@pytest.mark.asyncio
async def test_a_date_input_s_calendar_names_its_days_in_the_language_and_keeps_to_the_range() -> (
    None
):
    view, app, changes = await _booking_app()
    arrival = view.form.arrival
    texts: list[str] = []
    arrival.text_changed.connect(texts.append)
    arrival.text_edited.connect(lambda text: texts.append(f"typed {text}"))

    async with app.run_test(size=(80, 30)) as pilot:
        field = _field_widget(arrival.renderer)
        assert isinstance(field, ComposeDateInput)
        await pilot.pause()
        await pilot.click(field.button)
        await pilot.pause()
        month = app.screen.query_one(ComposeMonth)
        assert month.has_focus
        rendered = month.render()
        assert isinstance(rendered, Text)
        title, names, *_ = rendered.plain.split("\n")
        assert "octobre 2026" in title
        assert names.split() == ["lu", "ma", "me", "je", "ve", "sa", "di"]
        await pilot.press("down", "pagedown", "enter")  # a week on, then a month on
        await pilot.pause()
        assert not isinstance(app.screen, ComposeCalendar)
        assert (arrival.value, field.input.value) == (datetime.date(2026, 11, 25), "25/11/2026")
        assert changes == [datetime.date(2026, 11, 25)]
        assert texts == ["25/11/2026"]  # picked, not typed
        await pilot.click(field.button)
        await pilot.pause()
        await pilot.press("enter")  # the same day again: nothing to report
        await pilot.pause()
        assert (changes, texts) == ([datetime.date(2026, 11, 25)], ["25/11/2026"])

        await pilot.click(field.button)
        await pilot.pause()
        month = app.screen.query_one(ComposeMonth)
        await pilot.press("pagedown", "pagedown")  # past the maximum: its last day
        await pilot.pause()
        assert month.cursor == datetime.date(2026, 12, 31)
        # a click on a day: the 1st, on the first week's Tuesday
        await pilot.click(month, offset=(1 * 3 + 2, 2))
        await pilot.pause()
        assert arrival.value == datetime.date(2026, 12, 1)
        await pilot.click(field.button)
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, ComposeCalendar)
        assert changes == [datetime.date(2026, 11, 25), datetime.date(2026, 12, 1)]


@pytest.mark.asyncio
async def test_a_date_range_s_end_typed_before_its_start_moves_the_start_to_it() -> None:
    view = RangesMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    days = view.days
    changes: list[tuple[datetime.date | None, datetime.date | None]] = []
    days.value_changed.connect(changes.append)

    async with app.run_test(size=(100, 24)) as pilot:
        field = _field_widget(days.renderer)
        assert isinstance(field, ComposeDateRangeInput)
        await pilot.pause()
        assert [part.input.value for part in field.fields] == ["09/01/2014", ""]
        assert field.end.input.placeholder == "End"

        field.end.input.focus()
        await pilot.press(*"08/31/2014")
        await pilot.pause()

        august = datetime.date(2014, 8, 31)
        assert (days.value, changes) == ((august, august), [(august, august)])
        assert field.start.input.value == "08/31/2014"  # the start followed
        days.value = (None, FIRST_DAY)  # set in code: shown, and not reported
        await pilot.pause()
        assert [part.input.value for part in field.fields] == ["", "09/01/2014"]
        assert len(changes) == 1
        field.start.input.focus()
        await pilot.press(*"09/05/2014")  # after the end: the end follows
        await pilot.pause()
        fifth = datetime.date(2014, 9, 5)
        assert (days.value, field.end.input.value) == ((fifth, fifth), "09/05/2014")


@pytest.mark.asyncio
async def test_editing_finished_fires_on_blur_not_just_enter() -> None:
    """Check that editing_finished fires on blur, not just Enter.

    `editing_finished` must match Qt's `QLineEdit.editingFinished`, which fires on
    Enter *or* losing focus - `Input.Submitted` alone only covers Enter, so tabbing
    or clicking away from a field (a common way to fill out a form) used to never
    trigger validation wired to `editing_finished` (e.g. `PipeFormView._display_error_message`).
    """
    view = PipeMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None

    async with app.run_test() as pilot:
        await pilot.pause()
        widget = _field_widget(view.pages.inputs.pipe_form.main_pipe.radius.renderer)
        widget.focus()
        await pilot.press("5")
        await pilot.pause()
        await pilot.press("tab")
        await pilot.pause()

        assert view.pages.inputs.pipe_form.log_view.is_visible
        assert "incident radius" in view.pages.inputs.pipe_form.log_view.log_message


@pytest.mark.asyncio
async def test_a_failing_pipe_check_marks_the_fields_it_names() -> None:
    view = PipeMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    form = view.pages.inputs.pipe_form
    rows = [
        form.main_pipe.radius,
        form.main_pipe.width,
        form.incident_pipe.half_length,
        form.incident_pipe.radius,
    ]

    def marked() -> list[bool]:
        return [_field_widget(row.renderer).has_class(ROW_INVALID_CLASS) for row in rows]

    async with app.run_test() as pilot:
        await pilot.pause()
        radius = _field_widget(form.main_pipe.radius.renderer)
        radius.focus()
        clear = ["end"] + ["backspace"] * 10  # Textual's ctrl+a only goes to the start
        await pilot.press(*clear, *"300", "tab")
        await pilot.pause()
        # radius + width > the incident half length: the incident radius isn't involved
        assert marked() == [True, True, True, False]

        radius.focus()
        await pilot.press(*clear, *"50", "tab")
        await pilot.pause()
        assert marked() == [False, False, False, False]


@define_view
class _TextFieldsMainView(MainView):
    name: InputView = Factory(InputView)
    ratio: FloatInputView = Factory(FloatInputView)
    count: IntInputView = Factory(IntInputView)
    day: DateInputView = Factory(DateInputView)
    path: FilePathInputView = Factory(FilePathInputView)


def _set_name(view: _TextFieldsMainView) -> None:
    view.name.text = "Ada"


def _set_ratio(view: _TextFieldsMainView) -> None:
    view.ratio.value = 2.5


def _set_count(view: _TextFieldsMainView) -> None:
    view.count.value = 3


def _set_day(view: _TextFieldsMainView) -> None:
    view.day.value = datetime.date(2026, 1, 2)
    view.day.date_format = "dd/MM/yyyy"


def _set_path(view: _TextFieldsMainView) -> None:
    view.path.text = "flows.csv"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "set_by_code"),
    [
        ("name", _set_name),
        ("ratio", _set_ratio),
        ("count", _set_count),
        ("day", _set_day),
        ("path", _set_path),
    ],
)
async def test_a_text_field_reports_the_text_the_user_types_not_the_text_code_sets(
    name: str, set_by_code: Callable[[_TextFieldsMainView], None]
) -> None:
    view = _TextFieldsMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    field = getattr(view, name)
    seen: list[tuple[str, str]] = []
    field.text_changed.connect(lambda text: seen.append(("changed", text)))
    field.text_edited.connect(lambda text: seen.append(("edited", text)))

    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(field.renderer, TextualWidgetRenderer)
        widget = field.renderer.widget
        text_input = (
            widget.input if isinstance(widget, (ComposeDateInput, ComposeFilePathInput)) else widget
        )
        assert isinstance(text_input, ComposeInput)
        set_by_code(view)
        # typed after: the field's change for the code's text would come first
        text_input.focus()
        await pilot.press("end", "1")
        await pilot.pause()

        assert seen == [("changed", text_input.value), ("edited", text_input.value)]


@pytest.mark.asyncio
async def test_a_text_field_keeps_the_text_code_sets_after_a_change_textual_reports_later() -> None:
    view = _TextFieldsMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    seen: list[str] = []
    view.name.text_changed.connect(seen.append)
    view.name.text_edited.connect(seen.append)

    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(view.name.renderer, TextualWidgetRenderer)
        text_input = view.name.renderer.widget
        assert isinstance(text_input, ComposeInput)
        text_input.focus()
        # a key's edit, its `Changed` message queued; the app's text comes before Textual
        # handles it, as a job's result can
        text_input.insert_text_at_cursor("a")
        view.name.text = "Ada"
        await pilot.pause()

        assert (view.name.text, text_input.value, seen) == ("Ada", "Ada", [])


@pytest.mark.asyncio
async def test_a_date_input_s_calendar_keeps_off_the_days_before_its_minimum() -> None:
    view, app, changes = await _booking_app()
    arrival = view.form.arrival

    async with app.run_test(size=(80, 30)) as pilot:
        field = _field_widget(arrival.renderer)
        assert isinstance(field, ComposeDateInput)
        await pilot.pause()
        arrival.minimum = datetime.date(2026, 10, 10)
        await pilot.pause()
        await pilot.click(field.button)
        await pilot.pause()
        month = app.screen.query_one(ComposeMonth)
        await pilot.click(month, offset=(3 * 3 + 2, 2))  # Thursday the 1st, before it
        await pilot.click(month, offset=(1, 12))  # under the weeks
        await pilot.click(month, offset=(1, 0))  # the title's left: the month before
        await pilot.pause()
        cursor = month.cursor
        await pilot.press("enter")
        await pilot.pause()

        assert cursor == datetime.date(2026, 10, 10)  # as near the month before as allowed
        assert (arrival.value, changes) == (cursor, [cursor])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("edge", "keys", "title"),
    [
        (datetime.date.max, ("right", "down", "pagedown"), "9999"),
        (datetime.date.min, ("left", "up", "pageup"), " 1 "),
    ],
)
async def test_a_date_input_s_calendar_opens_and_stops_on_the_first_and_last_dates(
    edge: datetime.date, keys: tuple[str, str, str], title: str
) -> None:
    view, app, _ = await _booking_app()
    arrival = view.form.arrival

    async with app.run_test(size=(80, 30)) as pilot:
        field = _field_widget(arrival.renderer)
        assert isinstance(field, ComposeDateInput)
        arrival.minimum, arrival.maximum = None, None
        arrival.value = edge
        await pilot.pause()
        await pilot.click(field.button)
        await pilot.pause()
        month = app.screen.query_one(ComposeMonth)
        for key in keys:
            await pilot.press(key)
            await pilot.pause()
            assert month.cursor == edge
        rendered = month.render()
        assert isinstance(rendered, Text)
        assert title in rendered.plain.split("\n")[0]


@pytest.mark.asyncio
async def test_a_date_input_s_calendar_picks_no_day_outside_a_range_changed_while_open() -> None:
    view, app, changes = await _booking_app()
    arrival = view.form.arrival

    async with app.run_test(size=(80, 30)) as pilot:
        field = _field_widget(arrival.renderer)
        assert isinstance(field, ComposeDateInput)
        await pilot.pause()
        await pilot.click(field.button)
        await pilot.pause()
        month = app.screen.query_one(ComposeMonth)
        month.maximum = datetime.date(2026, 10, 15)  # under the cursor, on the 18th
        await pilot.press("enter")
        await pilot.click(month, offset=(7 * 3 + 1, 2))  # right of the week's last day
        await pilot.pause()

        assert changes == []
        assert isinstance(app.screen, ComposeCalendar)

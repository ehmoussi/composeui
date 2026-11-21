"""Tests of the Qt text, number and date inputs."""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, Any

import pytest
from qtpy.QtCore import QDate, Qt
from qtpy.QtWidgets import (
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QTableView,
)

from composeui.core.registry import RendererType
from composeui.core.view import (
    FloatInputView,
    InputView,
    IntInputView,
    TextAreaView,
)
from composeui.qtcore.widgets.qdatefield import QDateField, QDateRangeField
from examples.pipeform import PipeMainView
from tests.bookings import BookingMainView
from tests.hours import HoursMainView
from tests.ranges import FIRST_DAY, RangesMainView

if TYPE_CHECKING:
    from collections.abc import Callable

    from pytestqt.qtbot import QtBot


from tests.qtcore.support import _field_widget, _widget


def test_input_renderer_round_trips_typed_text(qtbot: QtBot) -> None:
    view = PipeMainView()
    view.render(RendererType.QT)
    name_widget = _field_widget(view.pages.inputs.pipe_form.name)
    assert isinstance(name_widget, QLineEdit)
    assert name_widget.text() == ""

    name_widget.show()
    name_widget.setFocus()
    qtbot.keyClicks(name_widget, "PipeTShape")
    assert view.pages.inputs.pipe_form.name.text == "PipeTShape"
    assert view.pages.inputs.pipe_form.name.log_message == ""  # _check_name ran via text_edited

    # a change the user didn't type, e.g. a paste or a completer's, reaches the view too
    name_widget.setText("direct")
    assert view.pages.inputs.pipe_form.name.text == "direct"


def test_a_failing_pipe_check_outlines_the_fields_it_names(qtbot: QtBot) -> None:
    view = PipeMainView()
    view.render(RendererType.QT)
    form = view.pages.inputs.pipe_form
    radius_widget = _field_widget(form.main_pipe.radius)
    assert isinstance(radius_widget, QLineEdit)
    named = [form.main_pipe.radius, form.main_pipe.width, form.incident_pipe.half_length]

    def outlined() -> list[bool]:
        return [
            _field_widget(row).styleSheet() != "" for row in (*named, form.incident_pipe.radius)
        ]

    radius_widget.show()
    radius_widget.setFocus()
    radius_widget.selectAll()
    qtbot.keyClicks(radius_widget, "300")
    qtbot.keyClick(radius_widget, Qt.Key.Key_Return)
    # radius + width > the incident half length: the incident radius isn't involved
    assert outlined() == [True, True, True, False]

    radius_widget.selectAll()
    qtbot.keyClicks(radius_widget, "50")
    qtbot.keyClick(radius_widget, Qt.Key.Key_Return)
    assert outlined() == [False, False, False, False]


@pytest.mark.parametrize(
    ("view", "read"),
    [
        (InputView(), lambda view: view.text),
        (FloatInputView(), lambda view: view.value),
        (IntInputView(), lambda view: view.value),
        (TextAreaView(), lambda view: view.text),
    ],
    ids=["text", "float", "int", "text_area"],
)
def test_an_edit_is_reported_once_the_view_has_it(
    qtbot: QtBot,
    view: InputView | FloatInputView | IntInputView | TextAreaView,
    read: Callable[[Any], object],
) -> None:
    """A check run on each edit (`text_edited`) reads the edited value, not the one before."""
    view.render(RendererType.QT)
    field = _widget(view)
    qtbot.addWidget(field)
    seen: list[object] = []
    view.text_edited.connect(lambda _text: seen.append(read(view)))
    field.show()
    field.setFocus()

    qtbot.keyClicks(field, "42")

    assert seen[-2:] in (["4", "42"], [4.0, 42.0], [4, 42])


def test_a_text_area_takes_several_lines_and_finishes_editing_when_left_after_a_change(
    qtbot: QtBot,
) -> None:
    view = PipeMainView()
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.show()
    # active, for the area to take the focus and lose it
    with qtbot.waitActive(window):
        window.activateWindow()
    comment = view.pages.inputs.pipe_form.comment
    area = _field_widget(comment)
    assert isinstance(area, QPlainTextEdit)
    finished: list[None] = []
    comment.editing_finished.connect(lambda: finished.append(None))
    area.setFocus()
    qtbot.waitUntil(area.hasFocus)

    qtbot.keyClicks(area, "North")
    qtbot.keyClick(area, Qt.Key.Key_Return)
    qtbot.keyClicks(area, "side")

    assert comment.text == "North\nside"
    assert finished == []  # Enter starts a new line
    qtbot.keyClick(area, Qt.Key.Key_Tab)
    assert not area.hasFocus()  # Tab goes to the next field, not into the text
    assert finished == [None]

    comment.text = "Set by the app"
    area.setFocus()
    qtbot.keyClick(area, Qt.Key.Key_Tab)

    assert area.toPlainText() == "Set by the app"
    assert finished == [None]  # left without a change


def test_float_input_renderer_round_trips_typed_value_and_rejects_bad_input(qtbot: QtBot) -> None:
    view = PipeMainView()
    view.render(RendererType.QT)
    radius_widget = _field_widget(view.pages.inputs.pipe_form.main_pipe.radius)
    assert isinstance(radius_widget, QLineEdit)

    radius_widget.show()
    radius_widget.setFocus()
    radius_widget.selectAll()
    qtbot.keyClicks(radius_widget, "2000")
    qtbot.keyClick(radius_widget, Qt.Key.Key_Return)
    assert view.pages.inputs.pipe_form.main_pipe.radius.value == 2000.0
    assert view.pages.inputs.pipe_form.log_view.is_visible is True  # tripped the pipe validation

    radius_widget.selectAll()
    qtbot.keyClicks(radius_widget, "abc")
    assert radius_widget.text() != "abc"  # rejected by the QDoubleValidator

    radius_widget.selectAll()
    qtbot.keyClick(radius_widget, Qt.Key.Key_Backspace)
    assert view.pages.inputs.pipe_form.main_pipe.radius.value is None


def test_a_float_input_shows_its_value_with_at_most_its_decimals(qtbot: QtBot) -> None:
    view = FloatInputView(value=3.14159)
    view.render(RendererType.QT)
    field = _widget(view)
    assert isinstance(field, QLineEdit)
    qtbot.addWidget(field)
    assert field.text() == "3.14159"

    view.decimals = 2
    assert field.text() == "3.14"
    assert view.value == 3.14159  # shown rounded, kept as it was
    view.value = 36.0
    assert field.text() == "36"


def test_int_input_is_a_spin_box_keeping_its_value_within_its_range(qtbot: QtBot) -> None:
    view = HoursMainView()
    view.render(RendererType.QT)
    opening = view.form.opening
    spin_box = _field_widget(opening)
    assert isinstance(spin_box, QSpinBox)
    qtbot.addWidget(spin_box)
    assert (spin_box.minimum(), spin_box.maximum(), spin_box.value()) == (0, 23, 8)

    spin_box.show()
    spin_box.setFocus()
    spin_box.selectAll()
    qtbot.keyClicks(spin_box, "15")
    assert opening.value == 15
    qtbot.keyClick(spin_box, Qt.Key.Key_Up)
    assert opening.value == 16
    spin_box.selectAll()
    qtbot.keyClicks(spin_box, "99")
    assert opening.value == 9  # the second 9 would take it past 23

    opening.value = None
    assert spin_box.text() == ""
    opening.minimum = 10  # Qt would show it, as it raises the 9 still held to 10
    assert (spin_box.minimum(), spin_box.text()) == (10, "")
    qtbot.keyClicks(spin_box, "1")
    assert opening.value is None  # on the way to a value in range, not one yet
    qtbot.keyClicks(spin_box, "2")
    assert opening.value == 12
    spin_box.selectAll()
    qtbot.keyClick(spin_box, Qt.Key.Key_Backspace)
    assert opening.value is None


def test_an_int_input_keeps_its_value_while_a_minus_sign_is_typed(qtbot: QtBot) -> None:
    view = IntInputView(value=3, minimum=-5)
    view.render(RendererType.QT)
    spin_box = _widget(view)
    assert isinstance(spin_box, QSpinBox)
    qtbot.addWidget(spin_box)
    spin_box.show()
    spin_box.setFocus()
    spin_box.selectAll()

    qtbot.keyClicks(spin_box, "-")
    kept = view.value
    qtbot.keyClicks(spin_box, "2")

    assert (kept, view.value) == (3, -2)


def test_a_date_input_s_calendar_offers_its_new_limits_at_once(qtbot: QtBot) -> None:
    view = BookingMainView()
    view.render(RendererType.QT)
    arrival = view.form.arrival
    field = _field_widget(arrival)
    assert isinstance(field, QDateField)
    qtbot.addWidget(field)

    # set in code: the calendar's own, not the previous limits, which the view held as its
    # renderer heard of the change
    arrival.maximum = datetime.date(2026, 11, 20)
    arrival.minimum = datetime.date(2026, 11, 2)

    assert (field.calendar.minimumDate(), field.calendar.maximumDate()) == (
        QDate(2026, 11, 2),
        QDate(2026, 11, 20),
    )


def test_a_date_input_is_typed_or_picked_in_the_language_s_format(qtbot: QtBot) -> None:
    view = BookingMainView()
    view.render(RendererType.QT)
    arrival = view.form.arrival
    field = _field_widget(arrival)
    assert isinstance(field, QDateField)
    qtbot.addWidget(field)
    changes: list[datetime.date | None] = []
    arrival.value_changed.connect(changes.append)
    assert field.line_edit.text() == "10/18/2026"  # English's, as the code writes its text

    view.set_language("fr")
    assert field.line_edit.text() == "18/10/2026"
    field.show()
    field.line_edit.selectAll()
    qtbot.keyClicks(field.line_edit, "25/10/20")
    assert (arrival.value, changes) == (datetime.date(2026, 10, 18), [])  # not a date yet
    qtbot.keyClicks(field.line_edit, "26")
    assert (arrival.value, changes) == (datetime.date(2026, 10, 25), [datetime.date(2026, 10, 25)])

    qtbot.mouseClick(field.button, Qt.MouseButton.LeftButton)
    calendar = field.calendar
    assert (calendar.isVisible(), calendar.selectedDate()) == (True, QDate(2026, 10, 25))
    assert (calendar.minimumDate(), calendar.maximumDate()) == (
        QDate(2026, 10, 1),
        QDate(2026, 12, 31),
    )
    calendar.setSelectedDate(QDate(2026, 11, 3))  # the arrows' move to a day
    days = calendar.findChild(QTableView)
    assert days is not None
    qtbot.keyClick(days, Qt.Key.Key_Return)
    assert not calendar.isVisible()
    assert (arrival.value, field.line_edit.text()) == (datetime.date(2026, 11, 3), "03/11/2026")
    assert changes[-1] == datetime.date(2026, 11, 3)

    field.line_edit.selectAll()
    qtbot.keyClicks(field.line_edit, "31/02")
    qtbot.keyClick(field.line_edit, Qt.Key.Key_Return)  # left as no date: the date back
    assert field.line_edit.text() == "03/11/2026"
    field.line_edit.selectAll()
    qtbot.keyClicks(field.line_edit, "03/11/2026")  # the same date typed again: nothing new
    qtbot.mouseClick(field.button, Qt.MouseButton.LeftButton)
    qtbot.keyClick(days, Qt.Key.Key_Return)  # the same day again: nothing to report
    assert len(changes) == 2
    field.line_edit.selectAll()
    qtbot.keyClick(field.line_edit, Qt.Key.Key_Backspace)  # cleared: no date
    assert (arrival.value, changes[-1]) == (None, None)
    # without a date, the calendar opens on the nearest month it allows to today's: the days
    # of today's month couldn't be picked
    arrival.minimum, arrival.maximum = datetime.date(2014, 9, 1), datetime.date(2014, 9, 30)
    qtbot.mouseClick(field.button, Qt.MouseButton.LeftButton)
    assert (calendar.yearShown(), calendar.monthShown()) == (2014, 9)
    calendar.close()
    arrival.minimum, arrival.maximum = datetime.date(2026, 10, 1), datetime.date(2026, 12, 31)
    arrival.value = datetime.date(2026, 11, 3)
    arrival.value = None  # set in code: shown empty, the format as its hint, not reported
    assert field.line_edit.text() == ""
    assert field.line_edit.placeholderText() == "dd/mm/yyyy"
    assert len(changes) == 3


def test_a_date_picked_in_qt_s_calendar_shows_before_the_app_hears_of_it(qtbot: QtBot) -> None:
    view = BookingMainView()
    view.render(RendererType.QT)
    arrival = view.form.arrival
    field = _field_widget(arrival)
    assert isinstance(field, QDateField)
    qtbot.addWidget(field)
    field.show()
    # what the field shows as the app hears of the date: its slow work leaves it shown
    shown: list[str] = []
    arrival.value_changed.connect(lambda _date: shown.append(field.line_edit.text()))

    qtbot.mouseClick(field.button, Qt.MouseButton.LeftButton)
    field.calendar.setSelectedDate(QDate(2026, 11, 3))
    days = field.calendar.findChild(QTableView)
    assert days is not None
    qtbot.keyClick(days, Qt.Key.Key_Return)

    assert shown == ["11/03/2026"]


def test_a_date_input_reports_the_text_typed_or_picked_not_the_text_code_sets(
    qtbot: QtBot,
) -> None:
    view = BookingMainView()
    view.render(RendererType.QT)
    arrival = view.form.arrival
    field = _field_widget(arrival)
    assert isinstance(field, QDateField)
    qtbot.addWidget(field)
    field.show()
    texts: list[str] = []
    arrival.text_changed.connect(texts.append)
    arrival.text_edited.connect(lambda text: texts.append(f"typed {text}"))

    view.set_language("fr")  # its format, set in code
    arrival.value = datetime.date(2026, 11, 3)
    assert (field.line_edit.text(), texts) == ("03/11/2026", [])
    field.line_edit.selectAll()
    qtbot.keyClicks(field.line_edit, "4")
    assert texts == ["4", "typed 4"]
    qtbot.mouseClick(field.button, Qt.MouseButton.LeftButton)
    field.calendar.setSelectedDate(QDate(2026, 11, 5))
    days = field.calendar.findChild(QTableView)
    assert days is not None
    qtbot.keyClick(days, Qt.Key.Key_Return)
    assert texts[2:] == ["05/11/2026"]  # picked, not typed


def test_a_date_range_s_end_typed_before_its_start_moves_the_start_to_it(qtbot: QtBot) -> None:
    view = RangesMainView()
    view.render(RendererType.QT)
    days = view.days
    field = _field_widget(days)
    assert isinstance(field, QDateRangeField)
    qtbot.addWidget(field)
    changes: list[tuple[datetime.date | None, datetime.date | None]] = []
    days.value_changed.connect(changes.append)
    assert [part.line_edit.text() for part in field.fields] == ["09/01/2014", ""]
    assert field.end.line_edit.placeholderText() == "End"

    qtbot.keyClicks(field.end.line_edit, "08/31/2014")

    august = datetime.date(2014, 8, 31)
    assert (days.value, changes) == ((august, august), [(august, august)])
    assert field.start.line_edit.text() == "08/31/2014"  # the start followed
    days.value = (None, FIRST_DAY)  # set in code: shown, and not reported
    assert [part.line_edit.text() for part in field.fields] == ["", "09/01/2014"]
    days.maximum = datetime.date(2014, 9, 15)
    assert field.end.calendar.maximumDate() == QDate(2014, 9, 15)
    assert len(changes) == 1
    qtbot.keyClicks(field.start.line_edit, "09/05/2014")  # after the end: the end follows
    fifth = datetime.date(2014, 9, 5)
    assert (days.value, field.end.line_edit.text()) == ((fifth, fifth), "09/05/2014")

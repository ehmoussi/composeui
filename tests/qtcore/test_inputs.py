"""Tests of the Qt text, number and date inputs."""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, Any, cast

import pytest
from qtpy.QtCore import QDate, Qt
from qtpy.QtGui import QColor, QPalette
from qtpy.QtWidgets import (
    QApplication,
    QFileDialog,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QTableView,
)

from composeui.core._views.inputs import HIGHLIGHT_COLORS, MAX_HIGHLIGHT_SIZE
from composeui.core.registry import RendererType
from composeui.core.view import (
    FloatInputView,
    InputView,
    IntInputView,
    TextAreaView,
)
from composeui.qtcore.widgets.qdatefield import QDateField, QDateRangeField
from composeui.qtcore.widgets.qtexteditor import QTextEditorBox
from examples.pipeform import PipeMainView
from tests.bookings import BookingMainView
from tests.deck import EXPORT, DeckMainView
from tests.hours import HoursMainView
from tests.memory import MemoryMainView
from tests.ranges import FIRST_DAY, RangesMainView

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from pytestqt.qtbot import QtBot
    from qtpy.QtWidgets import QWidget


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

    assert area.toPlainText() == "Set by the app"  # kept through the focus and its loss
    assert finished == [None]  # left without a change


def _shown_editor(qtbot: QtBot, view: DeckMainView) -> QTextEditorBox:
    """Show the main view's window, active for the editor to take the focus."""
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.show()
    with qtbot.waitActive(window):
        window.activateWindow()
    box = _widget(view.deck)
    assert isinstance(box, QTextEditorBox)
    return box


def test_a_text_editor_numbers_its_lines_keeps_them_whole_and_indents_with_tab(
    qtbot: QtBot,
) -> None:
    view = DeckMainView()
    box = _shown_editor(qtbot, view)
    editor = box.text
    area = editor.contentsRect()
    numbers = editor.viewport().geometry().left() - area.left()
    image = editor.grab().toImage()
    first_line = range(area.top(), area.top() + editor.fontMetrics().height())
    margin = range(area.left(), area.left() + numbers)
    shades = {QColor(image.pixel(x, y)).lightness() for x in margin for y in first_line}
    assert len(shades) > 1  # the first line's number is drawn on the margin

    view.deck.text = "\n".join(f"P line{index} {'x' * 300}" for index in range(120))
    # wider for three digits; the long lines scroll rather than wrap
    assert editor.viewport().geometry().left() - editor.contentsRect().left() > numbers
    assert editor.blockCount() == 120
    qtbot.waitUntil(lambda: editor.horizontalScrollBar().maximum() > 0)

    finished: list[None] = []
    view.deck.editing_finished.connect(lambda: finished.append(None))
    editor.setFocus()
    qtbot.waitUntil(editor.hasFocus)
    qtbot.keyClick(editor, Qt.Key.Key_Escape)
    assert (editor.hasFocus(), finished) == (False, [])  # left without a change

    editor.setFocus()
    qtbot.waitUntil(editor.hasFocus)
    editor.moveCursor(editor.textCursor().MoveOperation.Start)
    qtbot.keyClick(editor, Qt.Key.Key_Tab)
    assert view.deck.text.startswith("    P line0 ")
    assert editor.hasFocus()  # Tab types, it doesn't leave


def test_a_text_editor_colors_its_syntax_on_every_line_that_an_edit_reaches(
    qtbot: QtBot,
) -> None:
    view = DeckMainView()
    view.deck.text = "x = 1\ny = 2"
    view.deck.language = "python"
    box = _shown_editor(qtbot, view)
    editor = box.text

    def colors(line: int) -> list[tuple[int, int, str]]:
        layout = editor.document().findBlockByNumber(line).layout()
        # PySide's stubs give a `FormatRange` no field types
        parts = cast("list[Any]", layout.formats())
        return [
            (part.start, part.length, part.format.foreground().color().name()) for part in parts
        ]

    number, string = HIGHLIGHT_COLORS["number"][0], HIGHLIGHT_COLORS["string"][0]
    assert (4, 1, number) in colors(1)  # 2
    editor.moveCursor(editor.textCursor().MoveOperation.Start)
    qtbot.keyClicks(editor, '"""')  # a string opened on the first line goes on to the last
    assert colors(1) == [(0, 5, string)]
    assert view.deck.text == '"""x = 1\ny = 2'

    palette = editor.palette()
    palette.setColor(QPalette.ColorRole.Base, QColor("#111827"))  # a dark theme, without an edit
    editor.setPalette(palette)
    assert colors(1) == [(0, 5, HIGHLIGHT_COLORS["string"][1])]

    view.deck.language = None
    assert (colors(0), colors(1)) == ([], [])

    longer = "1" * (MAX_HIGHLIGHT_SIZE + 1)  # too long to color after each edit
    view.deck.text, view.deck.language = longer, "python"
    assert colors(0) == []
    view.deck.is_read_only = True  # colored once
    assert colors(0) == [(0, len(longer), HIGHLIGHT_COLORS["number"][1])]  # the dark theme's


def test_a_text_editor_s_search_follows_the_user_s_edits_and_the_app_s_text(
    qtbot: QtBot,
) -> None:
    view = DeckMainView()
    box = _shown_editor(qtbot, view)
    editor = box.text
    assert box.search.placeholderText() == "Search"

    qtbot.keyClicks(box.search, "comm")
    assert (box.matches.text(), len(editor.extraSelections())) == ("1 of 2", 2)

    editor.setFocus()
    qtbot.waitUntil(editor.hasFocus)
    editor.moveCursor(editor.textCursor().MoveOperation.End)
    qtbot.keyClick(editor, Qt.Key.Key_Return)
    qtbot.keyClicks(editor, "F comm run.comm D 2")
    assert (box.matches.text(), len(editor.extraSelections())) == ("1 of 4", 4)

    view.deck.text = "P version stable"
    assert (box.matches.text(), editor.extraSelections()) == ("No match", [])


def test_a_text_editor_s_bar_names_its_file_and_says_where_the_caret_is(qtbot: QtBot) -> None:
    view = DeckMainView()
    box = _shown_editor(qtbot, view)
    editor = box.text
    qtbot.waitUntil(editor.hasFocus)  # the window opens with the focus in the text
    assert (box.name.text(), box.position.text()) == ("study.export", "Line 1, column 1")

    editor.setFocus()
    qtbot.waitUntil(editor.hasFocus)
    qtbot.keyClick(editor, Qt.Key.Key_Down)
    qtbot.keyClick(editor, Qt.Key.Key_End)
    assert box.position.text() == f"Line 2, column {len('F comm study.comm D 1') + 1}"

    view.deck.export_filename = "run.export"
    view.deck.texts = {**view.deck.texts, "position": "Ligne {line}, colonne {column}"}
    assert (box.name.text(), box.position.text()) == ("run.export", "Ligne 2, colonne 22")

    # read only: the keys still move the caret and select, as Textual's and the browser's
    view.deck.is_read_only = True
    qtbot.keyClick(editor, Qt.Key.Key_Home)
    qtbot.keyClick(editor, Qt.Key.Key_Down)
    qtbot.keyClick(editor, Qt.Key.Key_Right, Qt.KeyboardModifier.ShiftModifier)
    assert (box.position.text(), editor.textCursor().selectedText()) == ("Ligne 3, colonne 2", "F")


@pytest.mark.parametrize("picked", ["run.export", ""])
def test_a_text_editor_s_buttons_copy_its_text_and_save_it_where_the_user_picks(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, picked: str
) -> None:
    view = DeckMainView()
    box = _shown_editor(qtbot, view)
    asked: list[tuple[str, str]] = []

    def get_save_file_name(_parent: QWidget, caption: str, name: str) -> tuple[str, str]:
        asked.append((caption, name))
        return (str(tmp_path / picked) if picked else ""), ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", get_save_file_name)
    assert (box.copy.text(), box.save.text()) == ("Copy all", "Save as…")

    qtbot.mouseClick(box.copy, Qt.MouseButton.LeftButton)
    assert QApplication.clipboard().text() == EXPORT
    qtbot.mouseClick(box.save, Qt.MouseButton.LeftButton)

    assert asked == [("Save as", "study.export")]
    if picked:
        assert (tmp_path / picked).read_text(encoding="utf-8") == EXPORT
    else:  # cancelled
        assert list(tmp_path.iterdir()) == []


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


def test_a_parsed_field_writes_its_value_again_once_editing_ends(
    qtbot: QtBot,
) -> None:
    view = MemoryMainView()
    view.render(RendererType.QT)
    memory = view.form.memory
    field = _field_widget(memory)
    assert isinstance(field, QLineEdit)
    qtbot.addWidget(field)
    assert field.text() == "4096 MB"

    field.show()
    field.setFocus()
    field.selectAll()
    qtbot.keyClicks(field, "4gb")
    assert (field.text(), memory.value) == ("4gb", 4000)  # as typed, until editing ends
    qtbot.keyClick(field, Qt.Key.Key_Return)
    assert (field.text(), memory.value) == ("4 GB", 4000)


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
    assert field.line_edit.placeholderText() == "dd/mm/yyyy"  # empty: the format as its hint
    arrival.value = datetime.date(2014, 9, 3)
    arrival.value = None  # cleared by the app: the hint kept too
    assert (field.line_edit.text(), field.line_edit.placeholderText()) == ("", "dd/mm/yyyy")
    # each date once: the clear's too, and nothing for the bounds set on the empty field
    assert changes == [datetime.date(2026, 10, 25), datetime.date(2026, 11, 3), None]


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
    days.value = (None, FIRST_DAY)
    days.maximum = datetime.date(2014, 9, 15)
    assert field.end.calendar.maximumDate() == QDate(2014, 9, 15)
    qtbot.keyClicks(field.start.line_edit, "09/05/2014")  # after the end: the end follows
    fifth = datetime.date(2014, 9, 5)
    assert (days.value, field.end.line_edit.text()) == ((fifth, fifth), "09/05/2014")

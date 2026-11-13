from __future__ import annotations

import datetime
from typing import Any, Optional

from qtpy.QtCore import QDate, QPoint, Qt
from qtpy.QtCore import Signal as QtSignal
from qtpy.QtWidgets import (
    QCalendarWidget,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QToolButton,
    QWidget,
)

from composeui.core.view import ISO_DATE_FORMAT, RANGE_DASH, format_date, parse_date

#: a calendar's own range, Qt's default, for a limit the view leaves out
_CALENDAR_FIRST, _CALENDAR_LAST = QDate(-4714, 11, 25), QDate(9999, 12, 31)


def _qdate(value: datetime.date) -> QDate:
    return QDate(value.year, value.month, value.day)


class QDateField(QWidget):
    """A field typing a date as `date_format` says, then a button opening a calendar.

    Qt's date edit can't be empty: this field can, meaning no date. `date_edited` reports
    the user's dates, typed or picked, and None once the field is emptied; text that isn't
    a date reports nothing, and leaving the field puts the date back. The calendar, a
    popup, offers the dates from `minimum` to `maximum`, named in the system's language.
    """

    #: the user typed or picked a date (a `datetime.date`), or emptied the field (None)
    date_edited = QtSignal(object)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._date: Optional[datetime.date] = None
        self._date_format = ISO_DATE_FORMAT
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self.line_edit = QLineEdit()
        self.line_edit.textEdited.connect(self._read_text)
        self.line_edit.editingFinished.connect(self._show_date)
        layout.addWidget(self.line_edit)
        self.button = QToolButton()
        self.button.setArrowType(Qt.ArrowType.DownArrow)
        self.button.clicked.connect(self.open_calendar)
        layout.addWidget(self.button)
        self.calendar = QCalendarWidget(self)
        self.calendar.setWindowFlags(Qt.WindowType.Popup)
        self.calendar.clicked.connect(self._pick)
        self.calendar.activated.connect(self._pick)  # Enter on a day

    def set_date(self, value: Optional[datetime.date]) -> None:
        self._date = value
        self._show_date()

    def set_date_format(self, date_format: str) -> None:
        self._date_format = date_format
        self._show_date()

    def set_range(self, minimum: Optional[datetime.date], maximum: Optional[datetime.date]) -> None:
        first = _CALENDAR_FIRST if minimum is None else _qdate(minimum)
        last = _CALENDAR_LAST if maximum is None else _qdate(maximum)
        self.calendar.setDateRange(first, last)

    def open_calendar(self) -> None:
        """Show the calendar under the field, on the date, else on today's month.

        Today out of the range, on the month of its nearest limit: the calendar would show a
        month of days that the user can't pick.
        """
        if self._date is not None:
            self.calendar.setSelectedDate(_qdate(self._date))
        else:
            shown = min(
                max(QDate.currentDate(), self.calendar.minimumDate()),
                self.calendar.maximumDate(),
            )
            self.calendar.setCurrentPage(shown.year(), shown.month())
        self.calendar.move(self.mapToGlobal(QPoint(0, self.height())))
        self.calendar.show()
        self.calendar.setFocus()

    def _read_text(self, text: str) -> None:
        if text.strip() == "":
            self._edit(None)
            return
        try:
            value = parse_date(text, self._date_format)
        except ValueError:
            return  # not a date yet, e.g. halfway through typing one
        self._edit(value)

    def _pick(self, value: QDate) -> None:
        # `close`, not `hide`: it also releases the popup's window, which WSLg's
        # compositor could otherwise keep drawing (see `release_when_hidden`)
        self.calendar.close()
        picked = datetime.date(value.year(), value.month(), value.day())
        if picked == self._date:
            self._show_date()  # e.g. over a date half typed
            return
        self._date = picked
        # the date shown at once, before the app's work on it: Qt would paint the field only
        # once that work is over, e.g. a dashboard filtering its rows and drawing them again
        self._show_date()
        self.line_edit.repaint()
        self.date_edited.emit(picked)

    def _edit(self, value: Optional[datetime.date]) -> None:
        if value != self._date:
            self._date = value
            self.date_edited.emit(value)

    def _show_date(self) -> None:
        text = "" if self._date is None else format_date(self._date, self._date_format)
        if self.line_edit.text() != text:
            self.line_edit.setText(text)


class QDateRangeField(QWidget):
    """Two date fields, the start and the end of a range, with a dash between them.

    `end_edited` reports the user's dates for an end: its index (0 the start, 1 the end)
    and the date, None once the field is emptied.
    """

    #: the user typed or picked a date for an end: its index and the date, or None
    end_edited = QtSignal(int, object)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.start = QDateField()
        self.end = QDateField()
        layout.addWidget(self.start)
        layout.addWidget(QLabel(RANGE_DASH.strip()))
        layout.addWidget(self.end)
        self.start.date_edited.connect(self._start_edited)
        self.end.date_edited.connect(self._end_edited)

    @property
    def fields(self) -> tuple[QDateField, QDateField]:
        return self.start, self.end

    def _start_edited(self, value: Optional[datetime.date]) -> None:
        self.end_edited.emit(0, value)

    def _end_edited(self, value: Optional[datetime.date]) -> None:
        self.end_edited.emit(1, value)

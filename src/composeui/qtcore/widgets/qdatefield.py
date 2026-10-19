from __future__ import annotations

import datetime
from typing import Any, Optional

from qtpy.QtCore import QDate, QPoint, Qt
from qtpy.QtCore import Signal as QtSignal
from qtpy.QtWidgets import QCalendarWidget, QHBoxLayout, QLineEdit, QToolButton, QWidget

from composeui.core.view import ISO_DATE_FORMAT, format_date, parse_date

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

    def date(self) -> Optional[datetime.date]:
        return self._date

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
        """Show the calendar under the field, on the date, else on today's month."""
        if self._date is not None:
            self.calendar.setSelectedDate(_qdate(self._date))
        else:
            today = QDate.currentDate()
            self.calendar.setCurrentPage(today.year(), today.month())
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
        self._edit(datetime.date(value.year(), value.month(), value.day()))
        self._show_date()

    def _edit(self, value: Optional[datetime.date]) -> None:
        if value != self._date:
            self._date = value
            self.date_edited.emit(value)

    def _show_date(self) -> None:
        text = "" if self._date is None else format_date(self._date, self._date_format)
        if self.line_edit.text() != text:
            self.line_edit.setText(text)

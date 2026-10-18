from __future__ import annotations

import calendar
import datetime
from typing import TYPE_CHECKING, ClassVar, Optional

from rich.style import Style
from rich.text import Text
from textual.binding import Binding, BindingType
from textual.containers import Center, Horizontal, Middle
from textual.screen import ModalScreen
from textual.validation import ValidationResult, Validator
from textual.widget import Widget
from textual.widgets import Button

from composeui.core.signal import Signal
from composeui.core.view import ISO_DATE_FORMAT, format_date, parse_date
from composeui.textualcore.widgets.composeinput import ComposeInput

if TYPE_CHECKING:
    from collections.abc import Sequence

    from textual import events
    from textual.app import ComposeResult, RenderResult

#: a day's cell in the month grid: its number right-aligned, after a space
_CELL_WIDTH = 3
#: the month grid's lines above its weeks: the month, then the days' names
_HEADER_LINES = 2


class ComposeMonth(Widget, can_focus=True):
    """A month's days in a grid, a week a line from Monday, the cursor on one day.

    Textual has no calendar. The arrows move the cursor a day or a week, Page Up/Down a
    month, onto the next month's grid as needed; Enter picks the cursor's day, and a click
    picks the day under it (or, on the month's line, goes to the month before or after).
    Days out of `minimum`/`maximum` are dimmed and never picked.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("left", "move(-1)", show=False),
        Binding("right", "move(1)", show=False),
        Binding("up", "move(-7)", show=False),
        Binding("down", "move(7)", show=False),
        Binding("pageup", "move_month(-1)", show=False),
        Binding("pagedown", "move_month(1)", show=False),
        Binding("enter", "pick", show=False),
    ]

    COMPONENT_CLASSES: ClassVar[set[str]] = {
        "month--title",
        "month--day-name",
        "month--cursor",
        "month--picked",
        "month--out-of-range",
    }

    DEFAULT_CSS = """
    ComposeMonth {
        width: 21;
        height: 8;
        & > .month--title {
            text-style: bold;
        }
        & > .month--day-name {
            color: $foreground 60%;
        }
        & > .month--cursor {
            background: $accent 40%;
        }
        &:focus > .month--cursor {
            background: $accent;
            color: $text;
        }
        & > .month--picked {
            text-style: bold underline;
        }
        & > .month--out-of-range {
            color: $foreground 30%;
        }
    }
    """

    def __init__(
        self,
        picked: datetime.date | None,
        minimum: datetime.date | None,
        maximum: datetime.date | None,
        month_names: Sequence[str] = (),
        day_names: Sequence[str] = (),
    ) -> None:
        super().__init__()
        self.minimum, self.maximum = minimum, maximum
        # on the date picked, else on today
        self.cursor = self._in_range(picked or datetime.datetime.now().astimezone().date())
        self.picked_date = picked
        self.month_names = list(month_names) or list(calendar.month_name)[1:]
        self.day_names = list(day_names) or [name[:2] for name in calendar.day_abbr]
        #: the user picked a day
        self.picked: Signal[datetime.date] = Signal()

    def render(self) -> RenderResult:
        text = Text(no_wrap=True, overflow="crop")
        width = 7 * _CELL_WIDTH
        title = f"{self.month_names[self.cursor.month - 1]} {self.cursor.year}"
        text.append(
            f"<{title.center(width - 2)}>\n", style=self.get_component_rich_style("month--title")
        )
        names = "".join(f"{name[:2]:>{_CELL_WIDTH}}" for name in self.day_names)
        text.append(f"{names}\n", style=self.get_component_rich_style("month--day-name"))
        for week in self._weeks():
            for day in week:
                if day is None:
                    text.append(" " * _CELL_WIDTH)
                    continue
                styles = []
                if not self._is_in_range(day):
                    styles.append("month--out-of-range")
                if day == self.picked_date:
                    styles.append("month--picked")
                if day == self.cursor:
                    styles.append("month--cursor")
                style = Style.combine([Style(), *map(self.get_component_rich_style, styles)])
                text.append(" ")
                text.append(f"{day.day:>{_CELL_WIDTH - 1}}", style=style)
            text.append("\n")
        text.rstrip()
        return text

    def _weeks(self) -> list[list[datetime.date | None]]:
        """Get the cursor's month a week a list, Monday first, None out of the month."""
        month = calendar.Calendar(firstweekday=0)
        return [
            [day if day.month == self.cursor.month else None for day in week]
            for week in month.monthdatescalendar(self.cursor.year, self.cursor.month)
        ]

    def action_move(self, days: int) -> None:
        self._move_to(self.cursor + datetime.timedelta(days=days))

    def action_move_month(self, months: int) -> None:
        month = self.cursor.month - 1 + months
        year, month = self.cursor.year + month // 12, month % 12 + 1
        day = min(self.cursor.day, calendar.monthrange(year, month)[1])
        self._move_to(datetime.date(year, month, day))

    def action_pick(self) -> None:
        if self._is_in_range(self.cursor):
            self.picked.emit(self.cursor)

    def on_click(self, event: events.Click) -> None:
        if event.y == 0:
            self.action_move_month(-1 if event.x < 7 * _CELL_WIDTH // 2 else 1)
            return
        week, column = event.y - _HEADER_LINES, event.x // _CELL_WIDTH
        weeks = self._weeks()
        if 0 <= week < len(weeks) and 0 <= column < len(weeks[week]):
            day = weeks[week][column]
            if day is not None and self._is_in_range(day):
                self.cursor = day
                self.picked.emit(day)

    def _move_to(self, day: datetime.date) -> None:
        self.cursor = self._in_range(day)
        self.refresh()

    def _is_in_range(self, day: datetime.date) -> bool:
        return (self.minimum is None or day >= self.minimum) and (
            self.maximum is None or day <= self.maximum
        )

    def _in_range(self, day: datetime.date) -> datetime.date:
        if self.minimum is not None and day < self.minimum:
            return self.minimum
        if self.maximum is not None and day > self.maximum:
            return self.maximum
        return day


class ComposeCalendar(ModalScreen[Optional[datetime.date]]):
    """A month grid over the app: dismissed with the day picked, or None on Escape."""

    BINDINGS: ClassVar[list[BindingType]] = [Binding("escape", "dismiss_none", show=False)]

    DEFAULT_CSS = """
    ComposeCalendar {
        align: center middle;
        & ComposeMonth {
            border: round $accent;
            padding: 0 1;
            width: 25;
            height: 10;
            background: $surface;
        }
    }
    """

    def __init__(self, month: ComposeMonth) -> None:
        super().__init__()
        self.month = month
        month.picked.connect(self._dismiss_with)

    def compose(self) -> ComposeResult:
        with Middle(), Center():
            yield self.month

    def on_mount(self) -> None:
        self.month.focus()

    def action_dismiss_none(self) -> None:
        self.dismiss(None)

    def _dismiss_with(self, day: datetime.date) -> None:
        self.dismiss(day)


class _DateValidator(Validator):
    """A date as the field's format says, within its range; no date at all is valid too."""

    def __init__(self, field: ComposeDateInput) -> None:
        super().__init__()
        self.field = field

    def validate(self, value: str) -> ValidationResult:
        if value.strip() == "":
            return self.success()
        try:
            date = parse_date(value, self.field.date_format)
        except ValueError:
            return self.failure()
        minimum, maximum = self.field.minimum, self.field.maximum
        if (minimum is not None and date < minimum) or (maximum is not None and date > maximum):
            return self.failure()
        return self.success()


class ComposeDateInput(Horizontal):
    """A field typing a date as `date_format` says, then a button opening a calendar.

    `date_edited` reports the user's dates, typed or picked, and None once the field is
    emptied: never a date set in code (`set_date`), though Textual posts its field's
    changes either way. Text that isn't a date, or a date out of range, marks the field
    invalid; text that isn't a date reports nothing, and leaving the field puts the date
    back.
    """

    DEFAULT_CSS = """
    ComposeDateInput {
        height: auto;
        & > ComposeInput {
            width: 1fr;
        }
        & > Button {
            min-width: 5;
            width: 5;
        }
        &.-row-invalid > ComposeInput {
            border: tall $error 60%;
            &:focus {
                border: tall $error;
            }
        }
    }
    """

    def __init__(self) -> None:
        self.input = ComposeInput(validators=[])
        self.button = Button("▾")
        super().__init__(self.input, self.button)
        self.input.validators.append(_DateValidator(self))
        self.date_format = ISO_DATE_FORMAT
        self.minimum: datetime.date | None = None
        self.maximum: datetime.date | None = None
        self.month_names: list[str] = []
        self.day_names: list[str] = []
        self._date: datetime.date | None = None
        self.date_edited: Signal[datetime.date | None] = Signal()
        self.input.value_changed.connect(self._read_text)
        self.input.value_submitted.connect(self._show_date)

    def date(self) -> datetime.date | None:
        return self._date

    def set_date(self, value: datetime.date | None) -> None:
        self._date = value
        self._show_date()

    def set_date_format(self, date_format: str) -> None:
        self.date_format = date_format
        self._show_date()

    def open_calendar(self) -> None:
        """Show the calendar on the date, else on today."""
        month = ComposeMonth(
            self._date, self.minimum, self.maximum, self.month_names, self.day_names
        )
        self.app.push_screen(ComposeCalendar(month), self._pick)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.open_calendar()

    def _pick(self, value: datetime.date | None) -> None:
        if value is not None:
            self._edit(value)
            self._show_date()
        self.input.focus()

    def _read_text(self, text: str) -> None:
        if text.strip() == "":
            self._edit(None)
            return
        try:
            value = parse_date(text, self.date_format)
        except ValueError:
            return  # not a date yet, e.g. halfway through typing one
        self._edit(value)

    def _edit(self, value: datetime.date | None) -> None:
        if value != self._date:
            self._date = value
            self.date_edited.emit(value)

    def _show_date(self) -> None:
        text = "" if self._date is None else format_date(self._date, self.date_format)
        if self.input.value != text:
            self.input.value = text

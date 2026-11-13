"""A range slider with two handles, and a date range of two date fields."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, Optional

from rich.text import Text
from textual.binding import Binding, BindingType
from textual.containers import Horizontal
from textual.widgets import Label

from composeui.core.signal import Signal
from composeui.core.view import RANGE_DASH, SliderMixin
from composeui.textualcore.widgets.composedateinput import ComposeDateInput
from composeui.textualcore.widgets.composeslider import DragReportMixin

if TYPE_CHECKING:
    import datetime

    from textual import events
    from textual.app import ComposeResult, RenderResult


class ComposeRangeSlider(DragReportMixin, can_focus=True):
    """A slider with a low and a high handle, from `first` by `step`, its ends on the right.

    As `ComposeSlider`, its positions count steps (0 to `last`) and it is three lines tall.
    A click moves the nearest handle, and a drag moves it under the mouse. The arrow keys,
    Page Up/Down, move the last handle pressed (the low one at first); Home moves the low
    one to the start, End the high one to the end. A handle stops on the other. `moved`
    reports the user's moves only, with both positions: a drag's once the handle rests, and
    on release (see `DragReportMixin`).
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("left,down", "move(-1)", "Decrease", show=False),
        Binding("right,up", "move(1)", "Increase", show=False),
        Binding("pagedown", "move_page(-1)", show=False),
        Binding("pageup", "move_page(1)", show=False),
        Binding("home", "move_to_end(0)", show=False),
        Binding("end", "move_to_end(1)", show=False),
    ]

    COMPONENT_CLASSES: ClassVar[set[str]] = {
        "slider--value",
        "slider--filled",
        "slider--handle",
        "slider--active-handle",
        "slider--empty",
    }

    # a form row's field while the row is invalid (see `ROW_INVALID_CLASS`)
    DEFAULT_CSS = """
    ComposeRangeSlider {
        height: 3;
        width: 1fr;
        padding: 1 1;
        & > .slider--filled {
            color: $primary;
        }
        & > .slider--handle, & > .slider--active-handle {
            color: $primary;
        }
        & > .slider--empty {
            color: $foreground 30%;
        }
        &:focus > .slider--active-handle {
            color: $accent;
            text-style: bold;
        }
        &.-row-invalid > .slider--filled, &.-row-invalid > .slider--handle,
        &.-row-invalid > .slider--active-handle {
            color: $error;
        }
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.first: float = 0
        self.step: float = 1
        #: the arithmetic of the steps: `SliderMixin`, or `FloatSliderMixin` for decimals
        self.steps: Any = SliderMixin
        self.last = 0
        self.low = 0
        self.high = 0
        #: the handle the keys move: 0 the low one, 1 the high one
        self.active = 0
        self._is_dragging = False
        self.moved: Signal[int, int] = Signal()

    def _text_at(self, position: int) -> str:
        value = self.steps.value_at(position, self.first, self.step)
        return self.steps.shown_text(value, self.first, self.step)  # type: ignore[no-any-return]

    def ends_text(self) -> str:
        return self._text_at(self.low) + RANGE_DASH + self._text_at(self.high)

    def set_steps(self, first: float, step: float, last: int, low: int, high: int) -> None:
        """Show `low` and `high` out of `last` steps of `step` from `first`, without `moved`."""
        self._drop_report()
        self.first, self.step, self.last = first, step, last
        self.low, self.high = low, high
        self.refresh()

    def render(self) -> RenderResult:
        width = self._track_width()
        if width <= 0:
            return ""
        low, high = self._handle_column(self.low, width), self._handle_column(self.high, width)
        empty = self.get_component_rich_style("slider--empty")
        handles = [
            self.get_component_rich_style(
                "slider--active-handle" if handle == self.active else "slider--handle"
            )
            for handle in (0, 1)
        ]
        text = Text(no_wrap=True, overflow="crop")
        text.append("─" * low, style=empty)
        text.append("●", style=handles[0])
        if high > low:
            fill = self.get_component_rich_style("slider--filled")
            text.append("━" * (high - low - 1), style=fill)
            text.append("●", style=handles[1])
        text.append("─" * (width - high - 1), style=empty)
        ends = self.ends_text().rjust(self._slot_width())
        text.append(f" {ends}", style=self.get_component_rich_style("slider--value"))
        return text

    def _slot_width(self) -> int:
        widest = max(len(self._text_at(0)), len(self._text_at(self.last)))
        return 2 * widest + len(RANGE_DASH)

    def _track_width(self) -> int:
        """Get the track's columns: the content's, less the ends' slot and a space."""
        return self.content_size.width - self._slot_width() - 1

    def _handle_column(self, position: int, width: int) -> int:
        return 0 if self.last == 0 else round(position * (width - 1) / self.last)

    def action_move(self, steps: int) -> None:
        self._move_active((self.low, self.high)[self.active] + steps)

    def action_move_page(self, direction: int) -> None:
        page = max(1, self.last // 10)
        self._move_active((self.low, self.high)[self.active] + direction * page)

    def action_move_to_end(self, end: int) -> None:
        self.active = end
        self._move_active(end * self.last)

    def on_mouse_down(self, event: events.MouseDown) -> None:
        position = self._position_at(event.get_content_offset_capture(self).x)
        if position is None:
            return  # no track to press on
        if self.low == self.high:
            # on one another: the one on the side of the click; on them, the one that can
            # move away from the end they are near, as the web's does
            if position == self.low:
                self.active = 0 if self.low > self.last / 2 else 1
            else:
                self.active = 0 if position < self.low else 1
        else:
            self.active = 0 if abs(position - self.low) <= abs(position - self.high) else 1
        self._is_dragging = True
        self.capture_mouse()
        self._move_active(position, is_drag=True)

    def on_mouse_move(self, event: events.MouseMove) -> None:
        position = self._position_at(event.get_content_offset_capture(self).x)
        if self._is_dragging and position is not None:
            self._move_active(position, is_drag=True)

    def on_mouse_up(self, _event: events.MouseUp) -> None:
        self._is_dragging = False
        self.release_mouse()
        self._report_rested()

    def _position_at(self, column: int) -> Optional[int]:
        """Get the position under `column`; None without a track, too narrow to draw one."""
        width = self._track_width()
        return None if width <= 1 else round(column * self.last / (width - 1))

    def _move_active(self, position: int, *, is_drag: bool = False) -> None:
        """Move the active handle to `position`, stopping on the other one and in range.

        A drag's move is reported once the handle rests, any other at once.
        """
        position = min(max(0, position), self.last)
        if self.active == 0:
            low, high = min(position, self.high), self.high
        else:
            low, high = self.low, max(position, self.low)
        if (low, high) != (self.low, self.high):
            self.low, self.high = low, high
            if is_drag:
                self._report_later()
            else:
                self._report()
        self.refresh()  # the active handle shows its focus

    def _report(self) -> None:
        self._drop_report()
        self.moved.emit(self.low, self.high)


class ComposeDateRangeInput(Horizontal):
    """Two date fields, the start and the end of a range, with a dash between them.

    `end_edited` reports the user's dates for an end: its index (0 the start, 1 the end)
    and the date, None once the field is emptied.
    """

    DEFAULT_CSS = """
    ComposeDateRangeInput {
        height: auto;
        & > ComposeDateInput {
            width: 1fr;
        }
        & > Label {
            padding: 1 1;
        }
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.start = ComposeDateInput()
        self.end = ComposeDateInput()
        self.end_edited: Signal[int, Optional[datetime.date]] = Signal()
        self.start.date_edited.connect(self._start_edited)
        self.end.date_edited.connect(self._end_edited)

    @property
    def fields(self) -> tuple[ComposeDateInput, ComposeDateInput]:
        return self.start, self.end

    def compose(self) -> ComposeResult:
        yield self.start
        yield Label(RANGE_DASH.strip())
        yield self.end

    def _start_edited(self, value: Optional[datetime.date]) -> None:
        self.end_edited.emit(0, value)

    def _end_edited(self, value: Optional[datetime.date]) -> None:
        self.end_edited.emit(1, value)

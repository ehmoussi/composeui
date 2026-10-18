from typing import ClassVar

from rich.text import Text
from textual import events
from textual.app import RenderResult
from textual.binding import Binding, BindingType
from textual.widget import Widget

from composeui.core.signal import Signal


class ComposeSlider(Widget, can_focus=True):
    """A slider from `first` by `step`, its value on the line above the handle.

    Textual has none. Its positions count steps (0 to `last`), so the handle only stops
    on a step. The arrow keys move it a step, Page Up/Down a tenth of the way, Home/End
    to an end; a click or a drag moves it under the mouse. `moved` reports the user's
    moves only, as Qt's renderers block their widget's signals while refreshing it.
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
        "slider--empty",
    }

    # a form row's field while the row is invalid (see `ROW_INVALID_CLASS`)
    DEFAULT_CSS = """
    ComposeSlider {
        height: 2;
        width: 1fr;
        & > .slider--value {
            text-style: bold;
        }
        & > .slider--filled {
            color: $primary;
        }
        & > .slider--handle {
            color: $primary;
        }
        & > .slider--empty {
            color: $foreground 30%;
        }
        &:focus > .slider--handle {
            color: $accent;
            text-style: bold;
        }
        &.-row-invalid > .slider--filled, &.-row-invalid > .slider--handle {
            color: $error;
        }
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.first = 0
        self.step = 1
        self.last = 0
        self.position = 0
        self._is_dragging = False
        self.moved: Signal[int] = Signal()

    @property
    def shown_value(self) -> int:
        return self.first + self.position * self.step

    def set_steps(self, first: int, step: int, last: int, position: int) -> None:
        """Show `position` out of `last` steps of `step` from `first`, without `moved`."""
        self.first, self.step, self.last, self.position = first, step, last, position
        self.refresh()

    def render(self) -> RenderResult:
        width = self.content_size.width
        if width <= 0:
            return ""
        handle = self._handle_column(width)
        value = str(self.shown_value)
        left = min(max(0, handle - len(value) // 2), max(0, width - len(value)))
        text = Text(no_wrap=True, overflow="crop")
        text.append(" " * left)
        text.append(value, style=self.get_component_rich_style("slider--value"))
        text.append("\n")
        text.append("━" * handle, style=self.get_component_rich_style("slider--filled"))
        text.append("●", style=self.get_component_rich_style("slider--handle"))
        empty = "─" * (width - handle - 1)
        text.append(empty, style=self.get_component_rich_style("slider--empty"))
        return text

    def _handle_column(self, width: int) -> int:
        return 0 if self.last == 0 else round(self.position * (width - 1) / self.last)

    def action_move(self, steps: int) -> None:
        self._move_to(self.position + steps)

    def action_move_page(self, direction: int) -> None:
        self._move_to(self.position + direction * max(1, self.last // 10))

    def action_move_to_end(self, end: int) -> None:
        self._move_to(end * self.last)

    def on_mouse_down(self, event: events.MouseDown) -> None:
        self._is_dragging = True
        self.capture_mouse()
        self._move_to_column(event.x)

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if self._is_dragging:
            self._move_to_column(event.x)

    def on_mouse_up(self, _event: events.MouseUp) -> None:
        self._is_dragging = False
        self.release_mouse()

    def _move_to_column(self, column: int) -> None:
        width = self.content_size.width
        if width > 1:
            self._move_to(round(column * self.last / (width - 1)))

    def _move_to(self, position: int) -> None:
        position = min(max(0, position), self.last)
        if position != self.position:
            self.position = position
            self.refresh()
            self.moved.emit(self.shown_value)

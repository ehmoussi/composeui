from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from textual.binding import Binding, BindingType
from textual.containers import Container
from textual.widget import Widget

from composeui.core.signal import Signal

if TYPE_CHECKING:
    from textual import events
    from textual.geometry import Size
    from textual.layout import DockArrangeResult
    from textual.visual import VisualType

#: the narrowest (or shortest) a pane gets, in cells
MINIMUM_PANE_LENGTH = 3


class SplitterHandle(Widget, can_focus=True):
    """The border between two panes: dragged, or moved with the arrow keys once focused."""

    DEFAULT_CSS = """
    SplitterHandle {
        width: 1;
        /* as tall as the tallest pane: 1fr would take the screen's spare height */
        height: 100%;
        min-height: 1;
        color: $foreground-darken-3;
    }
    SplitterHandle:hover, SplitterHandle.-dragging {
        color: $accent;
    }
    SplitterHandle:focus {
        background: $accent 30%;
        color: $accent;
    }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("left", "move(-1, False)", "Narrow the pane before", show=False),
        Binding("right", "move(1, False)", "Widen the pane before", show=False),
        Binding("up", "move(-1, True)", "Shorten the pane above", show=False),
        Binding("down", "move(1, True)", "Lengthen the pane above", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        #: where the drag started, on the screen, and the panes' lengths then
        self._drag_start: tuple[int, list[int]] | None = None
        #: the panes' lengths as the drag left them, before they're laid out
        self._dragged_lengths: list[int] = []

    def render(self) -> VisualType:
        if self.splitter.is_vertical:
            return "─" * max(self.size.width, 1)
        return "\n".join("│" * max(self.size.height, 1))

    @property
    def splitter(self) -> ComposeSplitter:
        parent = self.parent
        assert isinstance(parent, ComposeSplitter)
        return parent

    def _position(self, event: events.MouseEvent) -> int:
        """Get where `event` is on the screen, along the splitter."""
        return event.screen_y if self.splitter.is_vertical else event.screen_x

    def on_mouse_down(self, event: events.MouseDown) -> None:
        self.capture_mouse()
        self.add_class("-dragging")
        lengths = self.splitter.pane_lengths()
        self._drag_start, self._dragged_lengths = (self._position(event), lengths), lengths
        event.stop()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if self._drag_start is not None:
            start, lengths = self._drag_start
            self._dragged_lengths = self.splitter.move_border(
                self, lengths, self._position(event) - start
            )

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if self._drag_start is not None:
            self._drag_start = None
            self.release_mouse()
            self.remove_class("-dragging")
            self.splitter.resized.emit(self._dragged_lengths)
            event.stop()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        # the keys along the splitter only: the others still scroll the screen
        if action == "move":
            return parameters[1] == self.splitter.is_vertical
        return True  # pragma: no cover - Textual asks a widget about its own bindings only

    def action_move(self, cells: int, _is_vertical: Any) -> None:
        splitter = self.splitter
        splitter.resized.emit(splitter.move_border(self, None, cells))


class ComposeSplitter(Container):
    """Panes in a row (or a column), each its share of it, a handle between two to drag.

    Only the panes shown have a handle before them, past the first, so a hidden pane
    leaves no border behind. `resized` reports the panes' widths (heights, vertical), in
    cells (0 for a hidden one), once the user moved a border, not when `set_sizes`
    shares them in code. Vertical, it is 24 rows tall, each pane scrolling within its
    share.
    """

    DEFAULT_CSS = """
    ComposeSplitter {
        layout: horizontal;
        height: auto;
    }
    ComposeSplitter.-vertical {
        layout: vertical;
        height: 24;
    }
    /* here: a handle's own CSS is scoped to the handle, so can't select its splitter */
    ComposeSplitter.-vertical > SplitterHandle {
        width: 100%;
        height: 1;
    }
    """

    def __init__(self, *panes: Widget, is_vertical: bool = False) -> None:
        self.panes = list(panes)
        self.is_vertical = is_vertical
        self._pending_lengths: list[int] | None = None
        children: list[Widget] = []
        for index, pane in enumerate(self.panes):
            if index > 0:
                children.append(SplitterHandle())
            if is_vertical:
                pane.styles.overflow_y = "auto"
            children.append(pane)
        super().__init__(*children, classes="-vertical" if is_vertical else "")
        self.resized: Signal[list[int]] = Signal()

    def set_sizes(self, sizes: list[int]) -> None:
        """Share the splitter between the panes in proportion to `sizes`."""
        self._pending_lengths = None
        for pane, size in zip(self.panes, sizes):
            self._set_length(pane, size)

    def pane_lengths(self) -> list[int]:
        """Get the panes' widths (heights, vertical), in cells; 0 for a hidden one."""
        return [
            (pane.outer_size.height if self.is_vertical else pane.outer_size.width)
            if pane.display
            else 0
            for pane in self.panes
        ]

    def move_border(
        self,
        handle: SplitterHandle,
        lengths: list[int] | None,
        cells: int,
    ) -> list[int]:
        """Move `handle` by `cells` from where it was with the panes `lengths` long.

        Returns the panes' lengths once moved, which they take once laid out again.
        If ``lengths`` is None, use the last move pending layout, or the current lengths.
        """
        if lengths is None:
            # Rapid keys must build on the last move, not the layout before it.
            lengths = self._pending_lengths or self.pane_lengths()
        after = self._pane_after(handle)
        shown_before = [index for index in range(after) if self.panes[index].display]
        if len(shown_before) == 0:
            return lengths
        before = shown_before[-1]
        # each keeps a few cells: a pane dragged to nothing would be lost to the user
        cells = max(cells, MINIMUM_PANE_LENGTH - lengths[before])
        cells = min(cells, lengths[after] - MINIMUM_PANE_LENGTH)
        moved = list(lengths)
        moved[before] += cells
        moved[after] -= cells
        self._pending_lengths = moved
        # in proportion to their cells: the screen's size, as it changes, shared alike
        for pane, length in zip(self.panes, moved):
            if pane.display:
                self._set_length(pane, max(length, 1))
        return moved

    def _set_length(self, pane: Widget, share: int) -> None:
        if self.is_vertical:
            pane.styles.height = f"{share}fr"
        else:
            pane.styles.width = f"{share}fr"

    def _pane_after(self, handle: SplitterHandle) -> int:
        return self.children.index(handle) // 2 + 1

    def arrange(self, size: Size, optimal: bool = False) -> DockArrangeResult:  # noqa: FBT002
        # a handle shows before each pane shown, past the first: as a pane is shown or
        # hidden, which this lays out again
        handles = [child for child in self.children if isinstance(child, SplitterHandle)]
        has_shown = False
        for index, pane in enumerate(self.panes):
            if index > 0:
                shows = has_shown and bool(pane.display)
                if handles[index - 1].display != shows:
                    handles[index - 1].display = shows
            has_shown = has_shown or bool(pane.display)
        arranged = super().arrange(size, optimal)
        self._pending_lengths = None
        return arranged

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from textual.binding import Binding, BindingType
from textual.containers import Horizontal
from textual.widget import Widget

from composeui.core.signal import Signal

if TYPE_CHECKING:
    from textual import events
    from textual.geometry import Size
    from textual.layout import DockArrangeResult
    from textual.visual import VisualType

#: the narrowest a pane gets, in cells
MINIMUM_PANE_WIDTH = 3


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
        Binding("left", "move(-1)", "Narrow the left pane", show=False),
        Binding("right", "move(1)", "Widen the left pane", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        #: where the drag started, on the screen, and the panes' widths then
        self._drag_start: tuple[int, list[int]] | None = None
        #: the panes' widths as the drag left them, before they're laid out
        self._dragged_widths: list[int] = []

    def render(self) -> VisualType:
        return "\n".join("│" * max(self.size.height, 1))

    @property
    def splitter(self) -> ComposeSplitter:
        parent = self.parent
        if not isinstance(parent, ComposeSplitter):
            raise TypeError(parent)
        return parent

    def on_mouse_down(self, event: events.MouseDown) -> None:
        self.capture_mouse()
        self.add_class("-dragging")
        widths = self.splitter.pane_widths()
        self._drag_start, self._dragged_widths = (event.screen_x, widths), widths
        event.stop()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if self._drag_start is not None:
            start, widths = self._drag_start
            self._dragged_widths = self.splitter.move_border(self, widths, event.screen_x - start)

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if self._drag_start is not None:
            self._drag_start = None
            self.release_mouse()
            self.remove_class("-dragging")
            self.splitter.resized.emit(self._dragged_widths)
            event.stop()

    def action_move(self, cells: int) -> None:
        splitter = self.splitter
        splitter.resized.emit(splitter.move_border(self, splitter.pane_widths(), cells))


class ComposeSplitter(Horizontal):
    """Panes side by side, each as wide as its share, a handle between two the user drags.

    Only the panes shown have a handle before them, past the first, so a hidden pane
    leaves no border behind. `resized` reports the panes' widths, in cells (0 for a hidden
    one), once the user moved a border, not when `set_sizes` shares them in code.
    """

    DEFAULT_CSS = """
    ComposeSplitter {
        height: auto;
    }
    """

    def __init__(self, *panes: Widget) -> None:
        self.panes = list(panes)
        children: list[Widget] = []
        for index, pane in enumerate(self.panes):
            if index > 0:
                children.append(SplitterHandle())
            children.append(pane)
        super().__init__(*children)
        self.resized: Signal[list[int]] = Signal()

    def set_sizes(self, sizes: list[int]) -> None:
        """Share the width between the panes in proportion to `sizes`."""
        for pane, size in zip(self.panes, sizes):
            pane.styles.width = f"{size}fr"

    def pane_widths(self) -> list[int]:
        """Get the panes' widths, in cells; 0 for a hidden one."""
        return [pane.outer_size.width if pane.display else 0 for pane in self.panes]

    def move_border(self, handle: SplitterHandle, widths: list[int], cells: int) -> list[int]:
        """Move `handle` by `cells` from where it was with the panes `widths` wide.

        Returns the panes' widths once moved, which they take once laid out again.
        """
        right = self._pane_after(handle)
        shown_before = [index for index in range(right) if self.panes[index].display]
        if len(shown_before) == 0:
            return widths
        left = shown_before[-1]
        # each keeps a few cells: a pane dragged to nothing would be lost to the user
        cells = max(cells, MINIMUM_PANE_WIDTH - widths[left])
        cells = min(cells, widths[right] - MINIMUM_PANE_WIDTH)
        moved = list(widths)
        moved[left] += cells
        moved[right] -= cells
        # in proportion to their cells: the screen's width, as it changes, shared alike
        for pane, width in zip(self.panes, moved):
            if pane.display:
                pane.styles.width = f"{max(width, 1)}fr"
        return moved

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
        return super().arrange(size, optimal)

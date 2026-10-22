"""A large table's widget: a scrolled view that asks its view for the lines it draws."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, Protocol

from rich.segment import Segment
from textual.geometry import Size
from textual.scroll_view import ScrollView
from textual.strip import Strip

if TYPE_CHECKING:
    from textual import events


class DataTableLike(Protocol):
    """What the widget reads from a `DataTableView`."""

    @property
    def headers(self) -> list[str]: ...
    @property
    def row_count(self) -> int: ...
    def rows(self, start: int, stop: int) -> list[tuple[Any, list[str]]]: ...


class ComposeDataTable(ScrollView, can_focus=True):
    """A large table: its headers on its first line, then a line per row, as scrolled.

    Textual asks for the lines it draws (`render_line`), and the view reads their rows
    from its source a window at a time: the widget keeps no row. The arrow keys, Page Up,
    Page Down, Home and End scroll. Each line starts with its row's position, from 1; the
    columns share the rest of the width, a cell too long cut short. `reset` shows a new
    order of the rows, `repaint` the same rows formatted again.
    """

    COMPONENT_CLASSES: ClassVar[set[str]] = {"data-table--header", "data-table--even-row"}
    DEFAULT_CSS = """
    ComposeDataTable {
        height: 1fr;
        min-height: 5;
        & > .data-table--header {
            text-style: bold;
            background: $panel;
        }
        & > .data-table--even-row {
            background: $surface-lighten-1;
        }
    }
    """

    def __init__(self, table: DataTableLike) -> None:
        super().__init__()
        self._table = table

    def reset(self) -> None:
        # the header's line, then the rows'
        self.virtual_size = Size(self.size.width, self._table.row_count + 1)
        self.refresh()

    def repaint(self) -> None:
        self.refresh()

    def on_resize(self, _event: events.Resize) -> None:
        self.virtual_size = Size(self.size.width, self._table.row_count + 1)

    def render_line(self, y: int) -> Strip:
        width = self.size.width
        number_width = len(f"{self._table.row_count:,}") + 1
        if y == 0:  # the headers stay on top, whatever the scroll
            text = self._line(" " * number_width, self._table.headers, width - number_width)
            return Strip([Segment(text, self.get_component_rich_style("data-table--header"))])
        row = round(self.scroll_offset.y) + y - 1
        rows = self._table.rows(row, row + 1)
        if len(rows) == 0:
            return Strip.blank(width, self.rich_style)
        position = f"{row + 1:,}".rjust(number_width - 1) + " "
        text = self._line(position, rows[0][1], width - number_width)
        style = self.rich_style
        if row % 2 == 1:
            style += self.get_component_rich_style("data-table--even-row")
        return Strip([Segment(text, style)])

    @staticmethod
    def _line(start: str, cells: list[str], width: int) -> str:
        """Get a line of `cells` after `start`, each in an equal share of `width`."""
        if len(cells) == 0:
            return start.ljust(len(start) + max(width, 0))
        share = max(width // len(cells), 1)
        parts = [
            (cell if len(cell) < share else cell[: max(share - 2, 0)] + "…").ljust(share)
            for cell in cells
        ]
        return (start + "".join(parts)).ljust(len(start) + max(width, 0))

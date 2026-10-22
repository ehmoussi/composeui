"""A large table's widget: a scrolled view that asks its view for the lines it draws."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, Protocol

from rich.segment import Segment
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.geometry import Size
from textual.scroll_view import ScrollView
from textual.strip import Strip
from textual.widgets import Static
from textual_fspicker import FileSave, Filters
from textual_fspicker.path_filters import Filter

from composeui.core.signal import Signal, SignalNoArgs
from composeui.textualcore.widgets.composefiltertable import ComposeFilterBar

if TYPE_CHECKING:
    from pathlib import Path

    from textual import events
    from textual.app import ComposeResult


#: the key exporting the rows shown as CSV
EXPORT_KEY = "e"


def _is_csv(path: Path) -> bool:
    return path.suffix.lower() == ".csv"


class DataTableLike(Protocol):
    """What the widget reads from a `DataTableView`."""

    @property
    def headers(self) -> list[str]: ...
    @property
    def row_count(self) -> int: ...
    def rows(self, start: int, stop: int) -> list[tuple[Any, list[str]]]: ...
    def is_selected(self, row_id: Any) -> bool: ...


class ComposeDataTable(ScrollView, can_focus=True):
    """A large table: its headers on its first line, then a line per row, as scrolled.

    Textual asks for the lines it draws (`render_line`), and the view reads their rows
    from its source a window at a time: the widget keeps no row. Each line starts with
    its row's position, from 1; the columns share the rest of the width, a cell too long
    cut short. `reset` shows a new order of the rows, `repaint` the same rows formatted
    or selected again.

    `header_clicked` emits the column whose header the user clicked; the header shows
    the order `set_sort` gives (▲ or ▼ after its header), the table never sorting its
    rows itself.

    A cursor marks a row, which the arrow keys, Page Up, Page Down, Home and End move,
    the table scrolling to keep it shown. The table selects no row itself: `row_clicked`
    emits the position of the row the user clicked, or the cursor's on Space, and whether
    Shift extends the selection to it; `row_activated` emits it on a double click or
    Enter. A selected row has the primary color. `copy_requested` emits on Ctrl+C. Its
    key `e` asks where to export the rows as CSV, which `export_path_chosen` emits.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("up", "move_cursor(-1)", "Up", show=False),
        Binding("down", "move_cursor(1)", "Down", show=False),
        Binding("pageup", "move_cursor('-page')", "Page up", show=False),
        Binding("pagedown", "move_cursor('page')", "Page down", show=False),
        Binding("home", "move_cursor('-all')", "First row", show=False),
        Binding("end", "move_cursor('all')", "Last row", show=False),
        Binding("space", "click_cursor(False)", "Select", show=False),
        Binding("shift+space", "click_cursor(True)", "Select up to", show=False),
        Binding("enter", "activate_cursor", "Activate", show=False),
        Binding("ctrl+c", "copy_rows", "Copy", show=False),
    ]
    COMPONENT_CLASSES: ClassVar[set[str]] = {
        "data-table--header",
        "data-table--even-row",
        "data-table--cursor",
        "data-table--selected",
    }
    DEFAULT_CSS = """
    ComposeDataTable {
        height: 1fr;
        min-height: 5;
        overflow-x: hidden;
        & > .data-table--header {
            text-style: bold;
            background: $panel;
        }
        & > .data-table--even-row {
            background: $surface-lighten-1;
        }
        & > .data-table--selected {
            background: $primary;
            color: $text;
        }
        & > .data-table--cursor {
            text-style: reverse;
        }
    }
    """

    def __init__(self, table: DataTableLike) -> None:
        super().__init__()
        self._table = table
        self._sort: tuple[int, bool] | None = None
        #: the position of the row the cursor marks
        self.cursor = 0
        self.header_clicked: Signal[int] = Signal()
        self.row_clicked: Signal[int, bool] = Signal()
        self.row_activated: Signal[int] = Signal()
        self.copy_requested: SignalNoArgs = SignalNoArgs()
        self.export_path_chosen: Signal[Path] = Signal()
        #: the name the export's dialog offers
        self.export_filename = "table.csv"
        self.set_export_text("Export CSV")

    def set_export_text(self, text: str) -> None:
        """Describe the key exporting the rows, e.g. in the app's footer."""
        self._bindings.key_to_bindings.pop(EXPORT_KEY, None)
        self._bindings.bind(EXPORT_KEY, "export", text)
        self.refresh_bindings()

    def action_export(self) -> None:
        dialog = FileSave(
            filters=Filters(Filter("CSV", _is_csv)), default_file=self.export_filename
        )
        self.app.push_screen(dialog, self._export_path_chosen)

    def _export_path_chosen(self, path: Path | None) -> None:
        if path is not None:
            self.export_path_chosen.emit(
                path if _is_csv(path) else path.with_name(f"{path.name}.csv")
            )

    def set_sort(self, sort: tuple[int, bool] | None) -> None:
        """Show the order: by a column, descending or not; None for the source's own."""
        self._sort = sort
        self.refresh()

    def action_move_cursor(self, step: int | str) -> None:
        """Move the cursor by `step` rows, a page of them (``"page"``) or to an end."""
        steps = {"page": self._shown_rows(), "-page": -self._shown_rows()}
        steps.update({"all": self._table.row_count, "-all": -self._table.row_count})
        count = int(steps.get(step, step) if isinstance(step, str) else step)
        self.cursor = min(max(self.cursor + count, 0), max(self._table.row_count - 1, 0))
        self._show_cursor()

    def action_click_cursor(self, is_extended: bool) -> None:
        if self.cursor < self._table.row_count:
            self.row_clicked.emit(self.cursor, is_extended)

    def action_copy_rows(self) -> None:
        self.copy_requested.emit()

    def action_activate_cursor(self) -> None:
        if self.cursor < self._table.row_count:
            self.row_activated.emit(self.cursor)

    def on_click(self, event: events.Click) -> None:
        if event.y > 0:
            row = round(self.scroll_offset.y) + event.y - 1
            if row < self._table.row_count:
                self.cursor = row
                self.refresh()
                if event.chain == 2:  # noqa: PLR2004 (a double click)
                    self.row_activated.emit(row)
                else:
                    self.row_clicked.emit(row, event.shift)
            return
        number_width = self._number_width()
        count = len(self._table.headers)
        if count == 0 or event.x < number_width:
            return
        share = max((self._width() - number_width) // count, 1)
        column = (event.x - number_width) // share
        if column < count:
            self.header_clicked.emit(column)

    def reset(self) -> None:
        # the header's line, then the rows'
        self.virtual_size = Size(self._width(), self._table.row_count + 1)
        self.cursor = min(self.cursor, max(self._table.row_count - 1, 0))
        self.refresh()

    def repaint(self) -> None:
        self.refresh()

    def on_resize(self, _event: events.Resize) -> None:
        self.virtual_size = Size(self._width(), self._table.row_count + 1)

    def render_line(self, y: int) -> Strip:
        width = self._width()
        number_width = self._number_width()
        if y == 0:  # the headers stay on top, whatever the scroll
            headers = list(self._table.headers)
            if self._sort is not None and self._sort[0] < len(headers):
                column, is_descending = self._sort
                headers[column] += " ▼" if is_descending else " ▲"
            text = self._line(" " * number_width, headers, width - number_width)
            return Strip([Segment(text, self.get_component_rich_style("data-table--header"))])
        row = round(self.scroll_offset.y) + y - 1
        rows = self._table.rows(row, row + 1)
        if len(rows) == 0:
            return Strip.blank(width, self.rich_style)
        row_id, cells = rows[0]
        position = f"{row + 1:,}".rjust(number_width - 1) + " "
        text = self._line(position, cells, width - number_width)
        style = self.rich_style
        if self._table.is_selected(row_id):
            style += self.get_component_rich_style("data-table--selected")
        elif row % 2 == 1:
            style += self.get_component_rich_style("data-table--even-row")
        if row == self.cursor and self.has_focus:
            style += self.get_component_rich_style("data-table--cursor")
        return Strip([Segment(text, style)])

    def _shown_rows(self) -> int:
        """Get the number of rows shown at once, under the headers' line."""
        return max(self.scrollable_content_region.height - 1, 1)

    def _show_cursor(self) -> None:
        """Scroll as little as needed for the cursor's row to show."""
        top = round(self.scroll_offset.y)
        if self.cursor < top:
            self.scroll_to(y=self.cursor, animate=False)
        elif self.cursor >= top + self._shown_rows():
            self.scroll_to(y=self.cursor - self._shown_rows() + 1, animate=False)
        self.refresh()

    def _width(self) -> int:
        """Get the width of the lines: the widget's, but its vertical scroll bar's."""
        return self.scrollable_content_region.width

    def _number_width(self) -> int:
        """Get the width of the rows' positions, before their cells."""
        return len(f"{self._table.row_count:,}") + 1

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


class ComposeDataFilterTable(Vertical):
    """A large table under its filter bar, which shows only while a column filters.

    When the search or the filters hide every row, `empty` says so under the headers.
    """

    DEFAULT_CSS = """
    ComposeDataFilterTable {
        height: 1fr;
        & > Static.empty {
            color: $text-muted;
            text-align: center;
            width: 1fr;
        }
    }
    """

    def __init__(self, table: DataTableLike) -> None:
        super().__init__()
        self.bar = ComposeFilterBar()
        self.bar.display = False
        self.table = ComposeDataTable(table)
        self.empty = Static("", classes="empty")
        self.empty.display = False

    def compose(self) -> ComposeResult:
        yield self.bar
        yield self.table
        yield self.empty

from rich.text import Text
from textual import events
from textual.coordinate import Coordinate
from textual.widgets import DataTable

from composeui.core.signal import Signal

#: the first column's cell of a selected row, in a table selecting several rows
_CHECK = "✓"


class ComposeTable(DataTable[Text]):
    """A read-only table of text where the user selects rows, like Qt's `QTextTableView`.

    Selecting one row, the row cursor is the selection: hidden while nothing is
    selected, shown once the user clicks a row or presses Enter. Selecting several
    (`set_multiple_selection`), the cursor only moves, and a click or Enter adds or
    removes its row, checked in a first column of its own: the cursor can't show
    several rows. `selected_rows_changed` emits the selected rows, in order, only when
    the user changes them, re-emitting `DataTable`'s messages through a plain composeui
    `Signal` a renderer can connect to (see `ComposeRadioSet`).
    """

    def __init__(self) -> None:
        super().__init__(cursor_type="row", show_cursor=False, zebra_stripes=True)
        self.selected_rows_changed: Signal[list[int]] = Signal()
        self._selected_rows: list[int] = []
        self._is_multiple = False
        self._headers: list[str] = []
        self._rows: list[list[str]] = []

    def fill(self, headers: list[str], rows: list[list[str]]) -> None:
        """Rebuild the whole table, as plain text: a string cell would be read as markup."""
        self._headers, self._rows = headers, rows
        self.clear(columns=True)
        check = [""] if self._is_multiple else []
        self.add_columns(*(Text(header) for header in [*check, *headers]))
        self.add_rows([Text(cell) for cell in [*check, *row]] for row in rows)
        # clearing moved the cursor back to the first row
        self.set_selected_rows(self._selected_rows)

    def set_multiple_selection(self, *, is_multiple: bool) -> None:
        if is_multiple != self._is_multiple:
            self._is_multiple = is_multiple
            self.fill(self._headers, self._rows)  # with or without the check column

    def selected_rows(self) -> list[int]:
        return self._selected_rows

    def set_selected_rows(self, rows: list[int]) -> None:
        self._selected_rows = rows
        if self._is_multiple:
            for row in range(self.row_count):
                self._show_checked(row)
            return
        self.show_cursor = len(rows) > 0
        if len(rows) > 0:
            self.move_cursor(row=rows[0], animate=False)

    def on_click(self, event: events.Click) -> None:
        # runs before `DataTable`'s own click handler, which only moves a shown cursor
        row = event.style.meta.get("row", -1)
        if row >= 0:
            self.show_cursor = True
            if self._is_multiple:
                self._toggle(row)

    def action_select_cursor(self) -> None:
        if self._is_multiple and self.show_cursor:
            self._toggle(self.cursor_row)
        self.show_cursor = True
        super().action_select_cursor()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self._select(event.cursor_row)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self._select(event.cursor_row)

    def _select(self, row: int) -> None:
        # selecting several rows, only a click or Enter selects, never moving the cursor
        if self._is_multiple:
            return
        # a message about a cursor since moved (e.g. by `fill`) or still hidden is stale
        if self.show_cursor and row == self.cursor_row and self._selected_rows != [row]:
            self._selected_rows = [row]
            self.selected_rows_changed.emit([row])

    def _toggle(self, row: int) -> None:
        if row >= self.row_count:
            return
        selected = set(self._selected_rows) ^ {row}
        self._selected_rows = sorted(selected)
        self._show_checked(row)
        self.selected_rows_changed.emit(self._selected_rows)

    def _show_checked(self, row: int) -> None:
        check = _CHECK if row in self._selected_rows else ""
        self.update_cell_at(Coordinate(row, 0), Text(check), update_width=True)

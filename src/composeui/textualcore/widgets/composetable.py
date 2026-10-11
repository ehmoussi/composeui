from typing import Optional

from rich.text import Text
from textual import events
from textual.widgets import DataTable

from composeui.core.signal import Signal


class ComposeTable(DataTable[Text]):
    """A read-only table of text where the user selects one row, like Qt's `QTextTableView`.

    The row cursor is the selection: hidden while nothing is selected, shown once the
    user clicks a row or presses Enter. `selected_row_changed` emits the selected row
    only when the user changes it, re-emitting `DataTable`'s messages through a plain
    composeui `Signal` a renderer can connect to (see `ComposeRadioSet`).
    """

    def __init__(self) -> None:
        super().__init__(cursor_type="row", show_cursor=False, zebra_stripes=True)
        self.selected_row_changed: Signal[Optional[int]] = Signal()
        self._selected_row: Optional[int] = None

    def fill(self, headers: list[str], rows: list[list[str]]) -> None:
        """Rebuild the whole table, as plain text: a string cell would be read as markup."""
        self.clear(columns=True)
        self.add_columns(*(Text(header) for header in headers))
        self.add_rows([Text(cell) for cell in row] for row in rows)
        # clearing moved the cursor back to the first row
        self.set_selected_row(self._selected_row)

    def selected_row(self) -> Optional[int]:
        return self._selected_row

    def set_selected_row(self, row: Optional[int]) -> None:
        self._selected_row = row
        self.show_cursor = row is not None
        if row is not None:
            self.move_cursor(row=row, animate=False)

    def on_click(self, event: events.Click) -> None:
        # runs before `DataTable`'s own click handler, which only moves a shown cursor
        if event.style.meta.get("row", -1) >= 0:
            self.show_cursor = True

    def action_select_cursor(self) -> None:
        self.show_cursor = True
        super().action_select_cursor()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self._select(event.cursor_row)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self._select(event.cursor_row)

    def _select(self, row: int) -> None:
        # a message about a cursor since moved (e.g. by `fill`) or still hidden is stale
        if self.show_cursor and row == self.cursor_row and row != self._selected_row:
            self._selected_row = row
            self.selected_row_changed.emit(row)

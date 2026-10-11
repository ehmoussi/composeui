from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Optional

from rich.text import Text
from textual.binding import Binding
from textual.containers import Vertical
from textual.coordinate import Coordinate
from textual.screen import ModalScreen
from textual.widgets import DataTable, Input, Label

from composeui.core.signal import Signal
from composeui.core.view import replace_cell

if TYPE_CHECKING:
    from textual import events
    from textual.app import ComposeResult
    from textual.binding import BindingType

#: the first column's cell of a selected row, in a table selecting several rows
_CHECK = "✓"
#: `events.Click.chain` of a double click's second click
_DOUBLE_CLICK = 2


class ComposeRowEditor(ModalScreen[Optional[dict[int, str]]]):
    """A modal editing a row's editable cells, one input each under its header.

    Enter in any input dismisses it with every cell's text by column, Escape with None.
    """

    DEFAULT_CSS = """
    ComposeRowEditor {
        align: center middle;
    }
    ComposeRowEditor > Vertical {
        width: 60;
        max-width: 90%;
        height: auto;
        padding: 1 2;
        border: thick $primary 80%;
        background: $surface;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [Binding("escape", "dismiss_editor", "Close")]

    def __init__(self, cells: dict[int, tuple[str, str]], focused: int) -> None:
        """`cells` maps each editable column to its header and text."""
        super().__init__()
        self.inputs = {column: Input(text) for column, (_header, text) in cells.items()}
        self._headers = {column: header for column, (header, _text) in cells.items()}
        self._focused = focused

    def compose(self) -> ComposeResult:
        with Vertical():
            for column, cell_input in self.inputs.items():
                yield Label(self._headers[column])
                yield cell_input

    def on_mount(self) -> None:
        self.inputs[self._focused].focus()

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        self.dismiss({column: cell.value for column, cell in self.inputs.items()})

    def action_dismiss_editor(self) -> None:
        self.dismiss(None)


class ComposeTable(DataTable[Text]):
    """A table of text where the user selects rows, like Qt's `QTextTableView`.

    Selecting one row, the row cursor is the selection: hidden while nothing is
    selected, shown once the user clicks a row or presses Enter. Selecting several
    (`set_multiple_selection`), the cursor only moves, and a click or Enter adds or
    removes its row, checked in a first column of its own: the cursor can't show
    several rows. `selected_rows_changed` emits the selected rows, in order, only when
    the user changes them, re-emitting `DataTable`'s messages through a plain composeui
    `Signal` a renderer can connect to (see `ComposeRadioSet`).

    The user edits the cells of `editable_columns` in a `ComposeRowEditor`: F2 opens it
    on the cursor's row, a double click on the clicked cell's. `cell_edited` emits each
    cell the user changed: its row, its column (without the check column) and its text.
    """

    BINDINGS: ClassVar[list[BindingType]] = [Binding("f2", "edit_row", "Edit")]

    def __init__(self) -> None:
        super().__init__(cursor_type="row", show_cursor=False, zebra_stripes=True)
        self.selected_rows_changed: Signal[list[int]] = Signal()
        self.cell_edited: Signal[int, int, str] = Signal()
        self.editable_columns: list[int] = []
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
        if row < 0:
            return
        self.show_cursor = True
        if self._is_multiple:
            self._toggle(row)
        column = event.style.meta.get("column", -1) - (1 if self._is_multiple else 0)
        if event.chain == _DOUBLE_CLICK and column in self._editable_columns():
            self._edit(row, column)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "edit_row":
            return len(self._editable_columns()) > 0 and self.show_cursor
        return super().check_action(action, parameters)

    def action_edit_row(self) -> None:
        self._edit(self.cursor_row, self._editable_columns()[0])

    def _editable_columns(self) -> list[int]:
        """`editable_columns` the table has, in order."""
        return sorted(
            column for column in set(self.editable_columns) if 0 <= column < len(self._headers)
        )

    def _edit(self, row: int, focused: int) -> None:
        if row >= len(self._rows):
            return
        cells = self._rows[row]
        editor = ComposeRowEditor(
            {
                column: (self._headers[column], cells[column] if column < len(cells) else "")
                for column in self._editable_columns()
            },
            focused,
        )

        def apply(texts: dict[int, str] | None) -> None:
            # the rows the editor was opened on, or the edit would land on another row
            if texts is None or self._rows is not rows:
                return
            check = 1 if self._is_multiple else 0
            for column, text in texts.items():
                # an app answering an edit with fewer rows leaves none to edit
                if text == (cells[column] if column < len(cells) else "") or row >= len(self._rows):
                    continue
                self._rows = replace_cell(self._rows, row, column, text)
                self.update_cell_at(Coordinate(row, column + check), Text(text), update_width=True)
                self.cell_edited.emit(row, column, text)

        rows = self._rows
        self.app.push_screen(editor, apply)

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

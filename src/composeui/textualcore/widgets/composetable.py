from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Optional

from rich.text import Text
from textual.binding import Binding
from textual.containers import Vertical
from textual.coordinate import Coordinate
from textual.screen import ModalScreen
from textual.widgets import DataTable, Input, Label, OptionList

from composeui.core.signal import Signal
from composeui.core.view import (
    CHECKED_TEXTS,
    PLAIN_CELL,
    CellKind,
    CellStyle,
    CellWidget,
    HeaderGroup,
    replace_cell,
)
from composeui.textualcore.widgets.composefilepathinput import file_picker
from composeui.textualcore.widgets.composetree import MARKS

if TYPE_CHECKING:
    from pathlib import Path

    from textual import events
    from textual.app import ComposeResult
    from textual.binding import BindingType

#: the first column's cell of a selected row, in a table selecting several rows
_CHECK = "✓"
#: `events.Click.chain` of a double click's second click
_DOUBLE_CLICK = 2
#: a check box cell or a check-all header, by whether it's checked (None: some rows)
_BOXES = {True: "\u2611", False: "\u2610", None: "\u25a3"}


class ComposeOptionPicker(ModalScreen[Optional[str]]):
    """A modal listing a combobox cell's options, the cell's own highlighted.

    Picking one (a click or Enter) dismisses it with its text, Escape with None.
    """

    DEFAULT_CSS = """
    ComposeOptionPicker {
        align: center middle;
    }
    ComposeOptionPicker > OptionList {
        width: 40;
        max-width: 90%;
        height: auto;
        max-height: 80%;
        border: thick $primary 80%;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [Binding("escape", "dismiss_picker", "Close")]

    def __init__(self, options: list[str], text: str) -> None:
        super().__init__()
        self.options = OptionList(*(Text(option) for option in options))
        self._highlighted = options.index(text) if text in options else 0

    def compose(self) -> ComposeResult:
        yield self.options

    def on_mount(self) -> None:
        self.options.highlighted = self._highlighted
        self.options.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(str(event.option.prompt))

    def action_dismiss_picker(self) -> None:
        self.dismiss(None)


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
                yield Label(self._headers[column], markup=False)
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
    on the cursor's row, a double click on the clicked cell's. It types file paths too,
    whose cells show the path and "[…]": a click on an editable one opens textual-fspicker's
    file picker (see `file_picker`), the cell taking the file picked. `cell_edited` emits each
    cell the user changed: its row, its column (without the check column) and its text.

    The columns of `cell_widgets` show widgets as text: a check box as a box, which a
    click or Space (the cursor row's first) toggles when editable; a combobox as its text
    and an arrow, a click (or F2, without a typed column) opening a `ComposeOptionPicker`
    on it; a button as its text and the button's in brackets, and a link underlined,
    `cell_clicked` emitting a click on either. A check-all column's header starts with
    the box `set_checked_columns` shows, and its click emits `check_all_clicked`.

    `header_clicked` emits the column whose header the user clicked; the header shows
    the order `set_sort` gives (▲/▼), the table never sorting its rows itself.

    `fill` gives how the cells look: a background, the text black or white on it; dim
    and never edited when disabled; a mark before the text. A cell spanning rows shows
    its text in its own, those it covers empty: a terminal has no cells across rows. The
    rows' headers show on the left, unless there are none. With `set_header_groups`,
    the header has two lines: a group's text over its first column, then each column's.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("f2", "edit_row", "Edit"),
        Binding("space", "toggle_check", "Check", show=False),
    ]

    def __init__(self) -> None:
        super().__init__(cursor_type="row", show_cursor=False, zebra_stripes=True)
        self.selected_rows_changed: Signal[list[int]] = Signal()
        self.cell_edited: Signal[int, int, str] = Signal()
        self.header_clicked: Signal[int] = Signal()
        self.cell_clicked: Signal[int, int] = Signal()
        self.check_all_clicked: Signal[int] = Signal()
        self.editable_columns: list[int] = []
        self.cell_widgets: dict[int, CellWidget] = {}
        self._checked_columns: dict[int, bool | None] = {}
        self._sort: tuple[int, bool] | None = None
        self._selected_rows: list[int] = []
        self._is_multiple = False
        self._headers: list[str] = []
        self._rows: list[list[str]] = []
        self._styles: dict[tuple[int, int], CellStyle] = {}
        self._row_headers: list[str] = []
        self._groups: list[HeaderGroup] = []

    def fill(
        self,
        headers: list[str],
        rows: list[list[str]],
        selected: list[int] | None = None,
        styles: dict[tuple[int, int], CellStyle] | None = None,
        row_headers: list[str] | None = None,
    ) -> None:
        """Rebuild the whole table, as plain text: a string cell would be read as markup.

        `selected` replaces the selected rows, which the rows replaced may no longer hold;
        `styles` how the cells look, by row and column, and `row_headers` the rows'
        headers, likewise.
        """
        self._headers, self._rows = headers, rows
        if selected is not None:
            self._selected_rows = selected
        if styles is not None:
            self._styles = styles
        if row_headers is not None:
            self._row_headers = row_headers
        self.clear(columns=True)
        self.header_height = 2 if len(self._groups) > 0 else 1
        check = [Text("")] if self._is_multiple else []
        self.add_columns(*check, *(Text(label) for label in self._labels(headers)))
        covered = {
            (row + offset, column)
            for (row, column), style in self._styles.items()
            for offset in range(1, style.row_span)
        }
        for row, cells in enumerate(rows):
            label = Text(self._row_headers[row]) if row < len(self._row_headers) else None
            self.add_row(
                *check,
                *(
                    Text("") if (row, column) in covered else self._cell(row, column, cells)
                    for column in range(len(headers))
                ),
                label=label,
            )
        # clearing moved the cursor back to the first row
        self.set_selected_rows(self._selected_rows)

    def set_header_groups(self, groups: list[HeaderGroup]) -> None:
        self._groups = groups
        self.fill(self._headers, self._rows)

    def set_cell_widgets(self, widgets: dict[int, CellWidget]) -> None:
        self.cell_widgets = widgets
        self.fill(self._headers, self._rows)

    def set_checked_columns(self, checked: dict[int, bool | None]) -> None:
        """Show each check-all column's box: checked, unchecked or partly (None)."""
        if checked == self._checked_columns:
            return
        is_relabel = checked.keys() == self._checked_columns.keys()
        self._checked_columns = checked
        if not is_relabel:
            self.fill(self._headers, self._rows)
            return
        # as wide as before, a box for a box: relabelled in place, as rebuilding the table
        # would lose a click being handled, before the row it selects
        columns = list(self.columns.values())[1 if self._is_multiple else 0 :]
        for column, label in zip(columns, self._labels(self._headers)):
            column.label = Text(label)
        self._clear_caches()
        self.refresh()

    def _kind(self, column: int) -> CellKind | None:
        widget = self.cell_widgets.get(column)
        return None if widget is None else widget.kind

    def _style(self, row: int, column: int) -> CellStyle:
        return self._styles.get((row, column), PLAIN_CELL)

    def _cell(self, row: int, column: int, cells: list[str]) -> Text:
        """Show a cell: its mark, then its text or its widget's, as its style says."""
        content = self._content(column, cells)
        style = self._style(row, column)
        if style.mark is not None:
            glyph, mark_style = MARKS[style.mark]
            content = Text.assemble((glyph, mark_style), " ", content)
        if not style.is_enabled:
            content.stylize("dim")
        if style.background is not None:
            content.stylize(f"{style.text_color} on {style.background}")
        return content

    def _content(self, column: int, cells: list[str]) -> Text:
        """Show a cell's text, or its widget's."""
        text = cells[column] if column < len(cells) else ""
        widget = self.cell_widgets.get(column)
        if widget is None:
            return Text(text)
        if widget.kind is CellKind.CHECK_BOX:
            return Text(_BOXES[text.casefold() == "true"])
        if widget.kind is CellKind.COMBOBOX:
            return Text(f"{text} \u25be")
        if widget.kind is CellKind.BUTTON:
            return Text.assemble(text, " ", (f"[{widget.text}]", "bold"))
        if widget.kind is CellKind.FILE_PATH:
            return Text.assemble(text, " ", ("[\u2026]", "bold"))
        return Text(text, style="underline")

    def set_sort(self, sort: tuple[int, bool] | None) -> None:
        """Show the order: by a column, descending or not; None for the rows' own."""
        if sort != self._sort:
            self._sort = sort
            self.fill(self._headers, self._rows)

    def _labels(self, headers: list[str]) -> list[str]:
        labels = [
            f"{_BOXES[self._checked_columns[column]]} {header}"
            if column in self._checked_columns
            else header
            for column, header in enumerate(headers)
        ]
        if self._sort is None or self._sort[0] >= len(headers):
            return self._grouped(labels)
        column, is_descending = self._sort
        labels[column] = f"{labels[column]} {'▼' if is_descending else '▲'}"
        return self._grouped(labels)

    def _grouped(self, labels: list[str]) -> list[str]:
        """Put each group's text over its first column's label, on a line of its own."""
        if len(self._groups) == 0:
            return labels
        starts = {group.column: group.text for group in self._groups}
        return [f"{starts.get(column, '')}\n{label}" for column, label in enumerate(labels)]

    def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
        column = event.column_index - (1 if self._is_multiple else 0)
        if column in self._checked_columns:
            self.check_all_clicked.emit(column)
        elif column >= 0:
            self.header_clicked.emit(column)

    def set_multiple_selection(self, *, is_multiple: bool) -> None:
        if is_multiple != self._is_multiple:
            self._is_multiple = is_multiple
            self.fill(self._headers, self._rows)  # with or without the check column

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
        kind = self._kind(column)
        if not self._style(row, column).is_enabled:
            return
        if kind in (CellKind.BUTTON, CellKind.LINK) and event.chain == 1:
            self.cell_clicked.emit(row, column)
        elif column in self._editable_columns(kind=kind):
            self._edit_clicked(row, column, kind, event.chain)

    def _edit_clicked(self, row: int, column: int, kind: CellKind | None, chain: int) -> None:
        """Edit an editable cell clicked `chain` times in a row, as its widget does."""
        if kind is CellKind.CHECK_BOX:
            self._toggle_check(row, column)
        elif kind is CellKind.COMBOBOX:
            self._pick(row, column)
        elif kind is CellKind.FILE_PATH and chain == 1:
            self._browse(row, column)
        elif chain == _DOUBLE_CLICK:
            self._edit(row, column)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "edit_row":
            is_editable = any(
                len(self._editable_columns(kind=kind)) > 0
                for kind in (None, CellKind.COMBOBOX, CellKind.FILE_PATH)
            )
            return is_editable and self.show_cursor
        if action == "toggle_check":
            return len(self._editable_columns(kind=CellKind.CHECK_BOX)) > 0 and self.show_cursor
        return super().check_action(action, parameters)

    def action_edit_row(self) -> None:
        row = self.cursor_row
        typed = self._typed_columns(row)
        if len(typed) > 0:
            self._edit(row, typed[0])
        else:
            picked = self._editable_columns(kind=CellKind.COMBOBOX, row=row)
            if len(picked) > 0:
                self._pick(row, picked[0])

    def action_toggle_check(self) -> None:
        checked = self._editable_columns(kind=CellKind.CHECK_BOX, row=self.cursor_row)
        if len(checked) > 0:
            self._toggle_check(self.cursor_row, checked[0])

    def _editable_columns(self, kind: CellKind | None = None, row: int | None = None) -> list[int]:
        """Get the `editable_columns` whose cells show `kind`, in order: typed in if None.

        Those whose cell in `row`, if given, isn't disabled.
        """
        return sorted(
            column
            for column in set(self.editable_columns)
            if 0 <= column < len(self._headers)
            and self._kind(column) is kind
            and (row is None or self._style(row, column).is_enabled)
        )

    def _typed_columns(self, row: int) -> list[int]:
        """Get the `editable_columns` the user types in, in `row`: plain ones and paths."""
        return sorted(
            [
                *self._editable_columns(row=row),
                *self._editable_columns(kind=CellKind.FILE_PATH, row=row),
            ]
        )

    def _set_cell(self, row: int, column: int, text: str) -> None:
        """Show a cell the user changed and emit it, unless the rows no longer have its row."""
        if row >= len(self._rows):
            return
        self._rows = replace_cell(self._rows, row, column, text)
        check = 1 if self._is_multiple else 0
        self.update_cell_at(
            Coordinate(row, column + check),
            self._cell(row, column, self._rows[row]),
            update_width=True,
        )
        self.cell_edited.emit(row, column, text)

    def _toggle_check(self, row: int, column: int) -> None:
        assert row < len(self._rows)  # a row clicked, or the cursor's, shown only on a row
        cells = self._rows[row]
        is_checked = (cells[column] if column < len(cells) else "").casefold() == "true"
        self._set_cell(row, column, CHECKED_TEXTS[not is_checked])

    def _pick(self, row: int, column: int) -> None:
        assert row < len(self._rows)  # see `_toggle_check`
        cells = self._rows[row]
        text = cells[column] if column < len(cells) else ""
        options = list(self.cell_widgets[column].options)
        picker = ComposeOptionPicker([*options, *([] if text in options else [text])], text)

        def apply(picked: str | None) -> None:
            # the rows the picker was opened on, or the edit would land on another row
            if picked is not None and picked != text and self._rows is rows:
                self._set_cell(row, column, picked)

        rows = self._rows
        self.app.push_screen(picker, apply)

    def _browse(self, row: int, column: int) -> None:
        """Pick a file in the cell's directory, its path then the cell's text."""
        assert row < len(self._rows)  # see `_toggle_check`
        cells = self._rows[row]
        text = cells[column] if column < len(cells) else ""
        widget = self.cell_widgets[column]

        def apply(picked: Path | None) -> None:
            # the rows the picker was opened on, or the edit would land on another row
            if picked is not None and str(picked) != text and self._rows is rows:
                self._set_cell(row, column, str(picked))

        rows = self._rows
        start = widget.server_roots[0] if widget.server_roots else None
        self.app.push_screen(file_picker(text, widget.extensions, widget.text, start), apply)

    def _edit(self, row: int, focused: int) -> None:
        assert row < len(self._rows)  # see `_toggle_check`
        cells = self._rows[row]
        editor = ComposeRowEditor(
            {
                column: (self._headers[column], cells[column] if column < len(cells) else "")
                for column in self._typed_columns(row)
            },
            focused,
        )

        def apply(texts: dict[int, str] | None) -> None:
            # the rows the editor was opened on, or the edit would land on another row
            if texts is None or self._rows is not rows:
                return
            for column, text in texts.items():
                # an app answering an edit with fewer rows leaves none to edit
                if text != (cells[column] if column < len(cells) else ""):
                    self._set_cell(row, column, text)

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

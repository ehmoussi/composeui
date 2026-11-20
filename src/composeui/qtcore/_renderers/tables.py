"""Qt table and source-table renderers."""

from __future__ import annotations

import functools
from pathlib import Path
from typing import TYPE_CHECKING, Any

from qtpy.QtCore import Qt
from qtpy.QtWidgets import QApplication, QFileDialog
from typing_extensions import Protocol

from composeui.core._views.tables import SourceTableByPosition
from composeui.core.renderer import ViewLike
from composeui.core.view import CellKind, NodeMark, SelectionMode
from composeui.qtcore._renderers.files import _ask_file, _ask_folder, _ask_save
from composeui.qtcore.qtrenderer import QtWidgetRenderer
from composeui.qtcore.widgets.qfiltertable import QFilterTable
from composeui.qtcore.widgets.qsourcetable import QDataFilterTable

if TYPE_CHECKING:
    from collections.abc import Callable

    from qtpy.QtCore import QModelIndex

    from composeui.core.signal import Signal
    from composeui.core.view import CellStyle, CellWidget, HeaderGroup


class TableViewLike(ViewLike, Protocol):
    headers: list[str]
    filter_texts: dict[str, str]
    selection_mode: SelectionMode
    rows: list[list[str]]
    sortable_columns: list[int]
    filterable_columns: list[int]
    sort_column: int | None
    sort_descending: bool
    search: str
    filters: dict[int, str]
    selected_rows: list[int]
    shown_rows: list[int]
    selection_changed: Signal[list[int]]
    row_activated: Signal[int]
    editable_columns: list[int]
    cell_edited: Signal[int, int, str]
    cell_widgets: dict[int, CellWidget]
    file_texts: dict[str, str]
    cell_clicked: Signal[int, int]
    cell_styles: dict[tuple[int, int], CellStyle]
    header_groups: list[HeaderGroup]
    row_headers: list[str]

    def edit_cell(
        self,
        row: int,
        column: int,
        text: str,
        assign: Callable[[list[list[str]]], None] | None = None,
    ) -> bool: ...
    def mark_text(self, mark: NodeMark) -> str: ...
    def cell_widget(self, row: int, column: int) -> CellWidget | None: ...
    def shown_cell_styles(self) -> dict[tuple[int, int], CellStyle]: ...
    def column_checked(self, column: int) -> bool | None: ...
    def check_all(self, column: int, *, is_checked: bool) -> None: ...
    def sort_by(self, column: int) -> None: ...
    def filter_error(self, column: int, text: str) -> str | None: ...
    def filter_placeholder(self, column: int, *, is_pattern: bool = False) -> str: ...
    def filter_takes_pattern(self, column: int) -> bool: ...
    def filter_chip(self, column: int) -> str: ...


class SourceTableViewLike(ViewLike, Protocol):
    texts: dict[str, str]
    export_filename: str
    sort_column: str | None
    sort_descending: bool
    search: str
    filters: dict[str, str]
    filterable_columns: list[str]
    filter_texts: dict[str, str]

    @property
    def headers(self) -> list[str]: ...
    @property
    def column_names(self) -> list[str]: ...
    @property
    def row_count(self) -> int: ...
    def rows(self, start: int, stop: int) -> list[tuple[Any, list[str]]]: ...
    def sort_by(self, column: str) -> None: ...
    def is_selected(self, row_id: Any) -> bool: ...
    def select_at(self, position: int) -> None: ...
    def extend_to(self, position: int) -> None: ...
    def activate_at(self, position: int) -> None: ...
    @property
    def count_text(self) -> str: ...
    def header(self, column: str) -> str: ...
    def filter_error(self, column: str, text: str) -> str | None: ...
    def filter_takes_pattern(self, column: str) -> bool: ...
    def filter_placeholder(self, column: str, *, is_pattern: bool = False) -> str: ...
    def filter_chip(self, column: str) -> str: ...
    def selection_text(self) -> str: ...
    def export_csv(self, path: Path) -> None: ...


class QtSourceTableRenderer(QtWidgetRenderer[SourceTableViewLike, QDataFilterTable]):
    """A large table: Qt asks the view for the rows it draws, as the user scrolls.

    A click on a header sorts by its column (`SourceTableView.sort_by`). A click on a row
    selects it (`select_at`), Shift extending the selection (`extend_to`), and a double
    click activates it (`activate_at`).

    Its filter bar (`QTableFilterBar`) searches it, and filters the columns of
    `filterable_columns`: the bar knows them by their position among the source's.
    Ctrl+C copies the selected rows to the clipboard (`SourceTableView.selection_text`).
    Export CSV, above the rows and in their context menu, asks where to write the rows
    (`export_csv`). While a job orders the rows (`is_ordering`), the cursor over them is
    busy.
    """

    def __init__(self, view: SourceTableViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "source": self._refresh_source,
                "row_count": self._reset,
                "column_formats": self._repaint,
                "filter_texts": self._refresh_filter_texts,
                "filterable_columns": self._refresh_filterable_columns,
                "search": self._refresh_search,
                "filters": self._refresh_filters,
                # shown with the order they give, which the view sends as `row_count`
                "sort_column": lambda _view, _table, _value: None,
                "sort_descending": lambda _view, _table, _value: None,
                # each click asks the view, which knows the mode
                "selection_mode": lambda _view, _table, _value: None,
                "selected_ids": self._repaint,
                "texts": self._refresh_texts,
                # read as the user exports
                "export_filename": lambda _view, _table, _value: None,
                "is_ordering": self._refresh_is_ordering,
            }
        )

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QDataFilterTable(self._view)
            table, bar = self._rendered_object.table, self._rendered_object.bar
            columns = SourceTableByPosition(self._view)
            table.header_clicked.connect(columns.sort_by)
            table.row_clicked.connect(
                lambda position, is_extended: columns.select(position, is_extended=is_extended)
            )
            table.row_activated.connect(self._view.activate_at)
            table.copy_requested.connect(
                lambda: QApplication.clipboard().setText(self._view.selection_text())
            )
            self._connect(table.export_requested, self._export)
            bar.check = columns.filter_error
            bar.placeholder = lambda column, is_pattern: columns.filter_placeholder(
                column, is_pattern=is_pattern
            )
            bar.takes_pattern = columns.filter_takes_pattern
            self._connect(bar.search_edited, self._update_search)
            bar.filter_added.connect(columns.add_filter)
            bar.filter_removed.connect(columns.remove_filter)
            bar.filters_cleared.connect(columns.clear_filters)
            self.refresh()

    @classmethod
    def _refresh_source(
        cls, view: SourceTableViewLike, rendered_object: QDataFilterTable, value: Any
    ) -> None:
        """Show the new source's columns in the bar, then its rows."""
        cls._refresh_filterable_columns(view, rendered_object, view.filterable_columns)
        cls._refresh_filters(view, rendered_object, view.filters)
        cls._reset(view, rendered_object, value)

    @staticmethod
    def _reset(view: SourceTableViewLike, rendered_object: QDataFilterTable, _value: Any) -> None:
        """Show a new order of the rows: the sort indicator, the count, and no row if none."""
        table = rendered_object.table
        table.data_model.reset()
        sort = SourceTableByPosition(view).sort
        table.set_sort_indicator(sort)
        rendered_object.bar.set_count(view.count_text)
        rendered_object.empty.setVisible(view.row_count == 0 and view.count_text != "")

    @staticmethod
    def _refresh_texts(
        _view: SourceTableViewLike, rendered_object: QDataFilterTable, value: dict[str, str]
    ) -> None:
        # "empty": the web's; here the headers stay, over no row
        rendered_object.table.export_action.setText(f"{value.get('export', '')}…")

    @staticmethod
    def _refresh_is_ordering(
        _view: SourceTableViewLike, rendered_object: QDataFilterTable, value: bool
    ) -> None:
        rows = rendered_object.table.viewport()
        if value:
            rows.setCursor(Qt.CursorShape.BusyCursor)
        else:
            rows.unsetCursor()

    def _export(self) -> None:
        """Ask where to write the rows shown as CSV, and write them there."""
        table = self._rendered_object
        assert table is not None
        path, _chosen = QFileDialog.getSaveFileName(
            table, self._view.texts.get("export", ""), self._view.export_filename, "CSV (*.csv)"
        )
        if path != "":
            filepath = Path(path)
            if filepath.suffix.lower() != ".csv":
                filepath = filepath.with_name(f"{filepath.name}.csv")
            self._view.export_csv(filepath)

    @staticmethod
    def _refresh_filter_texts(
        view: SourceTableViewLike, rendered_object: QDataFilterTable, value: dict[str, str]
    ) -> None:
        rendered_object.bar.set_texts(value)
        rendered_object.bar.set_count(view.count_text)
        rendered_object.empty.setText(value.get("no_match", ""))

    @staticmethod
    def _refresh_filterable_columns(
        view: SourceTableViewLike, rendered_object: QDataFilterTable, value: list[str]
    ) -> None:
        columns = SourceTableByPosition(view).bar_columns(value)
        rendered_object.bar.set_columns(columns)
        rendered_object.bar.setVisible(len(columns) > 0)

    @staticmethod
    def _refresh_search(
        _view: SourceTableViewLike, rendered_object: QDataFilterTable, value: str
    ) -> None:
        rendered_object.bar.set_search(value)

    @staticmethod
    def _refresh_filters(
        view: SourceTableViewLike, rendered_object: QDataFilterTable, value: dict[str, str]
    ) -> None:
        rendered_object.bar.set_filters(SourceTableByPosition(view).chips(value))

    def _update_search(self, text: str) -> None:
        with self.stop_refresh():
            self._view.search = text

    @staticmethod
    def _repaint(
        _view: SourceTableViewLike, rendered_object: QDataFilterTable, _value: Any
    ) -> None:
        rendered_object.table.data_model.repaint()


class QtTableRenderer(QtWidgetRenderer[TableViewLike, QFilterTable]):
    """A table under its filter bar; the table shows `shown_rows`, in their order.

    The widgets know the rows only as shown: their indexes map back to `rows` through
    `shown_rows`. A file path cell's button opens Qt's file dialog in the directory of
    the cell's path, if any.
    """

    def __init__(self, view: TableViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "headers": self._refresh_headers,
                "filter_texts": self._refresh_filter_texts,
                "selection_mode": self._refresh_selection_mode,
                # shown with `shown_rows`, which the view always sends next
                "rows": lambda _view, _table, _value: None,
                "sortable_columns": self._refresh_sort,
                "filterable_columns": self._refresh_filterable_columns,
                "sort_column": self._refresh_sort,
                "sort_descending": self._refresh_sort,
                "search": self._refresh_search,
                "filters": self._refresh_filters,
                "selected_rows": self._refresh_selected_rows,
                "shown_rows": self._refresh_shown_rows,
                "editable_columns": self._refresh_editable_columns,
                "cell_widgets": self._refresh_cell_widgets,
                # the web's list of the server's files only
                "file_texts": lambda _view, _rendered_object, _value: None,
                "cell_styles": self._refresh_looks,
                "header_groups": self._refresh_header_groups,
                "row_headers": self._refresh_looks,
                "done_text": functools.partial(self._refresh_mark_text, NodeMark.DONE),
                "warning_text": functools.partial(self._refresh_mark_text, NodeMark.WARNING),
                "error_text": functools.partial(self._refresh_mark_text, NodeMark.ERROR),
            }
        )

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QFilterTable()
            table, bar = self._rendered_object.table, self._rendered_object.bar
            self._connect(table.selected_rows_changed, self._update_selected_rows)
            # a double click that edits nothing, or Enter (see `QTextTableView`)
            self._connect(table.activated, self._activate_row)
            self._connect(table.cell_edited, self._update_cell)
            self._connect(table.cell_clicked, self._click_cell)
            self._connect(table.browse_clicked, self._browse)
            self._connect(table.check_all_clicked, self._check_all)
            self._connect(table.header_clicked, self._sort_by)
            table.set_widget_of(self._cell_widget)
            bar.check = self._view.filter_error
            bar.placeholder = lambda column, is_pattern: self._view.filter_placeholder(
                column, is_pattern=is_pattern
            )
            bar.takes_pattern = self._view.filter_takes_pattern
            self._connect(bar.search_edited, self._update_search)
            self._connect(bar.filter_added, self._add_filter)
            self._connect(bar.filter_removed, self._remove_filter)
            self._connect(bar.filters_cleared, self._clear_filters)
            self.refresh()

    @classmethod
    def _refresh_headers(
        cls, view: TableViewLike, rendered_object: QFilterTable, _value: list[str]
    ) -> None:
        cls._refresh_shown_rows(view, rendered_object, view.shown_rows)
        cls._refresh_filterable_columns(view, rendered_object, view.filterable_columns)
        cls._refresh_filters(view, rendered_object, view.filters)
        cls._refresh_sort(view, rendered_object, None)

    @staticmethod
    def _refresh_filter_texts(
        view: TableViewLike, rendered_object: QFilterTable, value: dict[str, str]
    ) -> None:
        rendered_object.bar.set_texts(value)
        rendered_object.bar.set_count(_count_text(view, view.shown_rows))
        rendered_object.empty.setText(value.get("no_match", ""))

    @staticmethod
    def _refresh_selection_mode(
        _view: TableViewLike, rendered_object: QFilterTable, value: SelectionMode
    ) -> None:
        rendered_object.table.set_multiple_selection(is_multiple=value is SelectionMode.MULTIPLE)

    @staticmethod
    def _refresh_sort(view: TableViewLike, rendered_object: QFilterTable, _value: Any) -> None:
        sort = None if view.sort_column is None else (view.sort_column, view.sort_descending)
        rendered_object.table.set_sort_indicator(sort, is_shown=len(view.sortable_columns) > 0)

    @staticmethod
    def _refresh_filterable_columns(
        view: TableViewLike, rendered_object: QFilterTable, value: list[int]
    ) -> None:
        columns = [(column, view.headers[column]) for column in value if column < len(view.headers)]
        rendered_object.bar.set_columns(columns)
        rendered_object.bar.setVisible(len(columns) > 0)

    @staticmethod
    def _refresh_search(_view: TableViewLike, rendered_object: QFilterTable, value: str) -> None:
        rendered_object.bar.set_search(value)

    @staticmethod
    def _refresh_filters(
        view: TableViewLike, rendered_object: QFilterTable, value: dict[int, str]
    ) -> None:
        rendered_object.bar.set_filters(
            [
                (column, view.filter_chip(column), text, view.headers[column])
                for column, text in sorted(value.items())
                if column < len(view.headers)
            ]
        )

    @staticmethod
    def _refresh_selected_rows(
        view: TableViewLike, rendered_object: QFilterTable, value: list[int]
    ) -> None:
        positions = {row: position for position, row in enumerate(view.shown_rows)}
        rendered_object.table.set_selected_rows(
            sorted(positions[row] for row in value if row in positions)
        )

    @classmethod
    def _refresh_shown_rows(
        cls, view: TableViewLike, rendered_object: QFilterTable, value: list[int]
    ) -> None:
        row_headers = [
            view.row_headers[row] if row < len(view.row_headers) else "" for row in value
        ]
        rendered_object.table.set_table(
            view.headers,
            [view.rows[row] for row in value],
            view.shown_cell_styles(),
            row_headers if len(view.row_headers) > 0 else [],
        )
        # resetting the table drops its selection: reapply it
        cls._refresh_selected_rows(view, rendered_object, view.selected_rows)
        rendered_object.bar.set_count(_count_text(view, value))
        rendered_object.empty.setVisible(len(value) == 0 and len(view.rows) > 0)
        cls._refresh_checked_columns(view, rendered_object)

    @staticmethod
    def _refresh_checked_columns(
        view: TableViewLike,
        rendered_object: QFilterTable,
        *,
        editable_columns: list[int] | None = None,
        cell_widgets: dict[int, CellWidget] | None = None,
    ) -> None:
        """Show each check-all box; with the new value of a field the view doesn't hold yet."""
        editable = view.editable_columns if editable_columns is None else editable_columns
        widgets = view.cell_widgets if cell_widgets is None else cell_widgets
        rendered_object.table.set_checked_columns(
            {
                column: (view.column_checked(column), column in editable)
                for column, widget in widgets.items()
                if widget.kind is CellKind.CHECK_BOX and widget.check_all
            }
        )

    @classmethod
    def _refresh_editable_columns(
        cls, view: TableViewLike, rendered_object: QFilterTable, value: list[int]
    ) -> None:
        rendered_object.table.set_editable_columns(value)
        cls._refresh_checked_columns(view, rendered_object, editable_columns=value)

    @classmethod
    def _refresh_cell_widgets(
        cls, view: TableViewLike, rendered_object: QFilterTable, value: dict[int, CellWidget]
    ) -> None:
        rendered_object.table.set_cell_widgets(value)
        cls._refresh_checked_columns(view, rendered_object, cell_widgets=value)

    @classmethod
    def _refresh_looks(
        cls, view: TableViewLike, rendered_object: QFilterTable, _value: Any
    ) -> None:
        cls._refresh_shown_rows(view, rendered_object, view.shown_rows)

    @staticmethod
    def _refresh_header_groups(
        _view: TableViewLike, rendered_object: QFilterTable, value: list[HeaderGroup]
    ) -> None:
        rendered_object.table.set_header_groups(value)

    @staticmethod
    def _refresh_mark_text(
        mark: NodeMark, _view: TableViewLike, rendered_object: QFilterTable, value: str
    ) -> None:
        rendered_object.table.set_mark_text(mark, value)

    def _update_selected_rows(self, positions: list[int]) -> None:
        shown = self._view.shown_rows
        rows = sorted(shown[position] for position in positions)
        with self.stop_refresh():
            self._view.selected_rows = rows
        self._view.selection_changed.emit(rows)

    def _update_cell(self, position: int, column: int, text: str) -> None:
        self._view.edit_cell(self._view.shown_rows[position], column, text, self._assign_rows)
        assert self._rendered_object is not None
        # a check-all box follows its column's
        self._refresh_checked_columns(self._view, self._rendered_object)

    def _assign_rows(self, rows: list[list[str]]) -> None:
        """Set the user's edit in `rows`, which the widget already shows."""
        with self.stop_refresh():
            self._view.rows = rows

    def _click_cell(self, position: int, column: int) -> None:
        self._view.cell_clicked.emit(self._view.shown_rows[position], column)

    def _cell_widget(self, position: int, column: int) -> CellWidget | None:
        """Get the widget of the cell at `position` among the rows shown."""
        return self._view.cell_widget(self._view.shown_rows[position], column)

    def _activate_row(self, index: QModelIndex) -> None:
        self._view.row_activated.emit(self._view.shown_rows[index.row()])

    def _browse(self, position: int, column: int) -> None:
        """Pick a path in the cell's Qt dialog, then the cell's text; nothing if cancelled.

        A file's, a folder's, or one to save to, as the cell's widget says. The dialog opens
        on the cell's path, else in the widget's `start_folder`.
        """
        assert self._rendered_object is not None
        row = self._view.shown_rows[position]
        widget = self._view.cell_widget(row, column)
        assert widget is not None  # its button drawn for it
        cells = self._view.rows[row]
        text = cells[column].strip() if column < len(cells) else ""
        path = widget.path(text) if text != "" else None
        parent, title = self._rendered_object, widget.text
        if widget.kind is CellKind.FOLDER_PATH:
            picked = _ask_folder(parent, title, path or widget.start_folder())
        elif widget.kind is CellKind.SAVE_PATH:
            picked = _ask_save(
                parent,
                title,
                path or widget.start_folder(),
                widget.extensions,
                confirms_overwrite=widget.confirms_overwrite,
                replace_question=self._view.file_texts.get("replace_question", "{name}"),
            )
        else:
            start = path.parent if path is not None else widget.start_folder()
            picked = _ask_file(parent, title, start, widget.extensions)
        if picked != "":
            self._rendered_object.table.set_text(position, column, widget.path_text(Path(picked)))

    def _check_all(self, column: int) -> None:
        if column in self._view.editable_columns:
            self._view.check_all(column, is_checked=self._view.column_checked(column) is not True)

    def _sort_by(self, column: int) -> None:
        if column in self._view.sortable_columns:
            self._view.sort_by(column)

    def _update_search(self, text: str) -> None:
        with self.stop_refresh():
            self._view.search = text

    def _add_filter(self, column: int, text: str) -> None:
        self._view.filters = {**self._view.filters, column: text}

    def _remove_filter(self, column: int) -> None:
        self._view.filters = {
            other: text for other, text in self._view.filters.items() if other != column
        }

    def _clear_filters(self) -> None:
        self._view.filters = {}


def _count_text(view: TableViewLike, shown: list[int]) -> str:
    """Count the rows shown, while the search or the filters hide some."""
    if len(shown) == len(view.rows):
        return ""
    return view.filter_texts.get("count", "").format(shown=len(shown), total=len(view.rows))

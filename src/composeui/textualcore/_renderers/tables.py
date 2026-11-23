"""Textual tables and source tables."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from typing_extensions import Protocol, override

from composeui.core._views.tables import SourceTableByPosition
from composeui.core.renderer import ViewLike
from composeui.core.view import CellKind, SelectionMode
from composeui.textualcore.textualrenderer import TextualWidgetRenderer
from composeui.textualcore.widgets.composefiltertable import ComposeFilterTable
from composeui.textualcore.widgets.composesourcetable import ComposeDataFilterTable

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from composeui.core.signal import Signal
    from composeui.core.view import CellStyle, CellWidget, HeaderGroup, NodeMark


class SourceTableViewLike(ViewLike, Protocol):
    texts: dict[str, str]
    export_filename: str | None
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


class TextualSourceTableRenderer(
    TextualWidgetRenderer[SourceTableViewLike, ComposeDataFilterTable]
):
    """A large table: Textual asks the view for the lines it draws, as the user scrolls.

    A click on a header sorts by its column (`SourceTableView.sort_by`). A click on a row,
    or Space on the cursor's, selects it (`select_at`), Shift extending the selection
    (`extend_to`); a double click or Enter activates it (`activate_at`).

    Its filter bar (`ComposeFilterBar`) searches it, and filters the columns of
    `filterable_columns`: the bar knows them by their position among the source's.
    Ctrl+C copies the selected rows to the clipboard (`SourceTableView.selection_text`),
    through the terminal. Its key `e` asks where to write the rows as CSV (`export_csv`),
    unless `export_filename` is None.
    While a job orders the rows (`is_ordering`), Textual's loading indicator covers them.
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
                "export_filename": self._refresh_export_filename,
                "is_ordering": self._refresh_is_ordering,
            }
        )

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = ComposeDataFilterTable(self._view)
            table, bar = self._rendered_object.table, self._rendered_object.bar
            columns = SourceTableByPosition(self._view)
            table.header_clicked.connect(columns.sort_by)
            table.row_clicked.connect(
                lambda position, is_extended: columns.select(position, is_extended=is_extended)
            )
            table.row_activated.connect(self._view.activate_at)
            table.copy_requested.connect(self._copy)
            table.export_path_chosen.connect(self._view.export_csv)
            bar.check = columns.filter_error
            bar.placeholder = lambda column, is_pattern: columns.filter_placeholder(
                column, is_pattern=is_pattern
            )
            bar.takes_pattern = columns.filter_takes_pattern
            bar.search_edited.connect(self._update_search)
            bar.filter_added.connect(columns.add_filter)
            bar.filter_removed.connect(columns.remove_filter)
            bar.filters_cleared.connect(columns.clear_filters)

    @classmethod
    def _refresh_source(
        cls, view: SourceTableViewLike, rendered_object: ComposeDataFilterTable, value: Any
    ) -> None:
        """Show the new source's columns in the bar, then its rows."""
        cls._refresh_filterable_columns(view, rendered_object, view.filterable_columns)
        cls._refresh_filters(view, rendered_object, view.filters)
        cls._reset(view, rendered_object, value)

    @staticmethod
    def _reset(
        view: SourceTableViewLike, rendered_object: ComposeDataFilterTable, _value: Any
    ) -> None:
        """Show a new order of the rows: the sort mark, the count, and no row if none."""
        sort = SourceTableByPosition(view).sort
        rendered_object.table.set_sort(sort)
        rendered_object.table.reset()
        rendered_object.bar.set_count(view.count_text)
        rendered_object.empty.display = view.row_count == 0 and view.count_text != ""

    @staticmethod
    def _refresh_export_filename(
        _view: SourceTableViewLike, rendered_object: ComposeDataFilterTable, value: str | None
    ) -> None:
        rendered_object.table.set_export_filename(value)

    @staticmethod
    def _refresh_is_ordering(
        _view: SourceTableViewLike, rendered_object: ComposeDataFilterTable, value: bool
    ) -> None:
        rendered_object.table.loading = value

    @staticmethod
    def _refresh_texts(
        _view: SourceTableViewLike, rendered_object: ComposeDataFilterTable, value: dict[str, str]
    ) -> None:
        # "empty": the web's; here the headers stay, over no row
        rendered_object.table.set_export_text(value.get("export", ""))

    @staticmethod
    def _refresh_filter_texts(
        view: SourceTableViewLike, rendered_object: ComposeDataFilterTable, value: dict[str, str]
    ) -> None:
        rendered_object.bar.set_texts(value)
        rendered_object.bar.set_count(view.count_text)
        rendered_object.empty.update(value.get("no_match", ""))

    @staticmethod
    def _refresh_filterable_columns(
        view: SourceTableViewLike, rendered_object: ComposeDataFilterTable, value: list[str]
    ) -> None:
        columns = SourceTableByPosition(view).bar_columns(value)
        rendered_object.bar.set_columns(columns)
        rendered_object.bar.display = len(columns) > 0

    @staticmethod
    def _refresh_search(
        _view: SourceTableViewLike, rendered_object: ComposeDataFilterTable, value: str
    ) -> None:
        rendered_object.bar.set_search(value)

    @staticmethod
    def _refresh_filters(
        view: SourceTableViewLike, rendered_object: ComposeDataFilterTable, value: dict[str, str]
    ) -> None:
        rendered_object.bar.set_filters(SourceTableByPosition(view).chips(value))

    def _copy(self) -> None:
        app = self._get_app()
        assert app is not None
        app.copy_to_clipboard(self._view.selection_text())

    def _update_search(self, text: str) -> None:
        with self.stop_refresh():
            self._view.search = text

    @staticmethod
    def _repaint(
        _view: SourceTableViewLike, rendered_object: ComposeDataFilterTable, _value: Any
    ) -> None:
        rendered_object.table.repaint()


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
    def cell_widget(self, row: int, column: int) -> CellWidget | None: ...
    def mark_text(self, mark: NodeMark) -> str: ...
    def shown_cell_styles(self) -> dict[tuple[int, int], CellStyle]: ...
    def column_checked(self, column: int) -> bool | None: ...
    def check_all(self, column: int, *, is_checked: bool) -> None: ...
    def sort_by(self, column: int) -> None: ...
    def filter_error(self, column: int, text: str) -> str | None: ...
    def filter_placeholder(self, column: int, *, is_pattern: bool = False) -> str: ...
    def filter_takes_pattern(self, column: int) -> bool: ...
    def filter_chip(self, column: int) -> str: ...


class TextualTableRenderer(TextualWidgetRenderer[TableViewLike, ComposeFilterTable]):
    """A table under its filter bar; the table shows `shown_rows`, in their order.

    The widgets know the rows only as shown: their indexes map back to `rows` through
    `shown_rows`.
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
                "file_texts": self._refresh_file_texts,
                "cell_styles": self._refresh_looks,
                "header_groups": self._refresh_header_groups,
                "row_headers": self._refresh_looks,
                # a terminal's cell has no tooltip: the mark's glyph says it
                "done_text": lambda _view, _table, _value: None,
                "warning_text": lambda _view, _table, _value: None,
                "error_text": lambda _view, _table, _value: None,
            }
        )

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = ComposeFilterTable()
            table, bar = self._rendered_object.table, self._rendered_object.bar
            table.selected_rows_changed.connect(self._update_selected_rows)
            table.row_activated.connect(self._activate_row)
            table.cell_edited.connect(self._update_cell)
            table.cell_clicked.connect(self._click_cell)
            table.check_all_clicked.connect(self._check_all)
            table.header_clicked.connect(self._sort_by)
            table.widget_of = self._cell_widget
            bar.check = self._view.filter_error
            bar.placeholder = lambda column, is_pattern: self._view.filter_placeholder(
                column, is_pattern=is_pattern
            )
            bar.takes_pattern = self._view.filter_takes_pattern
            bar.search_edited.connect(self._update_search)
            bar.filter_added.connect(self._add_filter)
            bar.filter_removed.connect(self._remove_filter)
            bar.filters_cleared.connect(self._clear_filters)

    @classmethod
    def _refresh_headers(
        cls, view: TableViewLike, rendered_object: ComposeFilterTable, _value: list[str]
    ) -> None:
        cls._refresh_shown_rows(view, rendered_object, view.shown_rows)
        cls._refresh_filterable_columns(view, rendered_object, view.filterable_columns)
        cls._refresh_filters(view, rendered_object, view.filters)

    @staticmethod
    def _refresh_filter_texts(
        view: TableViewLike, rendered_object: ComposeFilterTable, value: dict[str, str]
    ) -> None:
        rendered_object.bar.set_texts(value)
        rendered_object.bar.set_count(_count_text(view, view.shown_rows))
        rendered_object.empty.update(value.get("no_match", ""))

    @staticmethod
    def _refresh_selection_mode(
        _view: TableViewLike, rendered_object: ComposeFilterTable, value: SelectionMode
    ) -> None:
        rendered_object.table.set_multiple_selection(is_multiple=value is SelectionMode.MULTIPLE)

    @staticmethod
    def _refresh_sort(
        view: TableViewLike, rendered_object: ComposeFilterTable, _value: Any
    ) -> None:
        is_sorted = view.sort_column is not None and view.sort_column in view.sortable_columns
        sort = (view.sort_column, view.sort_descending) if is_sorted else None
        rendered_object.table.set_sort(cast("tuple[int, bool] | None", sort))

    @staticmethod
    def _refresh_filterable_columns(
        view: TableViewLike, rendered_object: ComposeFilterTable, value: list[int]
    ) -> None:
        columns = [(column, view.headers[column]) for column in value if column < len(view.headers)]
        rendered_object.bar.set_columns(columns)
        rendered_object.bar.display = len(columns) > 0

    @staticmethod
    def _refresh_search(
        _view: TableViewLike, rendered_object: ComposeFilterTable, value: str
    ) -> None:
        rendered_object.bar.set_search(value)

    @staticmethod
    def _refresh_filters(
        view: TableViewLike, rendered_object: ComposeFilterTable, value: dict[int, str]
    ) -> None:
        rendered_object.bar.set_filters(
            [
                (column, view.filter_chip(column), text, view.headers[column])
                for column, text in sorted(value.items())
                if column < len(view.headers)
            ]
        )

    @staticmethod
    def _positions(view: TableViewLike, rows: list[int]) -> list[int]:
        """Get where `rows` show, in order."""
        positions = {row: position for position, row in enumerate(view.shown_rows)}
        return sorted(positions[row] for row in rows if row in positions)

    @classmethod
    def _refresh_selected_rows(
        cls, view: TableViewLike, rendered_object: ComposeFilterTable, value: list[int]
    ) -> None:
        rendered_object.table.set_selected_rows(cls._positions(view, value))

    @classmethod
    def _refresh_shown_rows(
        cls, view: TableViewLike, rendered_object: ComposeFilterTable, value: list[int]
    ) -> None:
        rendered_object.table.fill(
            view.headers,
            [view.rows[row] for row in value],
            cls._positions(view, view.selected_rows),
            view.shown_cell_styles(),
            [view.row_headers[row] if row < len(view.row_headers) else "" for row in value]
            if len(view.row_headers) > 0
            else [],
        )
        rendered_object.bar.set_count(_count_text(view, value))
        rendered_object.empty.display = len(value) == 0 and len(view.rows) > 0
        cls._refresh_checked_columns(view, rendered_object)

    @staticmethod
    def _refresh_checked_columns(
        view: TableViewLike,
        rendered_object: ComposeFilterTable,
        *,
        cell_widgets: dict[int, CellWidget] | None = None,
    ) -> None:
        """Show each check-all box; with the new widgets, which the view doesn't hold yet."""
        widgets = view.cell_widgets if cell_widgets is None else cell_widgets
        rendered_object.table.set_checked_columns(
            {
                column: view.column_checked(column)
                for column, widget in widgets.items()
                if widget.kind is CellKind.CHECK_BOX and widget.check_all
            }
        )

    @staticmethod
    def _refresh_editable_columns(
        _view: TableViewLike, rendered_object: ComposeFilterTable, value: list[int]
    ) -> None:
        rendered_object.table.editable_columns = value

    @classmethod
    def _refresh_cell_widgets(
        cls, view: TableViewLike, rendered_object: ComposeFilterTable, value: dict[int, CellWidget]
    ) -> None:
        rendered_object.table.set_cell_widgets(value)
        cls._refresh_checked_columns(view, rendered_object, cell_widgets=value)

    @staticmethod
    def _refresh_file_texts(
        _view: TableViewLike, rendered_object: ComposeFilterTable, value: dict[str, str]
    ) -> None:
        rendered_object.table.file_texts = value

    @classmethod
    def _refresh_looks(
        cls, view: TableViewLike, rendered_object: ComposeFilterTable, _value: Any
    ) -> None:
        cls._refresh_shown_rows(view, rendered_object, view.shown_rows)

    @staticmethod
    def _refresh_header_groups(
        _view: TableViewLike, rendered_object: ComposeFilterTable, value: list[HeaderGroup]
    ) -> None:
        rendered_object.table.set_header_groups(value)

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

    def _activate_row(self, position: int) -> None:
        self._view.row_activated.emit(self._view.shown_rows[position])

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

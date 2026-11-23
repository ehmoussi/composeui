"""The web renderers of tables: a table of rows, and a large table read from a source."""

from __future__ import annotations

import contextlib
import json
import math
from abc import abstractmethod
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Callable, ClassVar, Final

import attrs
from markupsafe import Markup, escape
from typing_extensions import Protocol, override

from composeui.core._views.files import is_within_roots
from composeui.core._views.tables import PLAIN_CELL, SourceTableByPosition, split_pattern
from composeui.core.model import RefusedError
from composeui.core.renderer import ViewLike
from composeui.core.view import (
    CHECKED_TEXTS,
    SEARCH_DELAY_MS,
    CellKind,
    NodeMark,
    SelectionMode,
    as_pattern,
)
from composeui.webcore._renderers.files import _PATH_KINDS, _FilesTexts, _ServerFiles
from composeui.webcore.changes import _DIRTY
from composeui.webcore.serverfiles import resolve_roots
from composeui.webcore.webrenderer import (
    _MARK_ICONS,
    TView,
    UnsupportedEventError,
    WebRenderer,
    _file_types,
    _icon,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping
    from pathlib import Path

    from composeui.core.signal import Signal
    from composeui.core.view import CellStyle, CellWidget, HeaderGroup


#: the rows of a large table the page draws at once, around those scrolled to
SOURCE_TABLE_WINDOW_ROWS = 100
#: the rows of a large table that the scroll bar's height can stand for at most, 2.25rem
#: each: past them, a scroll position maps to a row by its ratio, as browsers cap an
#: element's height (about 33M pixels in Chrome, 17M in Firefox)
SOURCE_TABLE_SCROLLED_ROWS = 400_000


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

    def refusing(self, message: str) -> contextlib.AbstractContextManager[None]: ...
    def edit_cell(
        self,
        row: int,
        column: int,
        text: str,
        assign: Callable[[list[list[str]]], None] | None = None,
    ) -> bool: ...
    def mark_text(self, mark: NodeMark) -> str: ...
    def shown_cell_styles(self) -> dict[tuple[int, int], CellStyle]: ...
    def is_checked(self, row: int, column: int) -> bool: ...
    def cell_widget(self, row: int, column: int) -> CellWidget | None: ...
    def cell_style(self, row: int, column: int) -> CellStyle: ...
    def header_group(self, column: int) -> HeaderGroup | None: ...
    def column_checked(self, column: int) -> bool | None: ...
    def check_all(self, column: int, *, is_checked: bool) -> None: ...
    def sort_by(self, column: int) -> None: ...
    def filter_error(self, column: int, text: str) -> str | None: ...
    def filter_placeholder(self, column: int, *, is_pattern: bool = False) -> str: ...
    def filter_takes_pattern(self, column: int) -> bool: ...
    def filter_chip(self, column: int) -> str: ...


#: the order a sortable column's header shows, as `aria-sort` says it
_ARIA_SORT: Final[dict[bool | None, str]] = {None: "none", False: "ascending", True: "descending"}


class FilteredLike(Protocol):
    """What a table's filter bar reads and sets, its columns known by their positions."""

    search: str
    filters: dict[int, str]

    @property
    def headers(self) -> list[str]: ...
    @property
    def filter_texts(self) -> dict[str, str]: ...
    @property
    def filterable_columns(self) -> list[int]: ...
    def filter_error(self, column: int, text: str) -> str | None: ...
    def filter_takes_pattern(self, column: int) -> bool: ...
    def filter_placeholder(self, column: int, *, is_pattern: bool = False) -> str: ...
    def filter_chip(self, column: int) -> str: ...


#: the parts of a filter bar each part holds: the count is in the bar
_BAR_PARTS_INSIDE: Mapping[str, tuple[str, ...]] = MappingProxyType({"bar": ("count",)})


class WebFilterBarRenderer(WebRenderer[TView]):
    """A table's renderer with a filter bar: a search, "+ Filter" and the filters' chips.

    The bar reads and sets `_filtered`, its columns known by their positions. The search
    posts as the user types; "+ Filter" opens an editor in the bar (a column, a value and
    Add), and the filters show as chips. A change swaps only the parts it changes
    (`_mark_parts`): "bar", "count" or "error", never the field the user types in. A
    value that can't filter swaps only its message in, the page marking the field invalid.

    A table adds its own parts (`_own_parts`), and what one holds (`_parts_inside`): a
    change marking the whole (`_mark_dirty`) swaps the table whole.
    """

    #: the parts each part holds, which swap with it rather than apart
    _parts_inside: ClassVar[Mapping[str, tuple[str, ...]]] = _BAR_PARTS_INSIDE

    def __init__(self, view: TView) -> None:
        super().__init__(view)
        #: the parts to swap, unless the whole table is (`_mark_dirty`)
        self._dirty_parts: set[str] = set()
        self._is_whole_dirty = False
        #: the filter editor, while open: its column (None for the first) and its text
        self._editor: tuple[int | None, str] | None = None
        #: why the editor's text can't filter, once the user added it
        self._editor_error: str | None = None
        #: whether "+ Filter" takes the focus back, the editor or a chip just gone
        self._focus_add_filter = False
        #: the column whose chip takes the focus, its filter just added: Enter reopens it
        self._focused_chip: int | None = None

    @staticmethod
    def _table_part(markup: Markup, *, oob: bool) -> Markup:
        """Wrap a part of the `<table>` swapped out of band in a `<template>` of its own.

        htmx parses an answer as a template's content. A `<tr>` or a `<tbody>` among the
        rest would switch the parser to a table's rules for what follows, mangling the
        next fragments, e.g. another table swapped whole.
        """
        return Markup("<template>{}</template>").format(markup) if oob else markup

    @property
    @abstractmethod
    def _filtered(self) -> FilteredLike:
        """Get what the bar reads and sets: the view, or what knows its columns by position."""

    @abstractmethod
    def _count_text(self) -> str:
        """Count the rows shown, while the search or the filters hide some: else ""."""

    @abstractmethod
    def _own_parts(self) -> dict[str, Callable[..., Markup]]:
        """Get how to render each of the table's own parts, in the order they're swapped."""

    @abstractmethod
    def _whole_html(self, *, oob: bool) -> Markup:
        """Render the whole table, its bar and its parts."""

    @override
    def to_html(self, *, oob: bool = False) -> Markup:
        parts, self._dirty_parts = self._dirty_parts, set()
        is_whole, self._is_whole_dirty = self._is_whole_dirty or not oob or not parts, False
        html_ = self._whole_html(oob=oob) if is_whole else self._parts_html(parts)
        self._focus_add_filter, self._focused_chip = False, None
        return html_

    def _parts_html(self, parts: set[str]) -> Markup:
        """Render the parts changed, out of band, each one only once."""
        for part, inside in self._parts_inside.items():
            if part in parts:
                parts.difference_update(inside)
        if len(self._filterable_columns()) == 0:
            # a hidden bar draws no count: htmx would find no element to swap it into
            parts.discard("count")
        # the bar last: it may hold the element that sent the request, which htmx swaps
        # nothing more from once it's gone
        renders: dict[str, Callable[..., Markup]] = {
            **self._own_parts(),
            "count": self._count_html,
            "error": self._error_html,
            "bar": self._bar_html,
        }
        return Markup("").join(
            render(oob=True) for part, render in renders.items() if part in parts
        )

    @override
    def _mark_dirty(self, view: TView, rendered_object: str, value: Any) -> None:
        self._is_whole_dirty = True
        super()._mark_dirty(view, rendered_object, value)

    def _part_marker(self, *parts: str) -> Callable[[TView, str, Any], None]:
        """Get a refresh handler swapping these parts of the table."""

        def mark(_view: TView, _rendered_object: str, _value: Any) -> None:
            self._mark_parts(*parts)

        return mark

    def _mark_parts(self, *parts: str) -> None:
        """Swap these parts of the table: "bar", "count" or "error", or its own."""
        dirty = _DIRTY.get()
        if dirty is not None:
            self._dirty_parts.update(parts)
            dirty[self.widget_id] = self

    def _oob(self, *, oob: bool) -> Markup:
        return Markup(' hx-swap-oob="true"') if oob else Markup()

    def _post(self, values: Mapping[str, str | int]) -> Markup:
        """Get the attributes posting an event of the table, without swapping its element back."""
        return Markup(
            """ hx-post="/_composeui/widget/{}" hx-vals='{}'"""
            ' hx-swap="none"'
        ).format(self.widget_id, json.dumps(values))

    def _count_html(self, *, oob: bool = False) -> Markup:
        text = self._count_text()
        return Markup(
            '<span id="{widget_id}-count" class="ms-auto text-sm opacity-70"'
            ' aria-live="polite"{oob}>{text}</span>'
        ).format(widget_id=self.widget_id, oob=self._oob(oob=oob), text=text)

    def _filterable_columns(self) -> list[int]:
        return [
            column
            for column in self._filtered.filterable_columns
            if column < len(self._filtered.headers)
        ]

    def _bar_html(self, *, oob: bool = False) -> Markup:
        bar_id = f"{self.widget_id}-bar"
        if len(self._filterable_columns()) == 0:
            return Markup('<div id="{}" hidden{}></div>').format(bar_id, self._oob(oob=oob))
        texts = self._filtered.filter_texts
        disabled = "" if self.is_enabled else " disabled"
        search_label = texts.get("search", "")
        search = Markup(
            '<label class="input input-sm w-56">'
            '{search_icon}<input id="{widget_id}-search" type="search"'
            ' name="search" value="{search}"'
            ' placeholder="{search_label}" aria-label="{search_label}"'
            ' hx-post="/_composeui/widget/{widget_id}"'
            ' hx-trigger="input changed delay:{delay}ms, search"'
            ' hx-vals=\'{{"event": "search"}}\' hx-swap="none" hx-sync="this:queue last"'
            ' autocomplete="off" data-table-search{disabled}>'
            '<button type="button" class="btn btn-ghost btn-xs btn-circle -me-1"'
            ' aria-label="{clear_label}" title="{clear_label}" data-clear-search'
            "{hidden}{disabled}>\u00d7</button></label>"
        ).format(
            search_icon=_icon("search"),
            widget_id=self.widget_id,
            delay=SEARCH_DELAY_MS,
            search=self._filtered.search,
            search_label=search_label,
            clear_label=texts.get("clear_search", ""),
            hidden=" hidden" if self._filtered.search == "" else "",
            disabled=disabled,
        )
        if self._editor is None:
            focus = " autofocus" if self._focus_add_filter else ""
            editor = Markup(
                '<button id="{widget_id}-add-filter" type="button"'
                ' class="btn btn-sm btn-soft"{post}'
                "{focus}{disabled}>{get}</button>"
            ).format(
                widget_id=self.widget_id,
                post=self._post({"event": "open_editor"}),
                focus=focus,
                disabled=disabled,
                get=texts.get("add_filter", ""),
            )
        else:
            editor = self._editor_html()
        chips = Markup("").join(
            self._chip_html(column) for column in sorted(self._filtered.filters)
        )
        clear = ""
        if len(self._filtered.filters) >= 2:  # noqa: PLR2004
            clear = Markup(
                '<button type="button" class="btn btn-sm btn-ghost"{post}{disabled}>{get}</button>'
            ).format(
                post=self._post({"event": "clear_filters"}),
                disabled=disabled,
                get=texts.get("clear", ""),
            )
        return Markup(
            '<div id="{bar_id}" role="search" class="flex flex-wrap items-center gap-2"'
            "{oob}>{search}{editor}{chips}{clear}{count_html}</div>"
        ).format(
            bar_id=bar_id,
            oob=self._oob(oob=oob),
            search=search,
            editor=editor,
            chips=chips,
            clear=clear,
            count_html=self._count_html(),
        )

    def _editor_html(self) -> Markup:
        assert self._editor is not None
        texts = self._filtered.filter_texts
        columns = self._filterable_columns()
        column, typed = self._editor
        chosen = column if column in columns else columns[0]
        takes_pattern = self._filtered.filter_takes_pattern(chosen)
        # slashes are the pattern's only where a pattern is taken: else the text as typed
        text, is_pattern = split_pattern(typed) if takes_pattern else (typed, False)
        options = Markup("").join(
            Markup(
                '<option value="{option}"'
                ' data-placeholder="{filter_placeholder}"'
                ' data-pattern-placeholder="{pattern_placeholder}"'
                "{value}>"
                "{headers}</option>"
            ).format(
                option=option,
                filter_placeholder=self._filtered.filter_placeholder(option),
                pattern_placeholder=self._pattern_placeholder(option),
                value=" selected" if option == chosen else "",
                headers=self._filtered.headers[option],
            )
            for option in columns
        )
        value_id = f"{self.widget_id}-value"
        value_label = texts.get("value", "")
        pattern_label = texts.get("pattern", "")
        placeholder = self._filtered.filter_placeholder(chosen, is_pattern=is_pattern)
        # a checkbox drawn as a button: on, the value is a regular expression; the page
        # shows it only for a column a pattern filters, and hints at what to type
        pattern = Markup(
            '<label class="btn btn-sm btn-soft font-mono has-checked:btn-primary"'
            ' title="{pattern_label}" data-filter-pattern{value}>'
            '<input type="checkbox" name="pattern" value="1" class="sr-only"'
            ' aria-label="{pattern_label}"{value2}>.*</label>'
        ).format(
            pattern_label=pattern_label,
            value="" if takes_pattern else " hidden",
            value2=" checked" if is_pattern else "",
        )
        return Markup(
            '<form id="{widget_id}-editor" class="flex flex-wrap items-center gap-2"'
            "{post}>"
            '<select name="column" class="select select-sm w-auto" data-filter-column'
            ' aria-label="{get}">{options}</select>'
            "{pattern}"
            '<input id="{value_id}" name="value" class="input input-sm w-60" type="text"'
            ' value="{text}" aria-label="{value_label}"'
            ' placeholder="{placeholder}"'
            ' aria-describedby="{value_id}-error" autocomplete="off" autofocus'
            ' hx-post="/_composeui/widget/{widget_id}" hx-trigger="escape-key"'
            """ hx-vals='{{"event": "close_editor"}}' hx-swap="none">"""
            "{error_html}"
            '<button type="submit" class="btn btn-sm btn-primary">'
            "{get2}</button></form>"
        ).format(
            widget_id=self.widget_id,
            post=self._post({"event": "add_filter"}),
            get=texts.get("column", ""),
            options=options,
            pattern=pattern,
            value_id=value_id,
            text=text,
            value_label=value_label,
            placeholder=placeholder,
            error_html=self._error_html(),
            get2=texts.get("add", ""),
        )

    def _pattern_placeholder(self, column: int) -> str:
        """Hint at a regular expression filtering `column`, or "" if none does."""
        if not self._filtered.filter_takes_pattern(column):
            return ""
        return self._filtered.filter_placeholder(column, is_pattern=True)

    def _error_html(self, *, oob: bool = False) -> Markup:
        """Render the editor's message, why its text can't filter; the page marks the field."""
        error = self._editor_error
        hidden = "" if error else " hidden"
        return Markup(
            '<span id="{widget_id}-value-error" class="text-sm text-error"'
            ' data-log="error"{hidden}{oob}>{value}</span>'
        ).format(widget_id=self.widget_id, hidden=hidden, oob=self._oob(oob=oob), value=error or "")

    def _chip_html(self, column: int) -> Markup:
        if column >= len(self._filtered.headers):
            return Markup()
        texts, header = self._filtered.filter_texts, self._filtered.headers[column]
        remove = texts.get("remove", "{header}").format(header=header)
        edit = texts.get("edit", "{header}").format(header=header)
        disabled = "" if self.is_enabled else " disabled"
        focus = " autofocus" if self._focused_chip == column else ""
        # named by its text, the filter; the pencil and the tooltip say it edits it
        return Markup(
            '<span class="badge badge-soft badge-primary gap-1 pe-0">'
            '<button id="{widget_id}-chip-{column}" type="button"'
            ' class="inline-flex cursor-pointer items-center gap-1 hover:underline"'
            ' title="{edit}"'
            "{post}{focus}{disabled}>"
            "{filter_chip}{pencil_icon}</button>"
            '<button type="button" class="btn btn-ghost btn-xs btn-circle"'
            ' aria-label="{remove}" title="{remove}"'
            "{post2}{disabled}>\u00d7</button>"
            "</span>"
        ).format(
            widget_id=self.widget_id,
            column=column,
            edit=edit,
            post=self._post({"event": "open_editor", "column": column}),
            focus=focus,
            disabled=disabled,
            filter_chip=self._filtered.filter_chip(column),
            pencil_icon=_icon("pencil", "size-3"),
            remove=remove,
            post2=self._post({"event": "remove_filter", "column": column}),
        )

    def _column(self, form: Mapping[str, str], columns: list[int]) -> int | None:
        """Get the column posted, if one of `columns`: a stale page may post another."""
        column = form.get("column", "")
        return int(column) if column.isdigit() and int(column) in columns else None

    def _search(self, form: Mapping[str, str]) -> None:
        # not swapped back: the user is typing in it
        with self.stop_refresh():
            self._filtered.search = form.get("search", "")

    def _open_editor(self, form: Mapping[str, str]) -> None:
        column = self._column(form, self._filterable_columns())
        text = self._filtered.filters.get(column, "") if column is not None else ""
        self._editor, self._editor_error = (column, text), None
        self._mark_parts("bar")

    def _close_editor(self, _form: Mapping[str, str]) -> None:
        self._editor, self._editor_error = None, None
        self._focus_add_filter = True
        self._mark_parts("bar")

    def _add_filter(self, form: Mapping[str, str]) -> None:
        column = self._column(form, self._filterable_columns())
        if column is None or self._editor is None:
            self._mark_parts("bar")  # a stale page: the bar as it now is
            return
        text = form.get("value", "")
        if form.get("pattern") == "1" and self._filtered.filter_takes_pattern(column):
            text = as_pattern(text)
        error = self._filtered.filter_error(column, text)
        if error is not None:
            # the field keeps the text typed: only its message is swapped in
            self._editor, self._editor_error = (column, text), error
            self._mark_parts("error")
            return
        self._close_editor(form)
        self._focus_add_filter, self._focused_chip = False, column
        self._filtered.filters = {**self._filtered.filters, column: text}

    def _remove_filter(self, form: Mapping[str, str]) -> None:
        column = self._column(form, list(self._filtered.filters))
        self._focus_add_filter = True
        self._mark_parts("bar")
        if column is not None:
            self._filtered.filters = {
                other: text for other, text in self._filtered.filters.items() if other != column
            }

    def _clear_filters(self, _form: Mapping[str, str]) -> None:
        self._focus_add_filter = True
        self._mark_parts("bar")
        self._filtered.filters = {}


class WebTableRenderer(WebFilterBarRenderer[TableViewLike]):
    """A table under its filter bar, scrolling sideways on its own when wider than the page.

    Clicking a row, or pressing Enter on it, selects it. The table is swapped back to
    show it selected, each row keeping its own id so htmx gives the focus back to the
    row that had it. Selecting one row, it is the current one (`aria-current`).
    Selecting several, the table is a grid whose rows are each selected or not
    (`aria-selected`), and a click adds or removes its row.

    Double clicking a cell of `editable_columns`, or pressing F2 on its row (see
    `tables.js`), edits it. The table comes back with a field in the cell, named by its
    header, its text selected. Enter or leaving the field posts the text, Escape puts the
    old text back first; either way the cell is text again. The page keeps the text the
    user is typing through a swap of the table, e.g. answering the double click's clicks.

    A column of `cell_widgets` holds a widget in each cell: a check box or a select,
    posting its change and never swapped back for it (only a check-all box in the header
    follows). A button after the cell's text, or the text as a link-like button, posting
    a click. A check-all column's header starts with its box, partly checked (see
    `tables.js`) while some rows are; its click swaps back the rows, not itself. A file
    path is typed as a plain cell, and its "…" button opens the browser's picker, a
    hidden file input uploading the file picked with its row and column
    (`/_composeui/widget/{id}/file`, see `WebSession.pick_file`). The cell then shows its copy's
    path.

    A cell of `cell_styles` has its background color, its text black or white on it, and
    its mark before its text, named for screen readers. A disabled one is grayed, its
    widget disabled and its text never edited. A cell spanning rows covers those under
    it (`rowspan`). The rows' headers start each row (`<th scope="row">`), and
    `header_groups` add a row of headers above the columns', each over its columns.

    The table shows `shown_rows`, each row keeping the id of its index in `rows`. A
    sortable column's header is a button sorting by it. While a column filters, the bar
    above the table has a search, posted as the user types, and "+ Filter", opening an
    editor in the bar: a column, a value and Add. The filters show as chips. A sort, a
    search or a filter swaps only what it changes (the headers, the body, the count, the
    bar), never the field the user types in. A value that can't filter swaps only its
    message in, the page marking the field invalid.
    """

    _role = "table"

    def __init__(self, view: TableViewLike) -> None:
        super().__init__(view)
        #: the cell the user is editing, by row and column
        self._editing: tuple[int, int] | None = None
        self._server_files: _ServerFiles | None = None
        #: the file path cell the list of the server's files picks for
        self._files_cell: tuple[int, int] | None = None
        #: whether the page has the list of the server's files, drawn with the whole table
        self._has_files = False
        self._refresh_dispatcher.update(
            {
                "headers": self._mark_dirty,
                "filter_texts": self._mark_dirty,
                "file_texts": self._mark_dirty,
                "selection_mode": self._mark_dirty,
                "rows": self._refresh_rows,
                "sortable_columns": self._mark_dirty,
                "filterable_columns": self._mark_dirty,
                "sort_column": self._part_marker("head"),
                "sort_descending": self._part_marker("head"),
                "search": self._part_marker("bar"),
                "filters": self._part_marker("bar"),
                "selected_rows": self._mark_dirty,
                "shown_rows": self._part_marker("body", "count"),
                "editable_columns": self._mark_dirty,
                "cell_widgets": self._mark_dirty,
                "cell_styles": self._part_marker("body"),
                "header_groups": self._mark_dirty,
                "row_headers": self._mark_dirty,
                "done_text": self._part_marker("body"),
                "warning_text": self._part_marker("body"),
                "error_text": self._part_marker("body"),
            }
        )

    def _refresh_rows(self, view: TableViewLike, rendered_object: str, value: Any) -> None:
        self._editing = None  # its row may have moved, or be gone
        self._mark_dirty(view, rendered_object, value)

    @property
    @override
    def _filtered(self) -> FilteredLike:
        return self._view

    @override
    def _count_text(self) -> str:
        shown, total = len(self._view.shown_rows), len(self._view.rows)
        if shown == total:
            return ""
        return self._view.filter_texts.get("count", "").format(shown=shown, total=total)

    @override
    def _own_parts(self) -> dict[str, Callable[..., Markup]]:
        return {
            "head": self._head_html,
            "body": self._body_html,
            "files": self._files_html,
            "files-list": self._files_list_html,
        }

    @override
    def _whole_html(self, *, oob: bool) -> Markup:
        grid = Markup(' role="grid" aria-multiselectable="true"') if self._is_multiple() else ""
        # a widget that `cell_widget` gave a cell since may have opened it: see `_mark_files`
        is_open = self._server_files is not None and self._server_files.is_open
        self._has_files = is_open or any(
            widget is not None and widget.kind.is_path and widget.server_roots
            for widget in self._path_widgets()
        )
        return Markup(
            '<div {root_attributes} class="flex flex-col gap-2">'
            "{bar_html}"
            '<div class="overflow-x-auto rounded-box border border-base-300">'
            '<table class="table table-zebra table-sm"{grid}>'
            "{head_html}{body_html}</table></div>{files_html}</div>"
        ).format(
            root_attributes=self._root_attributes(oob=oob),
            bar_html=self._bar_html(),
            grid=grid,
            head_html=self._head_html(),
            body_html=self._body_html(),
            files_html=self._files_html() if self._has_files else "",
        )

    @property
    def _files(self) -> _ServerFiles:
        # once rendered, with its id
        if self._server_files is None:
            self._server_files = _ServerFiles(f"{self.widget_id}-files", self.widget_id)
        return self._server_files

    def _path_widgets(self) -> Iterator[CellWidget | None]:
        """Get the widgets of the columns, those of a `CellWidget.path_by`'s kinds, and the cells'.

        The cells' are those of the rows shown, which `cell_widget` may give alone.
        """
        for widget in self._view.cell_widgets.values():
            yield widget
            yield from widget.editors.values()
        for row in self._view.shown_rows:
            for column in range(len(self._view.headers)):
                yield self._view.cell_widget(row, column)

    def _mark_files(self, part: str) -> None:
        """Mark a part of the list of the server's files, or the table if the page lacks it.

        The page lacks it when only `cell_widget` gave a cell a widget that lists them.
        """
        if self._has_files:
            self._mark_parts(part)
        else:
            self._mark_dirty(self._view, self.widget_id, self._view.rows)

    def _files_widget(self) -> CellWidget | None:
        """Get the widget of the cell the list of the server's files picks for, if still one.

        One of the kind of path the list was opened for: the row's kind may have changed.
        """
        cell = self._files_cell
        widget = None if cell is None else self._view.cell_widget(*cell)
        if (
            widget is None
            or widget.kind is not _PATH_KINDS[self._files.kind]
            or not widget.server_roots
        ):
            return None
        return widget

    def _files_texts(self, widget: CellWidget | None) -> _FilesTexts:
        texts = self._view.file_texts
        return _FilesTexts(
            "" if widget is None else widget.text,
            texts.get("parent_folder", ""),
            texts.get("cancel", ""),
            texts.get("unreadable_folder", ""),
            texts.get("partial_folder", ""),
            texts.get("choose_folder", ""),
            texts.get("file_name", ""),
            texts.get("save", ""),
            texts.get("replace_question", ""),
            texts.get("replace", ""),
        )

    def _files_html(self, *, oob: bool = False) -> Markup:
        """Render the list of the server's files of a file path cell, hidden while closed."""
        widget = self._files_widget()
        return self._files.dialog_html(
            self._files_texts(widget),
            [] if widget is None else resolve_roots(widget.server_roots),
            () if widget is None else tuple(_file_types(widget.extensions)),
            is_enabled=self.is_enabled and widget is not None,
            oob=oob,
        )

    def _files_list_html(self, *, oob: bool = False) -> Markup:
        widget = self._files_widget()
        return self._files.list_html(
            self._files_texts(widget),
            [] if widget is None else resolve_roots(widget.server_roots),
            () if widget is None else tuple(_file_types(widget.extensions)),
            oob=oob,
        )

    def _head_html(self, *, oob: bool = False) -> Markup:
        """Render the headers: a row of them, under a row of `header_groups` if any.

        A column without a group has its header across both rows.
        """
        headers = self._view.headers
        groups = [group for group in self._view.header_groups if group.column < len(headers)]
        span = Markup(' rowspan="2"') if len(groups) > 0 else ""
        # the corner over the rows' headers
        top = [Markup("<td{}></td>").format(span)] if len(self._view.row_headers) > 0 else []
        bottom = []
        for column in range(len(headers)):
            group = self._view.header_group(column)
            if group is None:
                top.append(self._header_html(column, span))
                continue
            if group.column == column:
                columns = min(group.column_count, len(headers) - column)
                top.append(
                    Markup('<th colspan="{}" scope="colgroup" class="text-center">{}</th>').format(
                        columns, group.text
                    )
                )
            bottom.append(self._header_html(column, ""))
        rows = Markup("<tr>{}</tr>").format(Markup("").join(top)) + (
            Markup("<tr>{}</tr>").format(Markup("").join(bottom)) if groups else ""
        )
        return self._table_part(
            Markup('<thead id="{widget_id}-head"{oob}>{rows}</thead>').format(
                widget_id=self.widget_id, oob=self._oob(oob=oob), rows=rows
            ),
            oob=oob,
        )

    def _header_html(self, column: int, span: str) -> Markup:
        """Render a column's header, with its check-all box, a button if sortable."""
        header = self._view.headers[column]
        box = self._check_all_html(column)
        if column not in self._view.sortable_columns:
            if box == "":
                return Markup("<th{}>{}</th>").format(span, header)
            return Markup(
                '<th{span}><span class="flex items-center gap-2">{box}{header}</span></th>'
            ).format(span=span, box=box, header=header)
        order = self._view.sort_descending if self._view.sort_column == column else None
        arrow = {None: "", False: " ▲", True: " ▼"}[order]
        disabled = "" if self.is_enabled else " disabled"
        return Markup(
            '<th{span} aria-sort="{ARIA_SORT}" class="p-0">'
            '<span class="flex items-center{value}">{box}'
            '<button type="button" class="btn btn-ghost btn-sm flex-1 justify-start'
            ' font-semibold"{post}{disabled}>'
            '{header}<span aria-hidden="true">{arrow}</span></button></span></th>'
        ).format(
            span=span,
            ARIA_SORT=_ARIA_SORT[order],
            value=" ps-3" if box else "",
            box=box,
            post=self._post({"event": "sort", "column": column}),
            disabled=disabled,
            header=header,
            arrow=arrow,
        )

    def _body_html(self, *, oob: bool = False) -> Markup:
        shown = self._view.shown_rows
        styles = self._view.shown_cell_styles()
        covered = {
            (position + offset, column)
            for (position, column), style in styles.items()
            for offset in range(1, style.row_span)
        }
        rows = Markup("").join(
            self._row_html(index, self._view.rows[index], position, styles, covered)
            for position, index in enumerate(shown)
        )
        if len(shown) == 0 and len(self._view.rows) > 0:
            no_match = self._view.filter_texts.get("no_match", "")
            columns = max(len(self._view.headers), 1) + (1 if self._view.row_headers else 0)
            rows = Markup(
                '<tr><td colspan="{}" class="text-center opacity-70">{}</td></tr>'
            ).format(columns, no_match)
        return self._table_part(
            Markup('<tbody id="{widget_id}-body"{oob}>{rows}</tbody>').format(
                widget_id=self.widget_id, oob=self._oob(oob=oob), rows=rows
            ),
            oob=oob,
        )

    def _check_all_html(self, column: int) -> Markup:
        """Render a check-all column's box, or "" for another column."""
        if column not in self._check_all_columns():
            return Markup()
        is_checked = self._view.column_checked(column)
        state = {True: " checked", False: "", None: " data-indeterminate"}[is_checked]
        disabled = "" if self.is_enabled and column in self._view.editable_columns else " disabled"
        # its own id, so htmx gives it the focus back when the head is swapped
        return Markup(
            '<input id="{widget_id}-check-all-{column}" type="checkbox"'
            ' class="checkbox checkbox-sm" aria-label="{headers}" name="checked" value="on"'
            "{state}{post}"
            ' hx-trigger="change" autocomplete="off"{disabled}>'
        ).format(
            widget_id=self.widget_id,
            column=column,
            headers=self._view.headers[column],
            state=state,
            post=self._post({"event": "check_all", "column": column}),
            disabled=disabled,
        )

    def _check_all_columns(self) -> list[int]:
        return [
            column
            for column, widget in self._view.cell_widgets.items()
            if widget.kind is CellKind.CHECK_BOX
            and widget.check_all
            and column < len(self._view.headers)
        ]

    def _row_html(
        self,
        index: int,
        row: list[str],
        position: int,
        styles: dict[tuple[int, int], CellStyle],
        covered: set[tuple[int, int]],
    ) -> Markup:
        """Render a row, at `position` among those shown, as `styles` say its cells look.

        The cells `covered` by a cell spanning rows above aren't rendered.
        """
        # a row short of an editable cell, a widget's or a styled one's still gets the
        # cell, empty
        widths = [
            *self._editable_columns(),
            *(
                column
                for column in range(len(row), len(self._view.headers))
                if self._view.cell_widget(index, column) is not None
            ),
            *(column for shown, column in styles if shown == position),
        ]
        width = max(len(row), *(column + 1 for column in widths), 0)
        cells = Markup("").join(
            self._cell_html(
                index,
                column,
                row[column] if column < len(row) else "",
                styles.get((position, column), PLAIN_CELL),
            )
            for column in range(width)
            if (position, column) not in covered
        )
        if len(self._view.row_headers) > 0:
            header = self._view.row_headers[index] if index < len(self._view.row_headers) else ""
            cells = Markup('<th scope="row">{}</th>{}').format(header, cells)

        is_selected = index in self._view.selected_rows
        if self._is_multiple():
            selected = Markup(' aria-selected="{}"').format("true" if is_selected else "false")
        else:
            selected = Markup(' aria-current="true"') if is_selected else Markup()
        if not self.is_enabled:
            return Markup("<tr{}>{}</tr>").format(selected, cells)
        return Markup(
            '<tr id="{widget_id}-row-{index}" class="cursor-pointer" tabindex="0"'
            '{selected} hx-post="/_composeui/widget/{widget_id}"'
            # a click or Enter, not from a cell's field or widget, which takes its own
            ' hx-trigger="activate"'
            """ hx-vals='{{"event": "select", "row": "{index}"}}'"""
            ' hx-swap="none"'
            # a double click or Enter then activates it (see `tables.js`)
            ' data-activate="{index}">'
            "{cells}</tr>"
        ).format(widget_id=self.widget_id, index=index, selected=selected, cells=cells)

    def _cell_html(self, row: int, column: int, text: str, style: CellStyle) -> Markup:
        """Render a cell: its mark, then its text, widget or field, as `style` says."""

        def post(event: str) -> Markup:
            return Markup(
                ' hx-post="/_composeui/widget/{widget_id}" hx-swap="none"'
                """ hx-vals='{{"event": "{event}", "row": "{row}", "column": "{column}"}}'"""
            ).format(widget_id=self.widget_id, event=event, row=row, column=column)

        widget = self._view.cell_widget(row, column)
        is_typed = self._is_typed(column, widget) and self.is_enabled and style.is_enabled
        # a file path's, typed in, is a field while edited
        if (
            widget is not None
            and column < len(self._view.headers)
            and self._editing != (row, column)
        ):
            content = self._widget_html(row, column, text, widget, is_disabled=not style.is_enabled)
            # a disabled widget is grayed already
            look = self._look(attrs.evolve(style, is_enabled=True))
            edit = Markup(' data-edit hx-trigger="dblclick"{}').format(post("start_edit"))
            return Markup("<td{}{}>{}</td>").format(
                look, edit if is_typed else Markup(), self._marked(style, content)
            )
        if not is_typed:
            return Markup("<td{}>{}</td>").format(self._look(style), self._marked(style, text))
        if self._editing != (row, column):
            return Markup('<td{look} data-edit hx-trigger="dblclick"{post}>{marked}</td>').format(
                look=self._look(style), post=post("start_edit"), marked=self._marked(style, text)
            )
        header = self._view.headers[column]
        # its own id, so htmx gives it the focus back when the table is swapped
        return Markup(
            '<td{look}><input id="{widget_id}-cell-{row}-{column}"'
            ' type="text"'
            ' class="input input-ghost input-sm w-full min-w-0" name="text" data-cell'
            ' value="{text}" data-original="{text}"'
            ' aria-label="{header}" autocomplete="off" autofocus'
            ' hx-trigger="enter-key, blur"'
            "{post}></td>"
        ).format(
            look=self._look(style, "p-0"),
            widget_id=self.widget_id,
            row=row,
            column=column,
            text=text,
            header=header,
            post=post("edit"),
        )

    @staticmethod
    def _look(style: CellStyle, classes: str = "") -> Markup:
        """Get the attributes giving a cell its colors, grayed if disabled, and its rows' span."""
        if not style.is_enabled:
            classes = f"{classes} opacity-50".strip()
        attributes = Markup(' class="{}"').format(classes) if classes else Markup()
        if style.background is not None:
            attributes += Markup(' style="background-color: {}; color: {}"').format(
                style.background, style.text_color
            )
        if style.row_span > 1:
            attributes += Markup(' rowspan="{}"').format(style.row_span)
        return attributes

    def _marked(self, style: CellStyle, content: str) -> Markup:
        """Put the cell's mark, if any, before its content, named for screen readers."""
        if style.mark is None:
            return escape(content)
        icon, color = _MARK_ICONS[style.mark]
        text = self._view.mark_text(style.mark)
        return Markup(
            '<span class="flex items-center gap-1"><span class="shrink-0 {color}" role="img"'
            ' aria-label="{text}" title="{text}">{icon}</span>{content}</span>'
        ).format(color=color, text=text, icon=_icon(icon), content=content)

    def _widget_html(
        self, row: int, column: int, text: str, widget: CellWidget, *, is_disabled: bool
    ) -> Markup:
        """Render a cell's widget, named by its column's header; disabled with its cell."""
        header = self._view.headers[column]
        is_editable = self.is_enabled and column in self._view.editable_columns and not is_disabled
        values = {"row": row, "column": column}
        # its own id, so htmx gives it the focus back when the table is swapped
        widget_id = f"{self.widget_id}-cell-{row}-{column}"
        if widget.kind is CellKind.CHECK_BOX:
            checked = " checked" if self._view.is_checked(row, column) else ""
            return Markup(
                '<input id="{widget_id}" type="checkbox" class="checkbox checkbox-sm"'
                ' name="checked" value="on" aria-label="{header}"{checked}'
                '{post} hx-trigger="change"'
                ' autocomplete="off"{value}>'
            ).format(
                widget_id=widget_id,
                header=header,
                checked=checked,
                post=self._post({"event": "check", **values}),
                value="" if is_editable else " disabled",
            )
        if widget.kind is CellKind.COMBOBOX:
            options = [*widget.options, *([] if text in widget.options else [text])]
            choices = Markup("").join(
                Markup('<option value="{option}"{value}>{option}</option>').format(
                    option=option, value=" selected" if option == text else ""
                )
                for option in options
            )
            return Markup(
                '<select id="{widget_id}" class="select select-sm w-full min-w-24" name="text"'
                ' aria-label="{header}"{post}'
                ' hx-trigger="change" autocomplete="off"{value}>'
                "{choices}</select>"
            ).format(
                widget_id=widget_id,
                header=header,
                post=self._post({"event": "pick", **values}),
                value="" if is_editable else " disabled",
                choices=choices,
            )
        disabled = "" if self.is_enabled and not is_disabled else " disabled"
        click = self._post({"event": "click_cell", **values})
        if widget.kind is CellKind.LINK:
            return Markup(
                '<button id="{widget_id}" type="button" class="link'
                ' link-primary"{click}{disabled}>{text}</button>'
            ).format(widget_id=widget_id, click=click, disabled=disabled, text=text)
        if widget.kind.is_path:
            return self._path_html(row, column, text, widget, is_editable=is_editable)
        label = f"{self._view.headers[column]}: {widget.text}"
        return Markup(
            '<span class="flex items-center gap-2"><span class="flex-1">{text}'
            '</span><button id="{widget_id}" type="button" class="btn btn-xs btn-soft"'
            ' aria-label="{label}" title="{label}"{click}{disabled}>'
            "{text2}</button></span>"
        ).format(
            text=text,
            widget_id=widget_id,
            label=label,
            click=click,
            disabled=disabled,
            text2=widget.text,
        )

    def _path_html(
        self, row: int, column: int, text: str, widget: CellWidget, *, is_editable: bool
    ) -> Markup:
        """Render a path's text, then its "…" button: a file's opens the hidden file input.

        With `server_roots`, the button opens the list of the server's files instead. The
        browser can't give the page a folder's path, or one to save to: without
        `server_roots`, such a path is typed, and has no button.
        """
        label = f"{self._view.headers[column]}: {widget.text}"
        widget_id = f"{self.widget_id}-cell-{row}-{column}"
        types = ",".join(_file_types(widget.extensions))
        disabled = "" if is_editable else " disabled"
        if widget.server_roots:
            return Markup(
                '<span class="flex items-center gap-2"><span class="flex-1">{text}</span>'
                '<button id="{widget_id}" type="button" class="btn btn-xs btn-soft"'
                ' aria-label="{label}" title="{label}"{browse}{disabled}>…</button></span>'
            ).format(
                text=text,
                widget_id=widget_id,
                label=label,
                browse=self._post({"event": "browse", "row": str(row), "column": str(column)}),
                disabled=disabled,
            )
        if widget.kind is not CellKind.FILE_PATH:
            return escape(text)
        return Markup(
            '<span class="flex items-center gap-2"><span class="flex-1">{text}</span>'
            '<button id="{widget_id}" type="button" class="btn btn-xs btn-soft"'
            ' aria-label="{label}" title="{label}" data-file-browse{disabled}>…</button>'
            # emptied once sent: picking the same file again is a change too
            '<input type="file" name="file"{accept} class="hidden" tabindex="-1"'
            ' aria-hidden="true" hx-post="/_composeui/widget/{table_id}/file"'
            """ hx-vals='{values}' hx-encoding="multipart/form-data" hx-trigger="change\""""
            ' hx-swap="none" data-clear-after-post autocomplete="off"{disabled}></span>'
        ).format(
            text=text,
            widget_id=widget_id,
            label=label,
            disabled=disabled,
            accept=Markup(' accept="{}"').format(types) if types else "",
            table_id=self.widget_id,
            values=json.dumps({"row": str(row), "column": str(column)}),
        )

    def file_path_cell(self, form: Mapping[str, str]) -> tuple[int, int] | None:
        """Get the file path cell an upload names, if the user can edit it; a stale page's, None.

        None too for a cell with `server_roots`, which lists the server's files: its page
        uploads nothing, and a crafted upload would write in `upload_folder`.
        """
        if not self.is_enabled:
            return None
        cell = self._widget_cell(form, (CellKind.FILE_PATH,))
        widget = None if cell is None else self._view.cell_widget(*cell)
        return None if widget is None or widget.server_roots else cell

    def file_types(self, cell: tuple[int, int]) -> list[str]:
        """Get the file types a file path cell's picker offers, e.g. [".csv"]; empty for any."""
        widget = self._view.cell_widget(*cell)
        assert widget is not None  # a cell `file_path_cell` found
        return _file_types(widget.extensions)

    def upload_folder(self, cell: tuple[int, int]) -> Path | None:
        """Get the folder that keeps a file path cell's upload, the app's; None: a copy."""
        widget = self._view.cell_widget(*cell)
        assert widget is not None  # a cell `file_path_cell` found
        return widget.upload_folder

    def holds_file(self, path: Path) -> bool:
        """Tell whether a file path cell names `path`, from its `base_folder` if relative."""
        path = path.resolve()
        for row, cells in enumerate(self._view.rows):
            for column, text in enumerate(cells):
                widget = self._view.cell_widget(row, column)
                if (
                    widget is not None
                    and widget.kind is CellKind.FILE_PATH
                    and widget.path(text).resolve() == path
                ):
                    return True
        return False

    def file_paths(self) -> set[str]:
        """Get the texts of the file path cells, the paths whose uploads are kept."""
        return {
            text
            for row, cells in enumerate(self._view.rows)
            for column, text in enumerate(cells)
            if getattr(self._view.cell_widget(row, column), "kind", None) is CellKind.FILE_PATH
        }

    def pick_file(self, cell: tuple[int, int] | None, path: Path | None) -> None:
        """Give a file path cell the path of the file its picker uploaded, as the user's edit.

        Without a cell, or a path, swap the table back as it now is, e.g. for a stale page.
        """
        if cell is not None and path is not None:
            widget = self._view.cell_widget(*cell)
            assert widget is not None  # a cell `file_path_cell` found
            self._set_widget_cell(cell, widget.path_text(path))
        # the picker only uploaded: the cell shows the path once swapped back
        self._mark_dirty(self._view, self.widget_id, self._view.rows)

    @override
    def dispatch(self, event: str, form: Mapping[str, str]) -> None:
        if event in ("start_edit", "edit"):
            self._edit(event, form)
            return
        if event.startswith("browse"):
            self._browse(event, form)
            return
        handlers = {
            "check": self._check,
            "pick": self._pick,
            "check_all": self._check_all,
            "click_cell": self._click_cell,
            "sort": self._sort,
            "search": self._search,
            "open_editor": self._open_editor,
            "close_editor": self._close_editor,
            "add_filter": self._add_filter,
            "remove_filter": self._remove_filter,
            "clear_filters": self._clear_filters,
        }
        if event in handlers:
            handlers[event](form)
            return
        if event not in ("select", "activate_row"):
            super().dispatch(event, form)
        row = form.get("row", "")
        if not row.isdigit() or int(row) not in self._view.shown_rows:
            # a row a stale page still shows: swap the table back as it now is
            self._mark_dirty(self._view, self.widget_id, self._view.rows)
            return
        if event == "activate_row":
            # the click or Enter before it has selected the row
            self._view.row_activated.emit(int(row))
            return
        if self._is_multiple():
            rows = sorted(set(self._view.selected_rows) ^ {int(row)})
        elif self._view.selected_rows == [int(row)]:
            return
        else:
            rows = [int(row)]
        self._view.selected_rows = rows
        self._view.selection_changed.emit(rows)

    def _sort(self, form: Mapping[str, str]) -> None:
        column = self._column(form, self._view.sortable_columns)
        if column is None:
            self._mark_parts("head", "body")  # as it now is
            return
        self._view.sort_by(column)

    def _edit(self, event: str, form: Mapping[str, str]) -> None:
        """Start editing a cell, or end it with the text posted."""
        # either way the table comes back: with the field, or with the cell's text
        self._mark_dirty(self._view, self.widget_id, self._view.rows)
        row, column = form.get("row", ""), form.get("column", "")
        if (
            not row.isdigit()
            or int(row) not in self._view.shown_rows
            or not column.isdigit()
            or not self._is_typed(int(column), self._view.cell_widget(int(row), int(column)))
            or not self._view.cell_style(int(row), int(column)).is_enabled
        ):
            return  # a cell a stale page still shows
        cell = (int(row), int(column))
        if event == "start_edit":
            self._editing = cell
            return
        if self._editing != cell:
            return  # a field already gone, e.g. leaving it after Enter
        self._editing = None
        cells, text = self._view.rows[cell[0]], form.get("text", "")
        if text == (cells[cell[1]] if cell[1] < len(cells) else ""):
            return
        widget = self._view.cell_widget(*cell)
        if widget is not None and widget.kind.is_path and widget.server_roots:
            path = widget.path(text)
            if text.strip() != "" and not is_within_roots(path, widget.server_roots):
                self._refuse_path(path)
                return
        # unless the app answered with its own rows, which it has marked to show
        self._view.edit_cell(*cell, text, self._assign_rows)

    def _refuse_path(self, path: Path) -> None:
        """Keep a file path cell's text, typed outside its roots, and say why."""
        message = self._view.file_texts.get("outside_roots", "")
        with (
            contextlib.suppress(RefusedError),
            self._view.refusing(message.replace("{path}", "{error}")),
        ):
            raise RefusedError(str(path))

    def _browse(self, event: str, form: Mapping[str, str]) -> None:
        """Open, move or close a path cell's list of the server's files, or pick a path.

        A file's, a folder's or one to save to, as the cell's widget says when it opens.
        """
        files = self._files
        if not files.takes(event):
            raise UnsupportedEventError(self, event)
        name = form.get("name", "")
        start = None
        if event == "browse":
            cell = self._widget_cell(form, _PATH_KINDS.values())
            opened = None if cell is None else self._view.cell_widget(*cell)
            if cell is None or opened is None or not opened.server_roots:
                return  # a cell a stale page still shows: the table comes back as it is
            self._files_cell = cell
            files.kind = next(kind for kind, path in _PATH_KINDS.items() if path is opened.kind)
            files.confirms_overwrite = opened.confirms_overwrite
            cells = self._view.rows[cell[0]]
            text = cells[cell[1]] if cell[1] < len(cells) else ""
            name = str(opened.path(text)) if text.strip() != "" else ""
            start = opened.base_folder
        widget = self._files_widget()
        if widget is None:  # its column changed since: nothing to pick for
            files.move("browse-close", "", [], ())
            self._mark_files("files")
            return
        was_open = files.is_open
        picked = files.move(
            event,
            name,
            resolve_roots(widget.server_roots),
            tuple(_file_types(widget.extensions)),
            start=start,
        )
        # opened or closed: the dialog; else only its list, the dialog left open
        self._mark_files("files-list" if was_open == files.is_open else "files")
        if picked is not None:
            self._set_widget_cell(self._files_cell, widget.path_text(picked))
            # unlike a check box's, the cell doesn't show it yet
            self._mark_parts("body")

    def _widget_cell(
        self, form: Mapping[str, str], kinds: Iterable[CellKind]
    ) -> tuple[int, int] | None:
        """Get the cell posted, if a shown one of a widget of `kinds` the user can use.

        A stale page may post another. A `CellWidget.path_by`'s cell is of its row's kind.
        """
        row, column = form.get("row", ""), form.get("column", "")
        if not row.isdigit() or int(row) not in self._view.shown_rows or not column.isdigit():
            return None
        widget = self._view.cell_widget(int(row), int(column))
        if (
            widget is None
            or widget.kind not in tuple(kinds)
            or int(column) >= len(self._view.headers)
        ):
            return None
        is_edit = widget.kind in (CellKind.CHECK_BOX, CellKind.COMBOBOX) or widget.kind.is_path
        if is_edit and int(column) not in self._view.editable_columns:
            return None
        if not self._view.cell_style(int(row), int(column)).is_enabled:
            return None
        return int(row), int(column)

    def _check(self, form: Mapping[str, str]) -> None:
        self._set_widget_cell(
            self._widget_cell(form, (CellKind.CHECK_BOX,)), CHECKED_TEXTS["checked" in form]
        )

    def _pick(self, form: Mapping[str, str]) -> None:
        self._set_widget_cell(self._widget_cell(form, (CellKind.COMBOBOX,)), form.get("text", ""))

    def _set_widget_cell(self, cell: tuple[int, int] | None, text: str) -> None:
        """Apply a check box's or a select's change, which the widget already shows."""
        if cell is None:
            self._mark_dirty(self._view, self.widget_id, self._view.rows)  # as it now is
            return
        cells = self._view.rows[cell[0]]
        if text == (cells[cell[1]] if cell[1] < len(cells) else ""):
            return
        widgets = self._row_widgets(cell[0])
        # unless the app answered with its own rows, which it has marked to show
        if self._view.edit_cell(*cell, text, self._assign_rows):
            if len(self._check_all_columns()) > 0:
                self._mark_parts("head")  # a check-all box follows its column's
            if self._row_widgets(cell[0]) != widgets:
                self._mark_parts("body")  # a cell's widget follows the edit, e.g. a kind's

    def _assign_rows(self, rows: list[list[str]]) -> None:
        """Set the user's edit in `rows`, which the widget already shows."""
        with self.stop_refresh():
            self._view.rows = rows

    def _row_widgets(self, row: int) -> list[CellWidget | None]:
        return [self._view.cell_widget(row, column) for column in range(len(self._view.headers))]

    def _check_all(self, form: Mapping[str, str]) -> None:
        column = self._column(form, self._check_all_columns())
        if column is None or column not in self._view.editable_columns:
            self._mark_parts("head")  # a stale page: the head as it now is
            return
        # the rows swapped back, not the box, which sent the request and shows the click. Its
        # state as the page showed it change, partly checked to checked: not the server's,
        # which a stale page may not show
        with self.stop_refresh():
            self._view.check_all(column, is_checked="checked" in form)
        self._editing = None
        self._mark_parts("body", "count")

    def _click_cell(self, form: Mapping[str, str]) -> None:
        cell = self._widget_cell(form, (CellKind.BUTTON, CellKind.LINK))
        if cell is None:
            self._mark_dirty(self._view, self.widget_id, self._view.rows)  # as it now is
            return
        self._view.cell_clicked.emit(*cell)

    def _editable_columns(self) -> list[int]:
        """Get the `editable_columns` the table has a header for."""
        return [
            column
            for column in self._view.editable_columns
            if 0 <= column < len(self._view.headers)
        ]

    def _is_typed(self, column: int, widget: CellWidget | None) -> bool:
        """Tell whether the user types in a cell of `column` with `widget`: a path, or none."""
        return column in self._editable_columns() and (widget is None or widget.kind.is_path)

    def _is_multiple(self) -> bool:
        return self._view.selection_mode is SelectionMode.MULTIPLE


class SourceTableViewLike(ViewLike, Protocol):
    texts: dict[str, str]
    sort_column: str | None
    sort_descending: bool
    selection_mode: SelectionMode
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
    @property
    def count_text(self) -> str: ...
    def rows(self, start: int, stop: int) -> list[tuple[Any, list[str]]]: ...
    def sort_by(self, column: str) -> None: ...
    def is_selected(self, row_id: Any) -> bool: ...
    def select_at(self, position: int) -> None: ...
    def extend_to(self, position: int) -> None: ...
    def activate_at(self, position: int) -> None: ...
    def header(self, column: str) -> str: ...
    def filter_error(self, column: str, text: str) -> str | None: ...
    def filter_takes_pattern(self, column: str) -> bool: ...
    def filter_placeholder(self, column: str, *, is_pattern: bool = False) -> str: ...
    def filter_chip(self, column: str) -> str: ...
    def selection_text(self) -> str: ...
    def csv_chunks(self) -> Iterator[str]: ...

    export_filename: str


class WebSourceTableRenderer(WebFilterBarRenderer[SourceTableViewLike]):
    """A large table, scrolled in a frame: the page draws only the rows around the view.

    The frame holds the headers, a window of `SOURCE_TABLE_WINDOW_ROWS` rows, and two filler
    rows that give the scroll bar the height of every row. When the user stops scrolling
    outside the window, `tables.js` posts the first row shown (`scroll`), and only the
    `<tbody>` comes back, the scroll position kept, that row still under the headers.
    Past `SOURCE_TABLE_SCROLLED_ROWS` rows, the fillers stop growing: a filler's height
    stands for more rows than as many drawn ones (`_fillers`).
    Each row starts with its position, from 1, and tells screen readers where it is
    (`aria-rowindex` of `aria-rowcount`).

    A new order of the rows (a sort, a search, a filter, the source changed) swaps the
    whole frame, scrolled to the top. A header is a button sorting by its column
    (`SourceTableView.sort_by`), keeping the focus as it comes back (`autofocus`). A click
    on a row, or Enter on it, selects it (`select_at`): only the rows come back, the row
    keeping the focus. A double click on a row, or Enter, then activates it (`activate_at`,
    posted by `tables.js`). The web doesn't extend a selection. While a
    column of `filterable_columns` filters, the filter bar (`WebFilterBarRenderer`) is
    above the frame. Ctrl+C in the frame posts `copy` (see `tables.js`): the selected rows'
    text (`SourceTableView.selection_text`) comes back in a hidden element, which the page
    writes to the clipboard. A link above the frame downloads the rows shown as CSV
    (`csv_chunks`, streamed by the `/_composeui/widget/{id}/csv` route).
    """

    #: its `dispatch` decides by event: a disabled table still scrolls and is read
    @property
    @override
    def takes_events(self) -> bool:
        return True

    _role = "source_table"

    def __init__(self, view: SourceTableViewLike) -> None:
        super().__init__(view)
        self._by_position = SourceTableByPosition(view)
        #: the position of the window's first row
        self._start = 0
        #: the filler's height above the window, in rows' heights, where the page scrolled
        #: to; None: its rows scaled (`_scale`)
        self._before: float | None = None
        #: the column whose header takes the focus as it comes back: the user sorted by it
        self._focused_header: str | None = None
        #: the position of the row that takes the focus as it comes back: the user selected it
        self._focused_row: int | None = None
        #: the text the user copied, sent once in the "copied" part; None: nothing to send
        self._copied: str | None = None
        self._refresh_dispatcher.update(
            {
                **dict.fromkeys(
                    ("source", "texts", "filter_texts", "filterable_columns"), self._mark_dirty
                ),
                "row_count": self._reorder,
                **dict.fromkeys(
                    ("column_formats", "selected_ids", "selection_mode"),
                    self._part_marker("rows"),
                ),
                "search": self._part_marker("bar"),
                "filters": self._part_marker("bar"),
                # shown with the order they give, which the view sends as `row_count`
                "sort_column": lambda _view, _table, _value: None,
                "sort_descending": lambda _view, _table, _value: None,
                # read as the user downloads
                "export_filename": lambda _view, _table, _value: None,
                # never: the web orders in the request's thread (`draws_on_main_thread`)
                "is_ordering": lambda _view, _table, _value: None,
            }
        )

    @property
    @override
    def _filtered(self) -> FilteredLike:
        return self._by_position

    @override
    def _count_text(self) -> str:
        return self._view.count_text

    def _reorder(self, _view: SourceTableViewLike, _rendered_object: str, _value: Any) -> None:
        """Show a new order of the rows from its first: the frame comes back to the top."""
        self._start, self._before = 0, None
        self._mark_parts("frame", "count")

    _parts_inside = MappingProxyType({**_BAR_PARTS_INSIDE, "frame": ("rows",)})

    @override
    def _own_parts(self) -> dict[str, Callable[..., Markup]]:
        return {"frame": self._frame_html, "rows": self._rows_html, "copied": self._copied_html}

    @override
    def _whole_html(self, *, oob: bool) -> Markup:
        return Markup(
            '<div {root_attributes} class="flex flex-col gap-2">{bar_html}'
            # a plain link: htmx can't start a download
            '<a class="btn btn-ghost btn-xs self-end" href="/_composeui/widget/{widget_id}/csv"'
            " download>{export}</a>{frame_html}{copied_html}</div>"
        ).format(
            root_attributes=self._root_attributes(oob=oob),
            bar_html=self._bar_html(),
            frame_html=self._frame_html(),
            copied_html=self._copied_html(),
            widget_id=self.widget_id,
            export=self._view.texts.get("export", ""),
        )

    @override
    def dispatch(self, event: str, form: Mapping[str, str]) -> None:
        # a scroll only reads: a disabled table still shows the rows scrolled to
        if not self.is_enabled and event != "scroll":
            super().dispatch(event, form)
        handlers: dict[str, Callable[[Mapping[str, str]], None]] = {
            "search": self._search,
            "open_editor": self._open_editor,
            "close_editor": self._close_editor,
            "add_filter": self._add_filter,
            "remove_filter": self._remove_filter,
            "clear_filters": self._clear_filters,
            "sort": self._sort,
            "select": self._select,
            "activate_row": self._activate,
            "scroll": self._scroll,
            "copy": self._copy,
        }
        if event not in handlers:
            super().dispatch(event, form)
        handlers[event](form)

    def _sort(self, form: Mapping[str, str]) -> None:
        column = form.get("column", "")
        if column not in self._view.column_names:
            super().dispatch("sort", form)
        self._focused_header = column
        self._view.sort_by(column)

    def _select(self, form: Mapping[str, str]) -> None:
        position = form.get("position", "")
        if not position.isdigit() or int(position) >= self._view.row_count:
            # a row a stale page still shows: swap the rows back as they now are
            self._mark_parts("rows")
            return
        self._focused_row = int(position)
        self._view.select_at(int(position))

    def _activate(self, form: Mapping[str, str]) -> None:
        position = form.get("row", "")
        if not position.isdigit() or int(position) >= self._view.row_count:
            self._mark_parts("rows")  # a row a stale page still shows
            return
        # the click or Enter before it has selected the row
        self._view.activate_at(int(position))

    def _scroll(self, form: Mapping[str, str]) -> None:
        """Draw the window around the first row shown, a fifth of it above.

        The page posts the row under the headers (`start`) and how far down the frame it
        is (`offset`, in rows' heights). The filler above the window gets the height that
        keeps that row there, the frame's scroll position kept.
        """
        shown = form.get("start", "")
        if not shown.isdigit():
            return
        last_start = max(self._view.row_count - SOURCE_TABLE_WINDOW_ROWS, 0)
        start = min(max(int(shown) - SOURCE_TABLE_WINDOW_ROWS // 5, 0), last_start)
        try:
            offset = float(form.get("offset", ""))
        except ValueError:
            offset = math.nan
        before = offset - (int(shown) - start) if math.isfinite(offset) else None
        if (start, before) != (self._start, self._before):
            self._start, self._before = start, before
            self._mark_parts("rows")

    def csv_file(self) -> tuple[str, Iterator[str]]:
        """Get the download's name, and the rows shown as CSV, in pieces."""
        return self._view.export_filename, self._view.csv_chunks()

    def _copy(self, _form: Mapping[str, str]) -> None:
        self._copied = self._view.selection_text()
        self._mark_parts("copied")

    def _copied_html(self, *, oob: bool = False) -> Markup:
        """Render the hidden element posting a copy, holding the text copied once answered.

        An answer (`data-copy-answer`, its text empty without a row selected) is sent
        once, out of band or in the whole table: the page waits for no other.
        """
        copied, self._copied = self._copied, None
        return Markup(
            '<pre id="{widget_id}-copied" hidden data-copied{answer}'
            ' hx-post="/_composeui/widget/{widget_id}"'
            """ hx-trigger="copy-rows" hx-vals='{{"event": "copy"}}' hx-swap="none"{oob}>"""
            "{copied}</pre>"
        ).format(
            widget_id=self.widget_id,
            answer=Markup() if copied is None else Markup(" data-copy-answer"),
            oob=Markup(' hx-swap-oob="true"') if oob else Markup(),
            copied="" if copied is None else copied,
        )

    def _scale(self) -> float:
        """Get the rows each row's height of the scroll bar stands for: 1 up to the cap."""
        return max(self._view.row_count / SOURCE_TABLE_SCROLLED_ROWS, 1.0)

    def _header_html(self, name: str, header: str, *, is_focused: bool) -> Markup:
        """Render a column's header: a button sorting by the column, its order after it."""
        view = self._view
        order = view.sort_descending if view.sort_column == name else None
        arrow = {None: "", False: " ▲", True: " ▼"}[order]
        return Markup(
            '<th scope="col" aria-sort="{aria_sort}" class="p-0">'
            '<button type="button" class="btn btn-ghost btn-sm w-full justify-start'
            ' font-semibold"{post}{disabled}{autofocus}>'
            '{header}<span aria-hidden="true">{arrow}</span></button></th>'
        ).format(
            aria_sort=_ARIA_SORT[order],
            post=self._post({"event": "sort", "column": name}),
            disabled="" if self.is_enabled else " disabled",
            autofocus=" autofocus" if is_focused else "",
            header=header,
            arrow=arrow,
        )

    def _row_html(
        self, position: int, row_id: Any, cells: list[str], *, is_focused: bool
    ) -> Markup:
        """Render a row: its position, then its cells; a click or Enter selects it."""
        is_selected = self._view.is_selected(row_id)
        if self._view.selection_mode is SelectionMode.MULTIPLE:
            selected = Markup(' aria-selected="{}"').format("true" if is_selected else "false")
        else:
            selected = Markup(' aria-current="true"') if is_selected else Markup()
        content = Markup(
            '<th scope="row" class="tabular-nums whitespace-nowrap">{position}</th>{cells}'
        ).format(
            position=f"{position + 1:,}",
            cells=Markup("").join(
                Markup('<td class="whitespace-nowrap">{}</td>').format(cell) for cell in cells
            ),
        )
        if not self.is_enabled:
            return Markup('<tr class="h-9" aria-rowindex="{}"{} data-window-row>{}</tr>').format(
                position + 2, selected, content
            )
        return Markup(
            '<tr class="h-9 cursor-pointer" tabindex="0" aria-rowindex="{index}"'
            '{selected}{autofocus} data-window-row hx-post="/_composeui/widget/{widget_id}"'
            """ hx-trigger="activate" hx-vals='{vals}'"""
            ' hx-swap="none"'
            # a double click or Enter then activates it (see `tables.js`)
            ' data-activate="{position}">{content}</tr>'
        ).format(
            position=position,
            index=position + 2,
            selected=selected,
            autofocus=" autofocus" if is_focused else "",
            widget_id=self.widget_id,
            vals=json.dumps({"event": "select", "position": str(position)}),
            content=content,
        )

    def _frame_html(self, *, oob: bool = False) -> Markup:
        """Render the scrolled frame: the headers, then the window of rows between fillers.

        Its hidden field takes the first row shown, which `tables.js` posts on a scroll.
        """
        view = self._view
        focused, self._focused_header = self._focused_header, None
        head = Markup("").join(
            self._header_html(name, header, is_focused=name == focused)
            for name, header in zip(view.column_names, view.headers)
        )
        return Markup(
            '<div id="{widget_id}-frame" class="max-h-[36rem] overflow-y-auto rounded-box'
            ' border border-base-300" tabindex="0"'
            " data-virtual-scroll{oob}>"
            '<input type="hidden" name="offset" id="{widget_id}-offset" data-scroll-offset>'
            '<input type="hidden" name="start" data-scroll-start'
            ' hx-post="/_composeui/widget/{widget_id}" hx-trigger="scroll-window"'
            ' hx-include="#{widget_id}-offset"'
            """ hx-vals='{{"event": "scroll"}}' hx-swap="none" hx-sync="this:replace">"""
            '<table class="table table-zebra table-sm" aria-rowcount="{row_count}">'
            '<thead class="sticky top-0 z-10 bg-base-100"><tr aria-rowindex="1"><td></td>'
            "{head}</tr></thead>{rows_html}</table></div>"
        ).format(
            widget_id=self.widget_id,
            oob=Markup(' hx-swap-oob="true"') if oob else Markup(),
            row_count=view.row_count + 1,
            head=head,
            rows_html=self._rows_html(),
        )

    def _rows_html(self, *, oob: bool = False) -> Markup:
        """Render the `<tbody>`: the window of rows, between the fillers standing for the rest.

        A filler is as tall as its rows, `_scale` of them to a row's height.
        """
        view = self._view
        start = min(self._start, max(view.row_count - 1, 0))
        rows = view.rows(start, start + SOURCE_TABLE_WINDOW_ROWS)
        width = len(view.headers) + 1
        if len(rows) == 0:
            empty = view.filter_texts.get("no_match", "") if view.count_text else ""
            body = Markup(
                '<tr><td colspan="{}" class="text-center opacity-70">{}</td></tr>'
            ).format(width, empty or view.texts.get("empty", ""))
        else:
            focused_row, self._focused_row = self._focused_row, None
            before, after = self._fillers(start, len(rows))
            body = Markup("{before}{rows}{after}").format(
                before=self._filler_html(before, width),
                rows=Markup("").join(
                    self._row_html(
                        start + offset, row_id, cells, is_focused=start + offset == focused_row
                    )
                    for offset, (row_id, cells) in enumerate(rows)
                ),
                after=self._filler_html(after, width),
            )
        return self._table_part(
            Markup('<tbody id="{}-rows"{}>{}</tbody>').format(
                self.widget_id, Markup(' hx-swap-oob="true"') if oob else Markup(), body
            ),
            oob=oob,
        )

    def _fillers(self, start: int, drawn: int) -> tuple[float, float]:
        """Get the heights, in rows' heights, of the fillers above and under the window.

        Together they stand for the rows not drawn, scaled: the frame keeps its height. The
        one above is where the page scrolled to (`_before`), else its rows scaled, and none
        from the first row.
        """
        hidden = (self._view.row_count - drawn) / self._scale()
        before = start / self._scale() if self._before is None else self._before
        before = 0.0 if start == 0 else min(max(before, 0.0), hidden)
        if start + drawn >= self._view.row_count:
            before = hidden  # down to the last row: no filler under it
        return before, hidden - before

    @staticmethod
    def _filler_html(height: float, width: int) -> Markup:
        """Render a row standing for rows not drawn, `height` rows' heights tall."""
        if height <= 0:
            return Markup()
        return Markup(
            '<tr aria-hidden="true" style="height: calc(2.25rem * {})"><td colspan="{}"></td></tr>'
        ).format(f"{height:.3f}", width)

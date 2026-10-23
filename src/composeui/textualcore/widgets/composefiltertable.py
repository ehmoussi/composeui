from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from textual.binding import Binding
from textual.containers import Horizontal, HorizontalScroll, Vertical
from textual.content import Content
from textual.widgets import Button, Input, Select, Static

from composeui.core.signal import Signal, SignalNoArgs
from composeui.core.view import SEARCH_DELAY_MS, as_pattern, split_pattern
from composeui.textualcore.widgets.composetable import ComposeTable

if TYPE_CHECKING:
    from textual.app import ComposeResult
    from textual.timer import Timer


#: a chip's remove button: a multiplication sign, as a close button often is
REMOVE = "\u00d7"
#: after a chip's text: a pencil, as its click edits the filter
EDIT = "\u270e"


class _ValueInput(Input):
    """The filter editor's value field: Escape closes the editor."""

    BINDINGS = [Binding("escape", "close_editor", "Close", show=False)]  # noqa: RUF012

    def __init__(self) -> None:
        super().__init__(compact=True)
        self.escaped = SignalNoArgs()

    def action_close_editor(self) -> None:
        self.escaped.emit()


class ComposeFilterChip(Horizontal):
    """A filter, as its column's header then its text, opening it, and a button removing it.

    The pencil after the text and the tooltip say a click edits it.
    """

    DEFAULT_CSS = """
    ComposeFilterChip {
        width: auto;
        height: 1;
        margin-right: 1;
    }
    """

    def __init__(self, column: int, text: str, edit_text: str, remove_text: str) -> None:
        super().__init__()
        self.column = column
        self.open_button = Button(
            Content(f"{text} {EDIT}"),
            compact=True,
            classes="chip-text",
            tooltip=Content(edit_text),
        )
        self.remove_button = Button(
            REMOVE, compact=True, classes="chip-remove", tooltip=Content(remove_text)
        )

    def compose(self) -> ComposeResult:
        yield self.open_button
        yield self.remove_button


class ComposeFilterBar(Horizontal):
    """A table's filter bar, on one line: a search, the filters as chips, the rows shown.

    The chips scroll sideways when they don't fit.

    "+ Filter" opens an editor in the bar, of a column, a value and an Add button, and in
    a text column a toggle (`pattern`, primary while on) making the value a regular
    expression: Enter or Add adds the filter, unless `check` says why its value can't
    filter, marking the value field `-invalid` with the reason as its tooltip; Escape
    closes it. A chip's
    text opens the editor on its filter, its remove button removes it. The signals emit only for the
    user: `search_edited` the text typed, `filter_added` a column and its text,
    `filter_removed` a column, and `filters_cleared`. `search_edited` waits
    `SEARCH_DELAY_MS` after the last key, but emits at once on Enter or once the search is
    cleared.
    """

    DEFAULT_CSS = """
    ComposeFilterBar {
        height: 1;
        margin-bottom: 1;
        & > Input#search {
            width: 20;
            margin-right: 1;
        }
        & > Select {
            width: 28;
        }
        & > Input#value {
            width: 20;
        }
        & > Button {
            margin-right: 1;
        }
        /* the chips take the room left, scrolling: Textual lays nothing out wrapping */
        & > HorizontalScroll#chips {
            width: 1fr;
            height: 1;
            scrollbar-size-horizontal: 0;
        }
        & > Static#count {
            width: auto;
            color: $text-muted;
        }
    }
    """

    def __init__(self) -> None:
        super().__init__()
        #: why a column's text can't filter it, or None if it can
        self.check: Callable[[int, str], str | None] = lambda _column, _text: None
        #: a hint at what filters a column, as a regular expression or not
        self.placeholder: Callable[[int, bool], str] = lambda _column, _is_pattern: ""
        #: whether a regular expression filters a column
        self.takes_pattern: Callable[[int], bool] = lambda _column: False
        self.search_edited: Signal[str] = Signal()
        self.filter_added: Signal[int, str] = Signal()
        self.filter_removed: Signal[int] = Signal()
        self.filters_cleared: SignalNoArgs = SignalNoArgs()
        self._search_timer: Timer | None = None
        self._texts: dict[str, str] = {}
        self._filters: list[tuple[int, str, str, str]] = []
        #: the column whose chip takes the focus once shown, its filter just added
        self._focused_chip: int | None = None
        self.search = Input(id="search", compact=True)
        self.add_filter = Button("", id="add-filter", compact=True)
        self.column: Select[int] = Select([], id="column", compact=True, allow_blank=True)
        self.pattern = Button(".*", id="pattern", compact=True)
        self.value = _ValueInput()
        self.value.id = "value"
        self.value.escaped.connect(self.close_editor)
        self.add = Button("", id="add", compact=True)
        self.chips = HorizontalScroll(id="chips")
        self.clear = Button("", id="clear", compact=True)
        self.count = Static("", id="count", markup=False)
        self._columns: list[tuple[int, str]] = []
        self.close_editor()

    def compose(self) -> ComposeResult:
        yield self.search
        yield self.add_filter
        yield self.column
        yield self.pattern
        yield self.value
        yield self.add
        yield self.chips
        yield self.clear
        yield self.count

    def on_mount(self) -> None:
        self._offer_columns()
        self._show_chips()

    def set_texts(self, texts: dict[str, str]) -> None:
        self._texts = texts
        self.search.placeholder = texts.get("search", "")
        self.add_filter.label = Content(texts.get("add_filter", ""))
        self.add.label = Content(texts.get("add", ""))
        self.clear.label = Content(texts.get("clear", ""))
        self.column.tooltip = Content(texts.get("column", ""))
        self.pattern.tooltip = Content(texts.get("pattern", ""))
        self.value.tooltip = None
        self._show_chips()

    def set_columns(self, columns: list[tuple[int, str]]) -> None:
        """Offer `columns`, each its index and its header, in the editor."""
        self._columns = columns
        if self.is_mounted:
            self._offer_columns()

    def _offer_columns(self) -> None:
        """Offer the columns, the one picked still picked, else the first."""
        selected = self.column.value
        self.column.set_options((Content(header), column) for column, header in self._columns)
        columns = [column for column, _ in self._columns]
        if selected in columns:
            self.column.value = selected
        elif len(columns) > 0:
            self.column.value = columns[0]

    def set_search(self, text: str) -> None:
        if self.search.value != text:
            self._stop_search_timer()  # the app's search, not the user's typed before
            with self.search.prevent(Input.Changed):
                self.search.value = text

    def set_filters(self, filters: list[tuple[int, str, str, str]]) -> None:
        """Show each filter as a chip: its column, the chip's text, the text typed, the header."""
        self._filters = filters
        self._show_chips()

    def set_count(self, text: str) -> None:
        self.count.update(text)
        self.count.display = text != ""

    def open_editor(self, column: int | None = None, text: str = "") -> None:
        if column is not None and self.is_mounted:
            self.column.value = column
        text, is_pattern = split_pattern(text)
        self.set_pattern(is_pattern=is_pattern)
        with self.value.prevent(Input.Changed):
            self.value.value = text
        self._mark_invalid(None)
        for widget in (self.column, self.value, self.add):
            widget.display = True
        self.add_filter.display = False
        if self.is_mounted:
            self._show_placeholder()
            self.value.focus()

    def close_editor(self) -> None:
        had_focus = self.value.has_focus
        for widget in (self.column, self.pattern, self.value, self.add):
            widget.display = False
        self.add_filter.display = True
        if had_focus:
            self.add_filter.focus()

    def is_pattern(self) -> bool:
        """Tell whether the value is a regular expression: the toggle is on."""
        return self.pattern.variant == "primary"

    def set_pattern(self, *, is_pattern: bool) -> None:
        self.pattern.variant = "primary" if is_pattern else "default"
        if self.is_mounted:
            self._show_placeholder()

    def is_editing(self) -> bool:
        return bool(self.value.display)

    def on_input_changed(self, event: Input.Changed) -> None:
        event.stop()
        if event.input is self.search:
            self._stop_search_timer()
            if event.value == "":
                self._emit_search()
            else:
                self._search_timer = self.set_timer(SEARCH_DELAY_MS / 1000, self._emit_search)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        if event.input is self.value:
            self._add()
        elif event.input is self.search and self._search_timer is not None:
            self._emit_search()

    def _stop_search_timer(self) -> None:
        if self._search_timer is not None:
            self._search_timer.stop()
            self._search_timer = None

    def _emit_search(self) -> None:
        self._stop_search_timer()
        self.search_edited.emit(self.search.value)

    def on_select_changed(self, event: Select.Changed) -> None:
        event.stop()
        self._show_placeholder()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        button = event.button
        if button is self.add_filter:
            self.open_editor()
        elif button is self.add:
            self._add()
        elif button is self.pattern:
            self.set_pattern(is_pattern=not self.is_pattern())
        elif button is self.clear:
            self.filters_cleared.emit()
        elif isinstance(button.parent, ComposeFilterChip):
            chip = button.parent
            if button is chip.remove_button:
                self.filter_removed.emit(chip.column)
            else:
                typed = next(
                    typed for column, _, typed, _ in self._filters if column == chip.column
                )
                self.open_editor(chip.column, typed)

    def _show_chips(self) -> None:
        self.clear.display = len(self._filters) >= 2  # noqa: PLR2004
        if not self.is_mounted:
            return
        self.chips.remove_children()
        remove, edit = self._texts.get("remove", "{header}"), self._texts.get("edit", "{header}")
        chips = [
            ComposeFilterChip(
                column, text, edit.format(header=header), remove.format(header=header)
            )
            for column, text, _typed, header in self._filters
        ]
        self.chips.mount_all(chips)
        for chip in chips:
            if chip.column == self._focused_chip:
                self.call_after_refresh(chip.open_button.focus)
        self._focused_chip = None

    def _add(self) -> None:
        column = self.column.value
        if not isinstance(column, int):
            return
        text = self.value.value
        if self.is_pattern() and self.takes_pattern(column):
            text = as_pattern(text)
        reason = self.check(column, text)
        if reason is not None:
            self._mark_invalid(reason)
            return
        self.close_editor()
        # its chip takes the focus: Enter opens it again
        self._focused_chip = column
        self.filter_added.emit(column, text)
        self._focused_chip = None

    def _mark_invalid(self, reason: str | None) -> None:
        self.value.set_class(reason is not None, "-invalid")
        self.value.tooltip = None if reason is None else Content(reason)

    def _show_placeholder(self) -> None:
        column = self.column.value
        if not isinstance(column, int):
            self.value.placeholder = ""
            return
        # a toggle only where a regular expression filters, while editing
        takes_pattern = self.takes_pattern(column)
        self.pattern.display = takes_pattern and bool(self.value.display)
        self.value.placeholder = self.placeholder(column, takes_pattern and self.is_pattern())


class ComposeFilterTable(Vertical):
    """A table of text under its filter bar, which shows only while a column filters.

    When the filters hide every row, `empty` says so under the headers.
    """

    DEFAULT_CSS = """
    ComposeFilterTable {
        height: auto;
        & > Static.empty {
            color: $text-muted;
            text-align: center;
            width: 1fr;
        }
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.bar = ComposeFilterBar()
        self.bar.display = False
        self.table = ComposeTable()
        self.empty = Static("", classes="empty", markup=False)
        self.empty.display = False

    def compose(self) -> ComposeResult:
        yield self.bar
        yield self.table
        yield self.empty

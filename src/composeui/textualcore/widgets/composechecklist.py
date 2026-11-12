"""A list of check boxes for a choice of several values: a search, a check-all box, the list."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from textual.containers import Vertical
from textual.content import Content
from textual.widgets import Checkbox, Input, SelectionList
from textual.widgets.selection_list import Selection

from composeui.core.signal import Signal
from composeui.textualcore.widgets.composecollapsible import ComposeCollapsible

if TYPE_CHECKING:
    from textual.app import ComposeResult

    from composeui.core.view import ChoicesShown


class ComposeCheckAll(Checkbox):
    """A check box that also shows partly checked, its mark a dash: a check-all box's."""

    DEFAULT_CSS = """
    ComposeCheckAll.-partly > .toggle--button {
        color: $success;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.clicked: Signal[bool] = Signal()

    def set_checked(self, is_checked: Optional[bool]) -> None:
        """Show the box checked, unchecked, or partly (None)."""
        is_partly = is_checked is None
        self.BUTTON_INNER = "-" if is_partly else "X"
        self.set_class(is_partly, "-partly")
        with self.prevent(Checkbox.Changed):
            self.value = is_checked is True
        self.refresh()

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        event.stop()
        self.clicked.emit(event.value)


class ComposeCheckList(Vertical):
    """A list of check boxes, with a search field and a check-all box above it.

    Its signals report only what the user does: `toggled` a choice's key and its new
    state, `all_clicked` the check-all box's new state, `searched` the search's text.
    """

    # a form row's field while the row is invalid (see `ROW_INVALID_CLASS`): the list's border
    DEFAULT_CSS = """
    ComposeCheckList {
        height: auto;
    }
    ComposeCheckList > SelectionList {
        height: auto;
        max-height: 12;
    }
    ComposeCheckList.-row-invalid > SelectionList {
        border: tall $error 60%;
        &:focus {
            border: tall $error;
        }
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.search_input = Input()
        self.check_all = ComposeCheckAll()
        self.choices: SelectionList[str] = SelectionList()
        self.toggled: Signal[str, bool] = Signal()
        self.searched: Signal[str] = Signal()
        self.all_clicked = self.check_all.clicked
        self._rows: list[tuple[str, str]] = []

    def compose(self) -> ComposeResult:
        yield self.search_input
        yield self.check_all
        yield self.choices

    def show(self, shown: ChoicesShown) -> None:
        """Show the choices that the search shows, and which are checked."""
        # the labels too: an int's key is its position, which new values keep
        rows = [(key, label) for key, label, _is_checked in shown.options]
        with self.prevent(SelectionList.SelectedChanged):
            if rows != self._rows:
                self._rows = rows
                self.choices.clear_options()
                self.choices.add_options(
                    [
                        Selection(Content(label), key, initial_state=is_checked)
                        for key, label, is_checked in shown.options
                    ]
                )
            else:
                for key, _label, is_checked in shown.options:
                    if is_checked:
                        self.choices.select(key)
                    else:
                        self.choices.deselect(key)
        self.check_all.set_checked(shown.all_checked)

    def set_search(self, text: str) -> None:
        if self.search_input.value != text:
            with self.prevent(Input.Changed):
                self.search_input.value = text

    def on_selection_list_selection_toggled(
        self, event: SelectionList.SelectionToggled[str]
    ) -> None:
        event.stop()
        key = event.selection.value
        self.toggled.emit(key, key in self.choices.selected)

    def on_input_changed(self, event: Input.Changed) -> None:
        event.stop()
        self.searched.emit(event.value)


class ComposeMultiComboBox(ComposeCollapsible):
    """A drop-down list of check boxes: a collapsible titled with the choice's summary."""

    # a form row's field while the row is invalid (see `ROW_INVALID_CLASS`)
    DEFAULT_CSS = """
    ComposeMultiComboBox {
        height: auto;
    }
    ComposeMultiComboBox.-row-invalid {
        border: tall $error 60%;
    }
    """

    def __init__(self) -> None:
        self.check_list = ComposeCheckList()
        super().__init__(self.check_list)

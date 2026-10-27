from __future__ import annotations

from typing import Generic, TypeVar

from textual.content import Content
from textual.widgets import Select

from composeui.core.signal import Signal

TValue = TypeVar("TValue")


def _options(values: dict[str, TValue]) -> list[tuple[Content, TValue]]:
    """Get the options of `values`, their labels plain text, not markup."""
    return [(Content(label), value) for label, value in values.items()]


class ComposeComboBox(Select[TValue], Generic[TValue]):
    """A combobox built from a `{label: value}` mapping."""

    # a form row's field while the row is invalid (see `ROW_INVALID_CLASS`): the border
    # is the current option's
    DEFAULT_CSS = """
    ComposeComboBox.-row-invalid > SelectCurrent {
        border: tall $error 60%;
    }
    ComposeComboBox.-row-invalid:focus > SelectCurrent {
        border: tall $error;
    }
    """

    def __init__(self, values: dict[str, TValue]) -> None:
        self._values: dict[str, TValue] = dict(values)
        super().__init__(_options(values))
        self.value_changed: Signal[TValue | None] = Signal()

    def set_values(self, values: dict[str, TValue]) -> None:
        """Rebuild the select for a new set of options."""
        # set in code, not chosen by the user: `value_changed` isn't emitted
        with self.prevent(Select.Changed):
            self.set_options(_options(values))

    def set_value(self, value: TValue | None) -> None:
        with self.prevent(Select.Changed):
            if value is None:
                self.value = Select.NULL
            else:
                self.value = value

    def current_value(self) -> TValue | None:
        return self.selection

    def on_select_changed(self, event: Select.Changed) -> None:
        self.value_changed.emit(self.current_value())

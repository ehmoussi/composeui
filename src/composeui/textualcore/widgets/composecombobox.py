from __future__ import annotations

from typing import Generic, TypeVar

from textual.widgets import Select

from composeui.core.signal import Signal

TValue = TypeVar("TValue")


class ComposeCombobox(Select[TValue], Generic[TValue]):
    """A combobox built from a `{label: value}` mapping."""

    def __init__(self, values: dict[str, TValue]) -> None:
        self._values: dict[str, TValue] = dict(values)
        super().__init__(values.items())
        self.value_changed: Signal[TValue | None] = Signal()

    def set_values(self, values: dict[str, TValue]) -> None:
        """Rebuild the select for a new set of options."""
        self.set_options(values.items())

    def set_value(self, value: TValue | None) -> None:
        if value is None:
            self.value = Select.NULL
        else:
            self.value = value

    def current_value(self) -> TValue | None:
        return self.selection

    def on_select_changed(self, event: Select.Changed) -> None:
        self.value_changed.emit(self.current_value())

from __future__ import annotations

from typing import Any, Generic, TypeVar

from qtpy.QtCore import QSignalBlocker, Qt, Signal, Slot
from qtpy.QtWidgets import QComboBox

TValue = TypeVar("TValue")


class QValueComboBox(QComboBox, Generic[TValue]):
    """A combobox that maps display labels to typed values."""

    # Emitted with the newly selected value whenever the current item changes
    current_value_changed = Signal(object)

    def __init__(self, values: dict[str, TValue], *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.set_values(values)
        self.currentIndexChanged.connect(self._emit_current_value_changed)

    def set_current_value(self, value: TValue | None) -> None:
        """Select the item of `value`: none for None, unless None is one of the items."""
        # not `findData`, which finds no item holding None
        index = next((i for i in range(self.count()) if self.itemData(i) == value), -1)
        self.setCurrentIndex(index)

    def set_values(self, values: dict[str, TValue]) -> None:
        """Replace all items with the given label-to-value mapping."""
        with QSignalBlocker(self):
            self.clear()
            for text, user_data in values.items():
                self.addItem(text, userData=user_data)

    @Slot(int)
    def _emit_current_value_changed(self, index: int) -> None:
        """Emit current_value_changed when currentIndexChanged is triggered."""
        user_data = self.itemData(index, role=Qt.ItemDataRole.UserRole)
        self.current_value_changed.emit(user_data)

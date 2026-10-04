from typing import Any

from qtpy.QtCore import Signal, Slot
from qtpy.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QRadioButton,
    QWidget,
)


class QRadioGroup(QWidget):
    """Custom signal for the Radio group."""

    value_changed = Signal(object)

    def __init__(self, values: dict[str, Any], *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._layout = QHBoxLayout()
        self._layout.setContentsMargins(0, 0, 0, 0)
        # the buttons packed at the start, as on the web, not spread over the row
        self._layout.addStretch()
        self.setLayout(self._layout)
        self._button_group = QButtonGroup(self)
        self._button_group.setExclusive(True)
        self._button_group.idClicked.connect(self._emit_value_changed_signal)
        self._values: dict[str, Any] = {}
        self.set_values(values)

    def set_values(self, values: dict[str, Any]) -> None:
        """Rebuild the radio buttons for a new set of options."""
        for button in self._button_group.buttons():
            self._button_group.removeButton(button)
            self._layout.removeWidget(button)
            # detached at once: `deleteLater` alone leaves it a visible child, drawn
            # next to the new buttons until the event loop gets to deleting it
            button.setParent(None)
            button.deleteLater()
        self._values = values
        for i, value_text in enumerate(self._values):
            button = QRadioButton(value_text)
            self._layout.insertWidget(self._layout.count() - 1, button)  # before the stretch
            self._button_group.addButton(button, i)

    def set_value(self, value: Any) -> None:
        for button_id, value_raw in enumerate(self._values.values()):
            if value == value_raw:
                button = self._button_group.button(button_id)
                if not button.isChecked():
                    button.setChecked(True)

    def value(self) -> Any:
        checked_button = self._button_group.checkedButton()
        if checked_button is None:
            return None
        value_text = checked_button.text()
        return self._values[value_text]

    @Slot()
    def _emit_value_changed_signal(self, button_id: int) -> None:
        """Emit the value changed signal."""
        value_text = self._button_group.button(button_id).text()
        value = self._values[value_text]
        self.value_changed.emit(value)

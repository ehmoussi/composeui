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
        # self.setContentsMargins(0, 0, 0, 0)
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        self._values = values
        self._button_group = QButtonGroup(self)
        self._button_group.setExclusive(True)
        self._button_group.idClicked.connect(self._emit_value_changed_signal)
        for i, value_text in enumerate(self._values):
            button = QRadioButton(value_text)
            layout.addWidget(button)
            self._button_group.addButton(button, i)
        self.setLayout(layout)

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

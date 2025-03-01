from qtpy.QtCore import Signal  # type: ignore[attr-defined]
from qtpy.QtGui import QShowEvent
from qtpy.QtWidgets import QComboBox, QGroupBox, QWidget


class Widget(QWidget):

    view_visible = Signal()

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        """Emit a signal when the widget is visible."""
        self.view_visible.emit()
        super().showEvent(event)


class GroupBox(QGroupBox):

    view_visible = Signal()

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        """Emit a signal when the widget is visible."""
        self.view_visible.emit()
        super().showEvent(event)


class ComboBox(QComboBox):

    view_visible = Signal()

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        """Emit a signal when the widget is visible."""
        self.view_visible.emit()
        super().showEvent(event)

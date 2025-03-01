r"""MainWindow with additional signals."""

from qtpy.QtCore import Signal  # type: ignore[attr-defined]
from qtpy.QtCore import Qt
from qtpy.QtGui import QCloseEvent
from qtpy.QtWidgets import QMainWindow, QMessageBox, QWidget

from typing import Optional


class MainWindow(QMainWindow):
    r"""Main window with signals for copy/paste."""

    save_before_exit = Signal()

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        flags: Qt.WindowFlags = Qt.WindowFlags(),  # noqa: B008
    ) -> None:
        super().__init__(parent, flags)
        self.message_before_closing = ""
        self._force_close = False

    @property
    def force_close(self) -> bool:
        r"""Check if the exit of the application can be forced."""
        return self._force_close

    @force_close.setter
    def force_close(self, force_close: bool) -> None:
        r"""Set if the exit of the application is forced."""
        self._force_close = force_close
        if force_close:
            self.close()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        r"""Ask a confirmation after receiving a window close request."""
        if self.force_close:
            event.accept()
        else:
            answer = self.ask_confirmation()
            if answer == QMessageBox.Discard:
                event.accept()
            elif answer == QMessageBox.Cancel:
                event.ignore()
            else:
                self.save_before_exit.emit()
                event.ignore()

    def ask_confirmation(self) -> QMessageBox.StandardButton:
        r"""Ask the confirmation before closing the mainwindow."""
        return QMessageBox.question(
            self,
            self.windowTitle(),
            self.message_before_closing,
            QMessageBox.Discard | QMessageBox.Save | QMessageBox.Cancel,
            QMessageBox.NoButton,
        )

r"""Progress dialog without closing if cancel button is clicked."""

from qtpy.QtGui import QCloseEvent
from qtpy.QtWidgets import QProgressBar, QProgressDialog

from typing import Any


class ProgressDialog(QProgressDialog):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._progress_bar = QProgressBar()
        self.setBar(self._progress_bar)
        super().cancel()

    @property
    def is_percentage_visible(self) -> bool:
        return bool(self._progress_bar.isTextVisible())

    @is_percentage_visible.setter
    def is_percentage_visible(self, is_visible: bool) -> None:
        self._progress_bar.setTextVisible(is_visible)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self.wasCanceled():
            self.reset()
        super().closeEvent(event)

    def setVisible(self, is_visible: bool) -> None:  # noqa: N802
        r"""Set the visibility except if hide and the dialog is cancelled."""
        if is_visible or not self.wasCanceled():
            super().setVisible(is_visible)

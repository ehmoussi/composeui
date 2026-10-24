from __future__ import annotations

from typing import TYPE_CHECKING

from qtpy.QtCore import Qt
from qtpy.QtCore import Signal as QtSignal
from qtpy.QtGui import QPainter, QPalette
from qtpy.QtWidgets import QSplitter, QSplitterHandle

if TYPE_CHECKING:
    from qtpy.QtGui import QKeyEvent, QMouseEvent, QPaintEvent

#: pixels an arrow key moves a focused handle by, as on the web
KEY_STEP = 16


class QSplitterBorder(QSplitterHandle):
    """A splitter's handle the keyboard reaches too: the arrow keys move it once focused.

    Qt's own handles take no focus, so only the mouse moves them.
    """

    def __init__(self, orientation: Qt.Orientation, parent: QComposeSplitter) -> None:
        super().__init__(orientation, parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if self.orientation() == Qt.Orientation.Vertical:
            steps = {Qt.Key.Key_Up: -KEY_STEP, Qt.Key.Key_Down: KEY_STEP}
            position = self.y()
        else:
            steps = {Qt.Key.Key_Left: -KEY_STEP, Qt.Key.Key_Right: KEY_STEP}
            position = self.x()
        step = steps.get(Qt.Key(event.key()))
        if step is None:
            super().keyPressEvent(event)
            return
        self.moveSplitter(position + step)
        self._splitter().moved_by_user.emit()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        super().mouseReleaseEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self._splitter().moved_by_user.emit()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        super().paintEvent(event)
        if self.hasFocus():  # Qt's style draws no focus on a handle
            painter = QPainter(self)
            painter.fillRect(self.rect(), self.palette().color(QPalette.ColorRole.Highlight))

    def _splitter(self) -> QComposeSplitter:
        splitter = self.splitter()
        assert isinstance(splitter, QComposeSplitter)
        return splitter


class QComposeSplitter(QSplitter):
    """A splitter whose handles the keyboard moves too, telling once the user moved one.

    `moved_by_user` reports the end of a drag, or a key's move, rather than each step
    of a drag as `splitterMoved` does; never a change of `setSizes`.
    """

    #: the user dropped a handle they dragged, or moved one with a key
    moved_by_user = QtSignal()

    def createHandle(self) -> QSplitterHandle:  # noqa: N802
        return QSplitterBorder(self.orientation(), self)

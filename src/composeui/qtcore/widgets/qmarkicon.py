from __future__ import annotations

import functools
from typing import Final

from qtpy.QtCore import QPoint, Qt
from qtpy.QtGui import QColor, QIcon, QPainter, QPen, QPixmap

from composeui.core.view import NodeMark

#: a `NodeMark`'s color, as a log's warning and error are colored
_MARK_COLORS: Final = {NodeMark.DONE: "green", NodeMark.WARNING: "orange", NodeMark.ERROR: "red"}


@functools.cache
def mark_icon(mark: NodeMark) -> QIcon:
    """Draw `mark` in a circle, as the web's icons are: a check, a "!" or a cross."""
    size = 32  # scaled down sharp, on a high-density screen too
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(_MARK_COLORS[mark]), 3)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.drawEllipse(3, 3, 26, 26)
    if mark is NodeMark.DONE:
        painter.drawPolyline([QPoint(10, 16), QPoint(14, 20), QPoint(22, 12)])
    elif mark is NodeMark.WARNING:
        painter.drawLine(16, 10, 16, 17)
        painter.drawPoint(16, 22)
    else:
        painter.drawLine(11, 11, 21, 21)
        painter.drawLine(21, 11, 11, 21)
    painter.end()
    return QIcon(pixmap)

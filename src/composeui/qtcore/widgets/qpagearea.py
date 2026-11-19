from __future__ import annotations

from typing import TYPE_CHECKING

from qtpy.QtWidgets import QScrollArea, QWidget

if TYPE_CHECKING:
    from qtpy.QtCore import QSize


class QPageArea(QScrollArea):
    """A page's column, which scrolls when its views need more room than the area has.

    The column is as big as the area, or bigger when its views need more. So a view that
    scrolls within itself takes the spare height. The area asks for the column's size, so
    a window opens at the same size as without the area.
    """

    def __init__(self, column: QWidget) -> None:
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.setWidget(column)
        self._column = column

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt's name)
        # a scroll area's own is the size of a few lines of text
        return self._column.sizeHint()

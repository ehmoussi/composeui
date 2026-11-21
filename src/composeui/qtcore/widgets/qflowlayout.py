"""A layout of widgets in a row, wrapping onto the next line when the row is full."""

from __future__ import annotations

from typing import TYPE_CHECKING

from qtpy.QtCore import QMargins, QPoint, QRect, QSize, Qt
from qtpy.QtWidgets import QLayout, QSizePolicy, QWidgetItem
from typing_extensions import override

if TYPE_CHECKING:
    from qtpy.QtWidgets import QLayoutItem, QWidget


class QFlowLayout(QLayout):
    """A layout of widgets in a row, wrapping onto the next line when the row is full.

    Qt has none built in: the Qt documentation's Flow Layout example. Each widget is as
    wide as its size hint, at most the layout's width, `spacing` apart (by default, the
    style's, as a row's). With `align_end`, each line ends at the layout's right edge.
    With `one_line_hint`, the layout asks for the width of all its widgets on one line, as
    a row does; else only for its widest widget's.
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        spacing: int | None = None,
        *,
        align_end: bool = False,
        one_line_hint: bool = False,
    ) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        if spacing is not None:
            self.setSpacing(spacing)
        self._align_end = align_end
        self._one_line_hint = one_line_hint
        self.setContentsMargins(QMargins(0, 0, 0, 0))

    @override
    def addItem(self, item: QLayoutItem) -> None:
        self._items.append(item)

    @override
    def count(self) -> int:
        return len(self._items)

    def insert_widget(self, index: int, widget: QWidget) -> None:
        self.addChildWidget(widget)
        # now: Qt would show it on its next pass, after laying it out as if hidden
        widget.show()
        self._items.insert(index, QWidgetItem(widget))
        self.invalidate()

    @override
    def itemAt(self, index: int) -> QLayoutItem | None:
        return self._items[index] if 0 <= index < len(self._items) else None

    @override
    def takeAt(self, index: int) -> QLayoutItem | None:
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    @override
    def expandingDirections(self) -> Qt.Orientation:
        return Qt.Orientation(0)

    @override
    def hasHeightForWidth(self) -> bool:
        return True

    @override
    def heightForWidth(self, width: int) -> int:
        return self._lay_out(QRect(0, 0, width, 0), move=False)

    @override
    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._lay_out(rect, move=True)

    @override
    def sizeHint(self) -> QSize:
        if not self._one_line_hint:
            return self.minimumSize()
        shown = [item.sizeHint() for item in self._items if not item.isEmpty()]
        width = sum(hint.width() for hint in shown) + self._gap() * max(len(shown) - 1, 0)
        height = max((hint.height() for hint in shown), default=0)
        return QSize(width, height) + self._margins_size()

    @override
    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size + self._margins_size()

    def _gap(self) -> int:
        """Get the space between two widgets, the style's unless one was set."""
        spacing = self.spacing()
        parent = self.parentWidget()
        if spacing < 0 and parent is not None:  # pragma: no cover - macOS's style only
            # it spaces each pair of controls instead, as Qt's Flow Layout example reads it
            spacing = parent.style().layoutSpacing(
                QSizePolicy.ControlType.PushButton,
                QSizePolicy.ControlType.PushButton,
                Qt.Orientation.Horizontal,
            )
        return max(spacing, 0)

    def _margins_size(self) -> QSize:
        margins = self.contentsMargins()
        return QSize(margins.left() + margins.right(), margins.top() + margins.bottom())

    def _lay_out(self, rect: QRect, *, move: bool) -> int:
        """Place the items in `rect`'s width (if `move`); return the height they take."""
        spacing = self._gap()
        lines: list[list[tuple[QLayoutItem, QSize]]] = []
        width = 0
        for item in self._items:
            if item.isEmpty():  # a hidden widget takes no room
                continue
            hint = _size_within(item, rect.width())
            if not lines or (lines[-1] and width + hint.width() > rect.width()):
                lines.append([])
                width = 0
            lines[-1].append((item, hint))
            width += hint.width() + spacing
        y = rect.y()
        for line in lines:
            if move:
                x = rect.x()
                if self._align_end:
                    used = sum(hint.width() for _, hint in line) + spacing * (len(line) - 1)
                    x = rect.right() + 1 - used
                for item, hint in line:
                    item.setGeometry(QRect(QPoint(x, y), hint))
                    x += hint.width() + spacing
            y += max(hint.height() for _, hint in line) + spacing
        return max(y - spacing - rect.y(), 0)


def _size_within(item: QLayoutItem, width: int) -> QSize:
    """Get `item`'s size hint, at most `width` wide (down to its minimum), e.g. to wrap a label."""
    hint = item.sizeHint()
    if hint.width() <= width:
        return hint
    narrower = max(width, item.minimumSize().width())
    height = item.heightForWidth(narrower) if item.hasHeightForWidth() else hint.height()
    return QSize(narrower, height)

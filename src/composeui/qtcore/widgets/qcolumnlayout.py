"""A column of views whose height to spare goes below them, unless one of them grows."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from qtpy.QtCore import Qt
from qtpy.QtWidgets import QSizePolicy, QSpacerItem, QVBoxLayout
from typing_extensions import override

if TYPE_CHECKING:
    from qtpy.QtWidgets import QLayoutItem

_NONE = Qt.Orientation(0)


class QColumnLayout(QVBoxLayout):
    """Views one above the other, then the column's spare space (`add_spare_space`).

    A shown view that grows taller, such as one scrolling within itself, takes the
    column's height to spare. Else the spare space below the views does. The column grows
    in the column holding it only with such a view: grown by its spare space alone, it
    would leave a gap under its views. Qt asks again each time it lays the column out, so
    a view shown or hidden later counts.
    """

    def add_spare_space(self) -> None:
        """Add the spare space, below the views."""
        self.addItem(_SpareSpace(self))

    @override
    def expandingDirections(self) -> Qt.Orientation:
        if _grows_without_spare_space(self):
            return Qt.Orientation.Vertical
        return _NONE


class _SpareSpace(QSpacerItem):
    """The space below a column's views: it grows only when none of them does."""

    def __init__(self, column: QColumnLayout) -> None:
        super().__init__(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        self._column = column

    @override
    def expandingDirections(self) -> Qt.Orientation:
        if _grows_without_spare_space(self._column):
            return _NONE
        return Qt.Orientation.Vertical


def _grows_without_spare_space(column: QColumnLayout) -> bool:
    """Whether a shown view of `column` grows taller (a hidden one doesn't, for Qt)."""
    for index in range(column.count()):
        # an index under the count: never None
        item = cast("QLayoutItem", column.itemAt(index))
        if (
            not isinstance(item, _SpareSpace)
            and item.expandingDirections() & Qt.Orientation.Vertical
        ):
            return True
    return False

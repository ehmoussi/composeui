"""Utilitary functions for the objects of Salome"""

from qtpy.QtCore import Signal  # type: ignore[attr-defined]
from qtpy.QtCore import QAbstractProxyModel, QModelIndex, QObject
from qtpy.QtWidgets import QTreeView
from salome.gui import helper

import enum
from typing import Any, List


class SalomeTreeType(enum.Enum):
    NONE = enum.auto()
    GEOM = enum.auto()


class SalomeTreeSignals(QObject):
    """New signals for the salome tree."""

    geometry_entries_removed = Signal()

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.view: QTreeView = helper.sgPyQt.getObjectBrowser()
        model = self.view.model()
        if isinstance(model, QAbstractProxyModel):
            self.model = model.sourceModel()
        else:
            self.model = model
        self.model.rowsAboutToBeRemoved.connect(self._find_entries_about_to_be_removed)
        self.last_entries_removed: List[str] = []
        self._last_entries_removed_type = SalomeTreeType.NONE
        self.model.rowsRemoved.connect(self._emit_signals)

    def _emit_signals(self) -> None:
        """Emit the appropriate signals."""
        if self._last_entries_removed_type == SalomeTreeType.GEOM:
            self.geometry_entries_removed.emit()

    def _find_entries_about_to_be_removed(
        self, parent: QModelIndex, first: int, last: int
    ) -> None:
        """Find the entries about to be removed in the salome tree."""
        self.last_entries_removed.clear()
        if self._is_from_geometry(parent):
            self._last_entries_removed_type = SalomeTreeType.GEOM
        else:
            self._last_entries_removed_type = SalomeTreeType.NONE
        if self._last_entries_removed_type != SalomeTreeType.NONE:
            for j in range(first, last + 1):
                # the third column correspond to the column of the entries
                index = self.model.index(j, 2, parent)
                entry = index.data()
                if entry is not None:
                    self.last_entries_removed.append(str(entry))

    def _find_root_parent(self, index: QModelIndex, column: int) -> QModelIndex:
        """Find the root parent of the given index."""
        parent = index.parent()
        if parent.isValid():
            return self._find_root_parent(parent, column)
        else:
            return self.model.index(index.row(), column)

    def _is_from_geometry(self, index: QModelIndex) -> bool:
        """Check if the given index is in the GEOM module"""
        root_parent = self._find_root_parent(index, 0)
        return (
            str(root_parent.data()) == "Geometry"
            or str(self.model.index(root_parent.row(), 3).data()) == "GEOM"
        )

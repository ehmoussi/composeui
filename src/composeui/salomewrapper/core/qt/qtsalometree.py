"""Utilitary functions for the objects of Salome"""

from composeui.core.qt.qtview import QtView
from composeui.salomewrapper.core.qt.widgets.salometreesignals import SalomeTreeSignals
from composeui.salomewrapper.core.views.salometree import SalomeTree

import salome
from qtpy.QtCore import (
    QAbstractProxyModel,
    QItemSelection,
    QItemSelectionModel,
    QModelIndex,
    Qt,
)
from qtpy.QtWidgets import QTreeView, QWidget
from salome.gui import helper

from dataclasses import dataclass, field
from typing import List


@dataclass(eq=False)
class QtSalomeTree(QtView, SalomeTree):
    """A view for the Salome tree widget."""

    view: QTreeView = field(
        init=False, default_factory=lambda: helper.sgPyQt.getObjectBrowser()
    )

    _parent_view: QWidget = field(init=False)
    _signals: SalomeTreeSignals = field(init=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        parent_view = self.view.parent()
        if isinstance(parent_view, QWidget):
            self._parent_view = parent_view
        else:
            raise TypeError("Parent view must be a QWidget")
        self._signals = SalomeTreeSignals(self.view)
        # Assign signals
        self.selection_changed.add_qt_signals(
            (self.view.selectionModel(), self.view.selectionModel().selectionChanged)
        )
        self.data_changed.add_qt_signals((self.view.model(), self.view.model().dataChanged))
        self.geometry_entries_removed.add_qt_signals(
            (self._signals, self._signals.geometry_entries_removed)
        )
        # Assign internal signals
        self.view.clicked.connect(self._display_selected_entry)

    def _display_selected_entry(self, index: QModelIndex) -> None:
        python_module = helper.sgPyQt.getActivePythonModule()
        if python_module is None or not hasattr(python_module, "APP"):
            # check if the current module is a compatible module
            return
        if index.isValid():
            model = self._model()
            source_index = model.mapToSource(index)
            if source_index.column() == 1:
                source_model = model.sourceModel()
                entry_index = source_model.index(source_index.row(), 2, source_index.parent())
                entry = entry_index.data()
                if salome.sg.hasDesktop() and entry != "":
                    is_visible = salome.sg.IsInCurrentView(entry)
                    if is_visible:
                        salome.sg.Erase(entry)
                    else:
                        salome.sg.Display(entry)
                    salome.sg.UpdateView()

    def _model(self) -> QAbstractProxyModel:
        model = self.view.model()
        assert isinstance(
            model, QAbstractProxyModel
        ), "Unexpected error: the model of the salome tree is not a proxy model"
        return model

    def update(self) -> None:
        if salome.sg.hasDesktop():
            salome.sg.updateObjBrowser()

    @property  # type: ignore[misc]
    def is_visible(self) -> bool:
        return self._parent_view.isVisible()

    @is_visible.setter
    def is_visible(self, is_visible: bool) -> None:
        self._parent_view.setVisible(is_visible)

    @property  # type: ignore[misc]
    def current_selections(self) -> List[str]:
        if salome.sg.hasDesktop():
            return list(salome.sg.getAllSelected())
        else:
            return []

    @current_selections.setter
    def current_selections(self, entries: List[str]) -> None:
        if hasattr(self, "view"):
            self._select_by_entries(entries)

    def get_last_entries_removed(self) -> List[str]:
        return self._signals.last_entries_removed

    def _select_by_entries(self, entries: List[str]) -> None:
        r"""Select an item in the object browser corresponding to the given entry."""
        selection_model = self.view.selectionModel()
        item_selection = QItemSelection()
        for entry in entries:
            entry_selection = self._create_selection_from_entry(entry)
            item_selection.merge(entry_selection, QItemSelectionModel.Select)
        selection_model.select(item_selection, QItemSelectionModel.ClearAndSelect)

    def _create_selection_from_entry(self, entry: str) -> QItemSelection:
        """Create an item selection from the given entry."""
        index_source = self._find_index_from_entry(entry)
        index = self._model().mapFromSource(index_source)
        item_selection = QItemSelection()
        item_selection.select(index.siblingAtColumn(0), index.siblingAtColumn(5))
        return item_selection

    def _find_index_from_entry(self, entry: str) -> QModelIndex:
        model = self._model().sourceModel()
        if len(entry.split(":")) == 3:
            return model.match(model.index(0, 2), 0, entry, 1, Qt.MatchExactly)[0]
        else:
            parent_entry = ":".join(entry.split(":")[:-1])
            parent = self._find_index_from_entry(parent_entry)
            indices = model.match(model.index(0, 2, parent), 0, entry, 1, Qt.MatchExactly)
            if len(indices) > 0:
                return indices[0]
            else:
                msg = f"{entry} is an unknown entry."
                raise ValueError(msg)

    def hide_row_by_entry(self, entry: str) -> None:
        """Hide a row corresponding to the given entry in the salome tree."""
        index = self._find_index_from_entry(entry)
        self.view.setRowHidden(index.row(), index.parent(), True)

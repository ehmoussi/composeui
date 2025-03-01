"""Item Model for a QComboBox."""

from composeui.form.abstractcomboboxitems import AbstractComboboxItems

from qtpy.QtCore import QAbstractListModel, QModelIndex, Qt

from typing import Any


class ComboBoxItemModel(QAbstractListModel):
    def __init__(self, items: AbstractComboboxItems, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.items = items

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802, B008
        """Get the number of rows."""
        return self.items.row_count()

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        r"""Get the data stored under the given role for the given index."""
        if role == Qt.DisplayRole:
            return self.items.data(index.row(), index.column())
        return None

    def headerData(  # noqa: N802
        self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole
    ) -> Any:
        r"""Return the header data for the given role, section and orientation."""
        # No header for a combobox
        return None

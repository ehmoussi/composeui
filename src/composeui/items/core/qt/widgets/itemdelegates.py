r"""ComboBox Delegate for a QTableView."""

from composeui.commontypes import AnyModel
from composeui.items.core.itemsutils import ComboBoxDelegateProps, FloatDelegateProps
from composeui.items.table.abstracttableitems import AbstractTableItems
from composeui.items.table.qt.widgets.tableitemmodel import TableItemModel
from composeui.items.tree.abstracttreeitems import AbstractTreeItems
from composeui.items.tree.qt.widgets.treeitemmodel import TreeItemModel

from qtpy.QtCore import QModelIndex
from qtpy.QtGui import QDoubleValidator
from qtpy.QtWidgets import QComboBox, QItemDelegate, QLineEdit, QStyleOptionViewItem, QWidget

import typing
from typing import Any, Tuple, Union

if typing.TYPE_CHECKING:
    from composeui.items.table.qt.widgets.tablewidget import _TableView
    from composeui.items.tree.qt.widgets.treewidget import _TreeView


class ComboBoxDelegate(QItemDelegate):
    r"""Display and editing a ComboBox for data items from a model."""

    def __init__(
        self,
        items: Union[AbstractTableItems[AnyModel], AbstractTreeItems[AnyModel]],
        table: Union["_TableView", "_TreeView"],
    ) -> None:
        super().__init__(table)
        self.table = table
        self.items = items

    def createEditor(  # noqa: N802
        self, parent: QWidget, option: QStyleOptionViewItem, index: QModelIndex
    ) -> QWidget:
        r"""Get the widget used to edit the item specified by index for editing."""
        editor = QComboBox(parent)
        editor.setEditable(True)
        model = self.table.model()
        if isinstance(model, (TreeItemModel, TableItemModel)):
            source_index = model.mapToSource(index)
            delegate_props = None
            if isinstance(self.items, AbstractTableItems):
                delegate_props = self.items.get_delegate_props(index.column(), row=index.row())
            else:
                delegate_props = self.items.get_delegate_props(
                    index.column(), row=index.row(), parent_rows=source_index.internalPointer()
                )
            if delegate_props is not None and isinstance(
                delegate_props, ComboBoxDelegateProps
            ):
                editor.addItems(delegate_props.values)
        return editor

    def updateEditorGeometry(  # noqa: N802
        self, editor: QWidget, option: QStyleOptionViewItem, index: QModelIndex
    ) -> None:
        r"""Update the editor for the index according to the style option given."""
        editor.setGeometry(option.rect)


class FloatDelegate(QItemDelegate):
    r"""Delegate for the float values."""

    def __init__(
        self,
        items: Union[AbstractTableItems[AnyModel], AbstractTreeItems[AnyModel]],
        table: Union["_TableView", "_TreeView"],
    ) -> None:
        super().__init__(table)
        self.items = items

    def createEditor(  # noqa: N802
        self, parent: QWidget, option: QStyleOptionViewItem, index: QModelIndex
    ) -> QWidget:
        r"""Get the widget used to edit the item specified by index for editing."""
        delegate_props = None
        if isinstance(self.items, AbstractTableItems):
            delegate_props = self.items.get_delegate_props(index.column(), row=index.row())
        else:
            delegate_props = self.items.get_delegate_props(
                index.column(), row=index.row(), parent_rows=index.internalPointer()
            )
        if delegate_props is not None and isinstance(delegate_props, FloatDelegateProps):
            editor = QLineEdit(parent)
            validator = DoubleValidator()
            bottom, top, decimals = (
                delegate_props.minimum,
                delegate_props.maximum,
                delegate_props.decimals,
            )
            if top is not None:
                validator.setTop(float(top))
            if bottom is not None:
                validator.setBottom(float(bottom))
            if decimals is not None:
                validator.setDecimals(int(decimals))
            editor.setValidator(validator)
            return editor
        return super().createEditor(parent, option, index)

    def updateEditorGeometry(  # noqa: N802
        self, editor: QWidget, option: QStyleOptionViewItem, index: QModelIndex
    ) -> None:
        r"""Update the editor for the index according to the style option given."""
        editor.setGeometry(option.rect)


class DoubleValidator(QDoubleValidator):
    r"""Double Validator with a default value for the empty string."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

    def validate(self, value: str, position: int) -> Tuple[QDoubleValidator.State, str, int]:
        r"""Validate the given value at the given position."""
        if str(value) == "":
            return self.Acceptable, value, position
        else:
            return super().validate(value, position)

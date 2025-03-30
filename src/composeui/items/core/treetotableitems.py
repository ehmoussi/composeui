"""
Transform a subset of a tree items into a table items to manipulate it
indistinguishably from a table.
"""

from composeui.commontypes import AnyItemsView, AnyModel
from composeui.items.core.abstractitems import AbstractItems
from composeui.items.core.itemsconverter import ItemsConverter
from composeui.items.core.itemsutils import BackgroundType, DelegateProps
from composeui.items.core.tabletotreeitems import TableToTreeItems
from composeui.items.table.abstracttableitems import AbstractTableItems
from composeui.items.tree.abstracttreeitems import AbstractTreeItems

from typing_extensions import OrderedDict

from typing import Any, Generator, List, Optional, Tuple


class TreeToTableItems(AbstractTableItems[AnyModel]):
    def __init__(
        self, tree_items: AbstractTreeItems[AnyModel], parent_rows: Tuple[int, ...]
    ) -> None:
        super().__init__(tree_items._view, tree_items._model)  # noqa: SLF001
        self._tree_items = tree_items
        self.parent_rows = parent_rows

    def get_dependencies(self) -> Tuple["AbstractItems[AnyItemsView, AnyModel]", ...]:
        return self._tree_items.get_dependencies()

    def set_dependencies(
        self, dependencies: List["AbstractItems[AnyItemsView, AnyModel]"]
    ) -> None:
        self._tree_items.set_dependencies(dependencies)

    def add_dependency(self, dependency: "AbstractItems[AnyItemsView, AnyModel]") -> None:
        self._tree_items.add_dependency(dependency)

    def is_view_selection_suspended(self) -> bool:
        return self._tree_items.is_view_selection_suspended()

    def set_view_selection_suspend_status(self, is_suspended: bool) -> None:
        self._tree_items.set_view_selection_suspend_status(is_suspended)

    def get_nb_rows(self) -> int:
        return self._tree_items.get_nb_rows(self.parent_rows)

    def get_data(self, row: int, column: int) -> str:
        return self._tree_items.get_data(row, column, self.parent_rows)

    def get_data_by_id(self, rid: Any, column: int) -> str:
        row = self.get_row_from_id(rid)
        return self._tree_items.get_data(row, column, self.parent_rows)

    def get_title(self) -> str:
        return self._tree_items.get_title(self.parent_rows)

    def get_nb_columns(self) -> int:
        return self._tree_items.get_nb_columns()

    def get_column_title(self, column: int) -> str:
        return self._tree_items.get_column_title(column)

    def get_exported_column_indices(self) -> List[int]:
        return self._tree_items.get_exported_column_indices(self.parent_rows)

    def get_exported_column_names(self) -> List[str]:
        return self._tree_items.get_exported_column_names(self.parent_rows)

    def insert(self, row: int) -> Optional[int]:
        new_selected_rows = self._tree_items.insert(row, self.parent_rows)
        if new_selected_rows is not None:
            *new_selected_parent_rows, new_selected_row = new_selected_rows
            if tuple(new_selected_parent_rows) == self.parent_rows:
                return new_selected_row
        return None

    def remove(self, row: int) -> Optional[int]:
        new_selected_rows = self._tree_items.remove(row, self.parent_rows)
        if new_selected_rows is not None:
            *new_selected_parent_rows, new_selected_row = new_selected_rows
            if tuple(new_selected_parent_rows) == self.parent_rows:
                return new_selected_row
        return None

    def remove_all(self) -> None:
        self._tree_items.remove_all()

    def move(self, from_row: int, to_row: int) -> bool:
        return self._tree_items.move(from_row, to_row, self.parent_rows, self.parent_rows)

    def set_data(self, row: int, column: int, value: str) -> bool:
        return self._tree_items.set_data(row, column, value, self.parent_rows)

    def get_edit_data(self, row: int, column: int) -> Any:
        return self._tree_items.get_edit_data(row, column, self.parent_rows)

    def is_checked(self, row: int, column: int) -> Optional[bool]:
        return self._tree_items.is_checked(row, column, self.parent_rows)

    def set_checked(self, row: int, column: int, value: bool) -> bool:
        return self._tree_items.set_checked(row, column, value, self.parent_rows)

    def is_editable(self, row: int, column: int) -> bool:
        return self._tree_items.is_editable(row, column, self.parent_rows)

    def is_enabled(self, row: int, column: int) -> bool:
        return self._tree_items.is_enabled(row, column, self.parent_rows)

    def get_delegate_props(self, row: int, column: int) -> Optional[DelegateProps]:
        return self._tree_items.get_delegate_props(row, column, self.parent_rows)

    def get_background(self, row: int, column: int) -> BackgroundType:
        return self._tree_items.get_background(row, column, self.parent_rows)

    def get_selected_rows(self) -> List[int]:
        return [
            row
            for *parent_rows, row in self.get_selected_positions()
            if tuple(parent_rows) == self.parent_rows
        ]

    def set_selected_rows(self, rows: List[int]) -> None:
        self._tree_items.set_selected_positions([(*self.parent_rows, row) for row in rows])

    def get_selected_row_items(self) -> OrderedDict[int, List[int]]:
        return OrderedDict(
            (row, columns)
            for (*parent_rows, row), columns in self._tree_items.get_selected_items().items()
            if tuple(parent_rows) == self.parent_rows
        )

    def set_selected_row_items(self, selected_row_items: OrderedDict[int, List[int]]) -> None:
        self._tree_items.set_selected_items(
            OrderedDict(
                ((*self.parent_rows, row), columns)
                for row, columns in selected_row_items.items()
            )
        )

    def is_filtered(self, row: int) -> bool:
        return self._tree_items.is_filtered(row, self.parent_rows)

    def get_infos(self) -> OrderedDict[str, Any]:
        return self._tree_items.get_infos(self.parent_rows)

    def iter_trigger_dependencies(self) -> Generator[None, None, None]:
        for _ in self._tree_items.iter_trigger_dependencies():
            yield

    def converter(self) -> ItemsConverter[TableToTreeItems[AnyModel]]:
        return ItemsConverter(TableToTreeItems(self))

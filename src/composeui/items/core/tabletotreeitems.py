"""
Transform a table items into a tree items to manipulate it indistinguishably from a tree.
"""

from composeui.commontypes import AnyItemsView, AnyModel
from composeui.items.core.abstractitems import AbstractItems
from composeui.items.core.itemsconverter import ItemsConverter
from composeui.items.core.itemsutils import BackgroundType, DelegateProps
from composeui.items.tree.abstracttreeitems import AbstractTreeItems

from typing_extensions import OrderedDict, Self

import typing
from typing import Any, Generator, List, Optional, Tuple

if typing.TYPE_CHECKING:
    from composeui.items.table.abstracttableitems import AbstractTableItems


class TableToTreeItems(AbstractTreeItems[AnyModel]):
    # TODO: replace by a generic with the abstracttableitems
    def __init__(self, items: "AbstractTableItems[AnyModel]") -> None:
        self._table_items = items
        super().__init__(items._view, items._model, depth=0)  # noqa: SLF001

    def get_dependencies(self) -> Tuple["AbstractItems[AnyItemsView, AnyModel]", ...]:
        return self._table_items.get_dependencies()

    def set_dependencies(
        self, dependencies: List["AbstractItems[AnyItemsView, AnyModel]"]
    ) -> None:
        self._table_items.set_dependencies(dependencies)

    def add_dependency(self, dependency: "AbstractItems[AnyItemsView, AnyModel]") -> None:
        self._table_items.add_dependency(dependency)

    def is_view_selection_suspended(self) -> bool:
        return self._table_items.is_view_selection_suspended()

    def set_view_selection_suspend_status(self, is_suspended: bool) -> None:
        self._table_items.set_view_selection_suspend_status(is_suspended)

    def get_nb_columns(self) -> int:
        return self._table_items.get_nb_columns()

    def get_column_title(self, column: int) -> str:
        return self._table_items.get_column_title(column)

    def get_nb_rows(self, parent_rows: Tuple[int, ...] = ()) -> int:
        if len(parent_rows) == 0:
            return self._table_items.get_nb_rows()
        else:
            return 0

    def get_data(self, row: int, column: int, parent_rows: Tuple[int, ...] = ()) -> str:
        return self._table_items.get_data(row, column)

    def get_title(self, parent_rows: Tuple[int, ...] = ()) -> str:
        return self._table_items.get_title()

    def get_exported_column_indices(self, parent_rows: Tuple[int, ...] = ()) -> List[int]:
        return self._table_items.get_exported_column_indices()

    def get_exported_column_names(self, parent_rows: Tuple[int, ...] = ()) -> List[str]:
        return self._table_items.get_exported_column_names()

    def insert(self, row: int, parent_rows: Tuple[int, ...] = ()) -> Optional[Tuple[int, ...]]:
        new_row = self._table_items.insert(row)
        if new_row is not None:
            return (new_row,)
        return None

    def remove(self, row: int, parent_rows: Tuple[int, ...] = ()) -> Optional[Tuple[int, ...]]:
        new_selected_row = self._table_items.remove(row)
        if new_selected_row is not None:
            return (new_selected_row,)
        return None

    def remove_all(self) -> None:
        return self._table_items.remove_all()

    def move(
        self,
        from_row: int,
        to_row: int,
        from_parent_rows: Tuple[int, ...] = (),
        to_parent_rows: Tuple[int, ...] = (),
    ) -> bool:
        return self._table_items.move(from_row, to_row)

    def set_data(
        self, row: int, column: int, value: str, parent_rows: Tuple[int, ...] = ()
    ) -> bool:
        return self._table_items.set_data(row, column, value)

    def get_edit_data(self, row: int, column: int, parent_rows: Tuple[int, ...] = ()) -> Any:
        return self._table_items.get_edit_data(row, column)

    def is_checked(
        self, row: int, column: int, parent_rows: Tuple[int, ...] = ()
    ) -> Optional[bool]:
        return self._table_items.is_checked(row, column)

    def set_checked(
        self, row: int, column: int, value: bool, parent_rows: Tuple[int, ...] = ()
    ) -> bool:
        return self._table_items.set_checked(row, column, value)

    def is_editable(self, row: int, column: int, parent_rows: Tuple[int, ...] = ()) -> bool:
        return self._table_items.is_editable(row, column)

    def is_enabled(self, row: int, column: int, parent_rows: Tuple[int, ...] = ()) -> bool:
        return self._table_items.is_enabled(row, column)

    def get_delegate_props(
        self, column: int, *, row: Optional[int] = None, parent_rows: Tuple[int, ...] = ()
    ) -> Optional[DelegateProps]:
        return self._table_items.get_delegate_props(column, row=row)

    def get_background(
        self, row: int, column: int, parent_rows: Tuple[int, ...] = ()
    ) -> BackgroundType:
        return self._table_items.get_background(row, column)

    def is_filtered(self, row: int, parent_rows: Tuple[int, ...] = ()) -> bool:
        return self._table_items.is_filtered(row)

    def get_expand_positions(self) -> List[Tuple[int, ...]]:
        return []

    def set_expanded(
        self, row: int, is_expanded: bool, parent_rows: Tuple[int, ...] = ()
    ) -> None:
        return None

    def get_infos(self, parent_rows: Tuple[int, ...] = ()) -> OrderedDict[str, Any]:
        return self._table_items.get_infos()

    def iter_trigger_dependencies(self) -> Generator[None, None, None]:
        for _ in self._table_items.iter_trigger_dependencies():
            yield

    def converter(self) -> ItemsConverter[Self]:
        return ItemsConverter(self)

from composeui.commontypes import AnyItemsView, AnyModel
from composeui.items.core.abstractitems import AbstractItems
from composeui.items.core.itemsconverter import ItemsConverter
from composeui.items.core.itemsutils import BackgroundType, DelegateProps
from composeui.items.core.paginationnavigator import PaginationNavigator

from typing_extensions import OrderedDict

import typing
from abc import abstractmethod
from typing import Any, Iterator, List, Optional, cast

if typing.TYPE_CHECKING:
    from composeui.items.core.tabletotreeitems import TableToTreeItems

if typing.TYPE_CHECKING:
    from composeui.items.core.tabletotreeitems import TableToTreeItems


class AbstractTableItems(AbstractItems[AnyItemsView, AnyModel]):
    """Abstract of the items of a table.

    There is two way to subclass it:
        - implement the methods that uses the row index of the table. Therefore the methods
        with the row id as an argument can be ignored because the row id will be the row index
        of the table.
        - implement the methods that uses the row id of the table. Therefore the methods
        get_id_by_row and get_row_by_id need to be implemented because they are essential to
        navigate between the row id and the row. Implementing these two methods are enough
        to make the methods using the rows usable.

    """

    def __init__(self, view: AnyItemsView, model: AnyModel, *, title: str = "") -> None:
        super().__init__(view, model, title=title)
        # self._view: ITableView[Self]
        self.page_navigator = PaginationNavigator(self._view.pagination_view, self)

    def get_cached_data(self) -> Optional[List[List[str]]]:
        """Get the cached data of the table or returns None if there is no cache

        By default, there is no cache the method should be reimplemented to use a cache.
        In the implementation be careful to invalidate the cache when the table is modified.
        """
        return None

    def update_cache(self) -> None:
        """Called to update the cache.

        This method should be implemented to update the cache when the data have been modified.
        By default the method does nothing.
        """
        return None

    @abstractmethod
    def get_nb_rows(self) -> int:
        """Get the number of rows."""
        return 0

    def iter_row_ids(self) -> Iterator[Any]:
        """Iterate over the row ids of the table.

        By default the row ids are the row of the table but this could be override to use
        something else as a key of a dictionary or an id of an sql table or whatever else.
        """
        yield from range(self.get_nb_rows())

    def get_row_from_id(self, rid: Any) -> int:
        """Get the row index for the given row id.

        For the opposite call get_id_from_row.

        By default the row id is the row of the table but this could be override to use
        something else as a key of a dictionary or an id of an sql table or whatever else.
        """
        return cast(int, rid)

    def get_id_from_row(self, row: int) -> Any:
        """Get the row id for the given row index.

        For the opposite call get_row_from_id.

        By default the row id is the row of the table but this could be override to use
        something else as a key of a dictionary or an id of an sql table or whatever else.
        """
        return row

    def get_data(self, row: int, column: int) -> str:
        """Get the displayed data of the item at the given row and column.

        The data is returned as a string.
        Use the helper method display_float for transforming a float value into a string.
        """
        return self.get_data_by_id(self.get_id_from_row(row), column)

    @abstractmethod
    def get_data_by_id(self, rid: Any, column: int) -> str:
        """Get the displayed data of the item at the given row id and column.

        By default the row id is the row of the table but this could be override to use
        something else as a key of a dictionary or an id of an sql table or whatever else.

        The data is returned as a string.
        Use the helper method display_float for transforming a float value into a string.
        """
        return ""

    def get_data_by_row(self, row: int) -> List[str]:
        """Get the data for the entire row.

        The method is implemented using the method get_data.
        When performance is crucial please reimplement the method.
        For example, when using an sql database multiple SELECT for each columns
        are slower than getting all the columns at once.

        The data is returned as a string.
        Use the helper method display_float for transforming a float value into a string.
        """
        return [self.get_data(row, column) for column in range(self.get_nb_columns())]

    def get_all_datas(self) -> List[List[str]]:
        """Get all the displayed data of the table.

        The method is implemented using the method get_data.
        When performance is crucial please reimplement the method.
        For example, when using an sql database multiple SELECT for each columns
        are slower than getting all the columns at once.

        The data is returned as a string.
        Use the helper method display_float for transforming a float value into a string.
        """
        return [
            [self.get_data(row, column) for row in range(self.get_nb_rows())]
            for column in range(self.get_nb_columns())
        ]

    def get_title(self) -> str:
        """Get the title of the table."""
        return self._title

    def get_slug_title(self) -> str:
        """Get the slug title of the table."""
        return self._title.replace(" ", "_").lower().strip()

    def get_exported_column_indices(self) -> List[int]:
        """Get the indices of the columns that should be exported.

        By default all the columns are exported.
        """
        return list(range(self.get_nb_columns()))

    def get_exported_column_names(self) -> List[str]:
        """Get the names of the columns that should be exported."""
        names = self.get_column_names()
        return [names[i] for i in self.get_exported_column_indices()]

    def insert(self, row: int) -> Optional[int]:
        """Insert a row at the table and return the row to be selected afterwards.

        None means no selection afterwards.
        """
        return row

    def remove(self, row: int) -> Optional[int]:
        """Remove the given row of the table.

        Override to remove the row from the model and call the parent method to return:
            - the row to be selected afterwards.
            - None if there is no selection afterwards.
        """
        rid = self.remove_by_id(self.get_id_from_row(row))
        if rid is not None:
            return self.get_row_from_id(rid)
        return None

    def remove_by_id(self, rid: int) -> Optional[Any]:
        """Remove the given row id of the table.

        Override to remove the row from the model and call the parent method to return:
            - the row to be selected afterwards.
            - None if there is no selection afterwards.
        """
        row = self.get_row_from_id(rid)
        self._remove_by_id(rid)
        nb_rows = self.get_nb_rows()
        if row < nb_rows:  # select the next item if available
            return self.get_id_from_row(row)
        elif row > 0:  # if there is not item available select the previous item
            return self.get_id_from_row(row - 1)
        else:  # if there is not item available select nothing
            return None

    def _remove_by_id(self, rid: Any) -> None:
        """Remove the given row id of the table.

        This method should be implemented when the rows of the table can be removed.
        """
        raise NotImplementedError

    def remove_all(self) -> None:
        """Remove all the rows of the table."""
        for row in range(self.get_nb_rows() - 1, -1, -1):
            self._remove_by_id(self.get_id_from_row(row))

    def move(self, from_row: int, to_row: int) -> bool:
        """Move an item to another position, return True if succeded, False otherwise.

        Works only if the option of drag_drop_enabled of the table is set to True.
        """
        return False

    def set_data(self, row: int, column: int, value: str) -> bool:
        """Set the data at the given row and column.

        Returns True if the value is valid and has been set, False otherwise.

        Use the helper method to_float_value to transform the value to a float
        Use the helper method to_int_value to transform the value to an int
        """
        return self.set_data_by_id(self.get_id_from_row(row), column, value)

    def set_data_by_id(self, rid: Any, column: int, value: str) -> bool:
        """Set the data at the given row id and column.

        Returns True if the value is valid and has been set, False otherwise.

        Use the helper method to_float_value to transform the value to a float
        Use the helper method to_int_value to transform the value to an int
        """
        return False

    def set_data_with_history(self, row: int, column: int, value: str) -> bool:
        """Set the data at the given row and column.

        It is used to save the history of the modification.
        If the data saved don't need to be in the history the method can be reimplemented
        to avoid it.
        """
        with self._model.record_history():
            return self.set_data(row, column, value)

    def get_edit_data(self, row: int, column: int) -> Any:
        """Get the data displayed during the edition of an item.

        By default the value is the same as the value displayed.
        """
        return self.get_edit_data_by_id(self.get_id_from_row(row), column)

    def get_edit_data_by_id(self, rid: Any, column: int) -> Any:
        """Get the data displayed during the edition of an item.

        By default the value is the same as the value displayed.
        """
        return self.get_data_by_id(rid, column)

    def is_checked(self, row: int, column: int) -> Optional[bool]:
        """Check if the item is checked or return None if there is no checkbox."""
        return self.is_checked_by_id(self.get_id_from_row(row), column)

    def is_checked_by_id(self, rid: Any, column: int) -> Optional[bool]:
        """Check if the item is checked or return None if there is no checkbox."""
        return None

    def set_checked(self, row: int, column: int, value: bool) -> bool:
        """Set if the item is checked or not.

        Only works if the item has a checkbox which means the method is_checked
        don't return None.
        """
        return self.set_checked_by_id(self.get_id_from_row(row), column, value)

    def set_checked_by_id(self, rid: Any, column: int, value: bool) -> bool:
        """Set if the item is checked or not.

        Only works if the item has a checkbox which means the method is_checked
        don't return None.
        """
        return False

    def set_checked_with_history(self, row: int, column: int, value: bool) -> bool:
        """Set if the item is checked or not.

        It is used to save the history of the modification.
        If the check don't need to be in the history the method can be reimplemented
        to avoid it.
        """
        return self.set_checked_by_id_with_history(self.get_id_from_row(row), column, value)

    def set_checked_by_id_with_history(self, rid: Any, column: int, value: bool) -> bool:
        """Set if the item is checked or not.

        It is used to save the history of the modification.
        If the check don't need to be in the history the method can be reimplemented
        to avoid it.
        """
        with self._model.record_history():
            return self.set_checked_by_id(rid, column, value)

    def is_editable(self, row: int, column: int) -> bool:
        """Check if the item is editable."""
        return self.is_editable_by_id(self.get_id_from_row(row), column)

    def is_editable_by_id(self, rid: Any, column: int) -> bool:
        """Check if the item is editable."""
        return False

    def is_enabled(self, row: int, column: int) -> bool:
        """Check if the item is enabled."""
        return self.is_enabled_by_id(self.get_id_from_row(row), column)

    def is_enabled_by_id(self, rid: Any, column: int) -> bool:
        """Check if the item is enabled."""
        return True

    def get_delegate_props(
        self, column: int, *, row: Optional[int] = None
    ) -> Optional[DelegateProps]:
        """Get the delegate properties of the item.

        The type should be the same for all the rows of the same column.
        Only the properties can be different but not necesarilly.

        - ComboBoxDelegateProps: A combobox will be displayed with its values to choose
        - FloatDelegateProps: A LineEdit with a double validator with the given properties
        - IntDelegateProps: A Spinbox with the given properties
        - None: normal display
        """
        rid = None
        if row is not None:
            rid = self.get_id_from_row(row)
        return self.get_delegate_props_by_id(column, rid=rid)

    def get_delegate_props_by_id(
        self, column: int, *, rid: Optional[Any] = None
    ) -> Optional[DelegateProps]:
        """Get the delegate properties of the item.

        The type should be the same for all the rows of the same column.
        Only the properties can be different but not necesarilly.

        - ComboBoxDelegateProps: A combobox will be displayed with its values to choose
        - FloatDelegateProps: A LineEdit with a double validator with the given properties
        - IntDelegateProps: A Spinbox with the given properties
        - None: normal display
        """
        return None

    def get_background(self, row: int, column: int) -> BackgroundType:
        """Get the background for the given row and column."""
        return self.get_background_by_id(self.get_id_from_row(row), column)

    def get_background_by_id(self, rid: Any, column: int) -> BackgroundType:
        """Get the background for the given row and column."""
        return BackgroundType.NONE

    def get_selected_rows(self) -> List[int]:
        """Get the selected rows.

        This method should not be reimplemented or do it with care.
        """
        return [position[-1] for position in self._view.selected_items]

    def get_selected_ids(self) -> List[Any]:
        """Get the selected rows.

        This method should not be reimplemented or do it with care.
        """
        return [self.get_id_from_row(position[-1]) for position in self._view.selected_items]

    def set_selected_rows(self, rows: List[int]) -> None:
        """Set the selected rows.

        This method should not be reimplemented or do it with care.
        """
        columns = list(range(self.get_nb_columns()))
        self._view.selected_items = OrderedDict(((row,), columns) for row in rows)

    def set_selected_ids(self, rids: List[Any]) -> None:
        """Set the selected ids.

        This method should not be reimplemented or do it with care.
        """
        columns = list(range(self.get_nb_columns()))
        self._view.selected_items = OrderedDict(
            ((self.get_row_from_id(rid),), columns) for rid in rids
        )

    def get_selected_row_items(self) -> OrderedDict[int, List[int]]:
        """Get the selected items by row.

        This method should not be reimplemented or do it with care.

        Same as get_selected_items but use the row directly instead of the path of rows.
        """
        return OrderedDict(
            (row, columns) for (*_, row), columns in self._view.selected_items.items()
        )

    def get_selected_id_items(self) -> OrderedDict[Any, List[int]]:
        """Get the selected items by row id.

        This method should not be reimplemented or do it with care.

        Same as get_selected_items but use the row id directly instead of the path of rows.
        """
        return OrderedDict(
            (self.get_id_from_row(row), columns)
            for (*_, row), columns in self._view.selected_items.items()
        )

    def set_selected_row_items(self, selected_row_items: OrderedDict[int, List[int]]) -> None:
        """Set the selected items by row.

        This method should not be reimplemented or do it with care.

        Same as set_selected_items but use the row directly instead of the path of rows.
        """
        self._view.selected_items = OrderedDict(
            ((row,), columns) for row, columns in selected_row_items.items()
        )

    def set_selected_id_items(self, selected_id_items: OrderedDict[Any, List[int]]) -> None:
        """Set the selected items by row id.

        This method should not be reimplemented or do it with care.

        Same as set_selected_items but use the row directly instead of the path of rows.
        """
        self._view.selected_items = OrderedDict(
            ((self.get_row_from_id(rid),), columns)
            for rid, columns in selected_id_items.items()
        )

    def is_filtered(self, row: int) -> bool:
        """Check if the row is filtered or not.

        This method should not be reimplemented or do it with care.

        If the row id is not on the current page then it is considered as filtered otherwise
        it uses the configuration of the filter to determine if the row id is filtered or not.
        """
        return not self._is_on_current_page(row) or (
            len(self.filter_column_indices) > 0
            and self.filter_manager.has_pattern
            and all(
                not self.filter_manager.match(self.get_data(row, column))
                for column in self.filter_column_indices
            )
        )

    def is_filtered_by_id(self, rid: Any) -> bool:
        """Check if the row id is filtered or not.

        This method should not be reimplemented or do it with care.

        If the row id is not on the current page then it is considered as filtered otherwise
        it uses the configuration of the filter to determine if the row id is filtered or not.
        """
        row = self.get_row_from_id(rid)
        return self.is_filtered(row)

    def get_infos(self) -> OrderedDict[str, Any]:
        """Get the informations that can be added to the export in Markdown/HTML.

        This method sould be reimplemented only if the export of the table in markdown or html
        is used to display more informations about the table.
        The informations will appear as a list in the following format:
        - **{key}**: {value}
        """
        return OrderedDict()

    def converter(self) -> "ItemsConverter[TableToTreeItems[AnyModel]]":
        """Return the table items converter.

        This method should not be reimplemented or do it with care.

        Can be used to convert the table to a pandas dataframe or a markdown table
        or an html table.
        """
        from composeui.items.core.tabletotreeitems import TableToTreeItems

        return ItemsConverter(TableToTreeItems(self))

    def _is_on_current_page(self, row: int) -> bool:
        """Check if the given row is on the current page of the table.

        This method should not be reimplemented or do it with care.

        If the pagination is not active, it will always return True because all the rows
        are on the page.
        """
        return not self._view.has_pagination or (
            self.page_navigator.get_current_min_row()
            <= row
            <= self.page_navigator.get_current_max_row()
        )

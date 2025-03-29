from composeui.commontypes import AnyItemsView, AnyModel
from composeui.items.core.abstractitems import AbstractItems
from composeui.items.core.itemsconverter import ItemsConverter
from composeui.items.core.itemsutils import BackgroundType, DelegateProps
from composeui.items.core.paginationnavigator import PaginationNavigator

from typing_extensions import OrderedDict

from abc import abstractmethod
from typing import Any, List, Optional
import typing

if typing.TYPE_CHECKING:
    from composeui.items.core.tabletotreeitems import TableToTreeItems


class AbstractTableItems(AbstractItems[AnyItemsView, AnyModel]):
    r"""Abstract of the items of a table."""

    def __init__(self, view: AnyItemsView, model: AnyModel, *, title: str = "") -> None:
        super().__init__(view, model, title=title)
        # self._view: ITableView[Self]
        self.page_navigator = PaginationNavigator(self._view.pagination_view, self)

    @abstractmethod
    def get_nb_rows(self) -> int:
        """Get the number of rows."""
        return 0

    @abstractmethod
    def get_data(self, row: int, column: int) -> str:
        """Get the displayed data.

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
        nb_rows = self.get_nb_rows()
        # select the next item if available
        if row < nb_rows:
            return row
        # if none select the previous item
        elif row > 0:
            return row - 1
        # otherwise no selection
        return None

    def remove_all(self) -> None:
        """Remove all the rows of the table/tree."""
        for row in range(self.get_nb_rows() - 1, -1, -1):
            self.remove(row)

    def move(self, from_row: int, to_row: int) -> bool:
        """Move an item to another position, return True if succeded, False otherwise.

        Works only if the option of drag_drop_enabled of the table is set to True.
        """
        return False

    def set_data(self, row: int, column: int, value: str) -> bool:
        r"""Set the data at the given row and column.

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
        return self.get_data(row, column)

    def is_checked(self, row: int, column: int) -> Optional[bool]:
        """Check if the item is checked or return None if there is no checkbox."""
        return None

    def set_checked(self, row: int, column: int, value: bool) -> bool:
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
        with self._model.record_history():
            return self.set_checked(row, column, value)

    def is_editable(self, row: int, column: int) -> bool:
        """Check if the item is editable."""
        return False

    def is_enabled(self, row: int, column: int) -> bool:
        """Check if the item is enabled."""
        return True

    def get_delegate_props(self, row: int, column: int) -> Optional[DelegateProps]:
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
        # TODO: increase the posibilities of this method
        return BackgroundType.NONE

    def get_selected_rows(self) -> List[int]:
        """Get the selected rows."""
        return [position[-1] for position in self._view.selected_items]

    def set_selected_rows(self, rows: List[int]) -> None:
        """Set the selected rows."""
        columns = list(range(self.get_nb_columns()))
        self._view.selected_items = OrderedDict(((row,), columns) for row in rows)

    def get_selected_row_items(self) -> OrderedDict[int, List[int]]:
        """Get the selected items by row.

        Same as get_selected_items but use the row directly instead of the path of rows.
        """
        return OrderedDict(
            (row, columns) for (*_, row), columns in self._view.selected_items.items()
        )

    def set_selected_row_items(self, selected_row_items: OrderedDict[int, List[int]]) -> None:
        """Set the selected items by row.

        Same as set_selected_items but use the row directly instead of the path of rows.
        """
        self._view.selected_items = OrderedDict(
            ((row,), columns) for row, columns in selected_row_items.items()
        )

    def is_filtered(self, row: int) -> bool:
        """Check if the row is filtered or not."""
        return not self._is_on_current_page(row) or (
            len(self.filter_column_indices) > 0
            and self.filter_manager.has_pattern
            and all(
                not self.filter_manager.match(self.get_data(row, column))
                for column in self.filter_column_indices
            )
        )

    def get_infos(self) -> OrderedDict[str, Any]:
        """Get the informations that can be added to the export in Markdown/HTML.

        The informations will appear as a list in the following format:
        - **{key}**: {value}
        """
        return OrderedDict()

    def converter(self) -> ItemsConverter["TableToTreeItems[AnyModel]"]:
        """Return the table items converter.

        Can be used to convert the table to a pandas dataframe or a markdown table
        or an html table.
        """
        from composeui.items.core.tabletotreeitems import TableToTreeItems

        return ItemsConverter(TableToTreeItems(self))

    def _is_on_current_page(self, row: int) -> bool:
        return not self._view.has_pagination or (
            self.page_navigator.get_current_min_row()
            <= row
            <= self.page_navigator.get_current_max_row()
        )

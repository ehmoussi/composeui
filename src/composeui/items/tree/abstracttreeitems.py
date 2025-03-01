from composeui.commontypes import AnyItemsView, AnyModel
from composeui.items.core.abstractitems import AbstractItems
from composeui.items.core.itemsconverter import ItemsConverter
from composeui.items.core.itemsutils import BackgroundType, DelegateProps
from composeui.items.core.paginationnavigator import PaginationNavigator

from typing_extensions import OrderedDict, Self

from abc import abstractmethod
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Tuple


class AbstractTreeItems(AbstractItems[AnyItemsView, AnyModel]):
    """Abstract of the items of a tree."""

    def __init__(
        self, view: AnyItemsView, model: AnyModel, *, title: str = "", depth: int = 1
    ) -> None:
        super().__init__(view, model, title=title)
        # TODO: Manage dynamic depth
        self.depth = depth
        # The import is here to avoid circular import
        from composeui.items.core.treetotableitems import TreeToTableItems

        self.page_navigator = PaginationNavigator(
            self._view.pagination_view, TreeToTableItems(self, ())
        )

    @abstractmethod
    def get_nb_rows(self, parent_rows: Tuple[int, ...] = ()) -> int:
        """Get the number of rows."""
        return 0

    @abstractmethod
    def get_data(self, row: int, column: int, parent_rows: Tuple[int, ...] = ()) -> str:
        """Get the displayed data.

        The data is returned as a string.
        Use the helper method display_float for transforming a float value into a string.
        """
        return ""

    def get_all_datas(self) -> Dict[Tuple[int, ...], List[List[str]]]:
        """Get all the displayed data."""
        datas = {}
        nb_columns = self.get_nb_columns()
        parent_rows_queue: Deque[Tuple[int, ...]] = deque([()])
        while len(parent_rows_queue) > 0:
            parent_rows = parent_rows_queue.popleft()
            nb_rows = self.get_nb_rows(parent_rows)
            datas[parent_rows] = [
                [self.get_data(row, column, parent_rows) for column in range(nb_columns)]
                for row in range(nb_rows)
            ]
            parent_rows_queue.extend((*parent_rows, row) for row in range(nb_rows))
        return datas

    def get_title(self, parent_rows: Tuple[int, ...] = ()) -> str:
        """Get the title of the tree."""
        if len(parent_rows) > 0:
            *ascendant_rows, parent_row = parent_rows
            return self.get_data(parent_row, 0, tuple(ascendant_rows))
        else:
            return self._title

    def get_exported_column_indices(self, parent_rows: Tuple[int, ...] = ()) -> List[int]:
        """Get the indices of the columns that should be exported.

        By default all the columns are exported.
        """
        return list(range(self.get_nb_columns()))

    def get_exported_column_names(self, parent_rows: Tuple[int, ...] = ()) -> List[str]:
        """Get the names of the exported columns.

        By default all redundant column names of the children will be appended by its depth.
        For example the column name will be:
            - "Name" for the first level
            - "Name.1" for the second level
            - "Name.2" for the third level and so on...
        It's useful to avoid duplicate column names when exporting data.

        The method can be override if the default behavior is not suitable.
        """
        names = self.get_column_names()
        levels = [0] * len(names)
        for i in range(len(parent_rows)):
            indices = self.get_exported_column_indices(parent_rows[:i])
            for j in indices:
                levels[j] += 1
        for i, level in enumerate(levels):
            if level != 0:
                names[i] += f".{level}"
        return [names[i] for i in self.get_exported_column_indices(parent_rows)]

    def insert(self, row: int, parent_rows: Tuple[int, ...] = ()) -> Optional[Tuple[int, ...]]:
        """Insert a row at the table and return the row position to be selected afterwards.

        An empty tuple or None means no selection afterwards.
        """
        return (row,)

    def remove(self, row: int, parent_rows: Tuple[int, ...] = ()) -> Optional[Tuple[int, ...]]:
        """Remove the given row of the table.

        Override to remove the row from the model and call the parent method to return:
            - the tuple position of the row to be selected afterwards.
            - An empty tuple or None if there is no selection afterwards.
        """
        nb_rows = self.get_nb_rows(parent_rows)
        # select the next item if available
        if row < nb_rows:
            return (*parent_rows, row)
        # if none select the previous item
        elif row > 0:
            return (*parent_rows, row - 1)
        # otherwise no selection
        return None

    def remove_all(self) -> None:
        """Remove all the rows of the tree."""
        for row in range(self.get_nb_rows() - 1, -1, -1):
            self.remove(row)

    def move(
        self,
        from_row: int,
        to_row: int,
        from_parent_rows: Tuple[int, ...] = (),
        to_parent_rows: Tuple[int, ...] = (),
    ) -> bool:
        """Move an item to another position, return True if succeded, False otherwise.

        Works only if the option of drag_drop_enabled of the table is set to True.
        """
        return False

    def set_data(
        self, row: int, column: int, value: str, parent_rows: Tuple[int, ...] = ()
    ) -> bool:
        r"""Set the data at the given row and column.

        Use the helper method to_float_value to transform the value to a float
        Use the helper method to_int_value to transform the value to an int
        """
        return False

    def get_edit_data(self, row: int, column: int, parent_rows: Tuple[int, ...] = ()) -> Any:
        """Get the data displayed during the edition of an item.

        By default the value is the same as the value displayed.
        """
        return self.get_data(row, column, parent_rows)

    def is_checked(
        self, row: int, column: int, parent_rows: Tuple[int, ...] = ()
    ) -> Optional[bool]:
        """Check if the item is checked or return None if there is no checkbox."""
        return None

    def set_checked(
        self, row: int, column: int, value: bool, parent_rows: Tuple[int, ...] = ()
    ) -> bool:
        """Set if the item is checked or not.

        Only works if the item has a checkbox which means the method is_checked
        don't return None.
        """
        return False

    def is_editable(self, row: int, column: int, parent_rows: Tuple[int, ...] = ()) -> bool:
        """Check if the item is editable."""
        return False

    def is_enabled(self, row: int, column: int, parent_rows: Tuple[int, ...] = ()) -> bool:
        """Check if the item is enabled."""
        return True

    def get_delegate_props(
        self, row: int, column: int, parent_rows: Tuple[int, ...] = ()
    ) -> Optional[DelegateProps]:
        """Get the delegate properties of the item.

        The type should be the same for all the rows of the same column.
        Only the properties can be different.

        - ComboBoxDelegateProps: A combobox will be displayed with its values to choose
        - FloatDelegateProps: A LineEdit with a double validator with the given properties
        - IntDelegateProps: A Spinbox with the given properties
        - None: normal display
        """
        return None

    def get_background(
        self, row: int, column: int, parent_rows: Tuple[int, ...] = ()
    ) -> BackgroundType:
        """Get the background for the given row and column."""
        # TODO: increase the posibilites of this method
        return BackgroundType.NONE

    def is_filtered(self, row: int, parent_rows: Tuple[int, ...] = ()) -> bool:
        """Check if the row is filtered or not."""
        return not self._is_on_current_page(
            parent_rows[0] if len(parent_rows) > 0 else row
        ) or (
            len(self.filter_column_indices) > 0
            and self.filter_manager.has_pattern
            and all(
                not self.filter_manager.match(self.get_data(row, column, parent_rows))
                for column in self.filter_column_indices
            )
        )

    def get_expand_positions(self) -> List[Tuple[int, ...]]:
        """Get the expand positions.

        This method should be override only if the status of the expansion of each item
        is stored into the model.
        The point is to retrieve the status even when an insertion or a removal occurs.
        """
        return []

    def set_expanded(
        self, row: int, is_expanded: bool, parent_rows: Tuple[int, ...] = ()
    ) -> None:
        """Set the expansion status of the row.

        This method should be override only if the status of the expansion of each item
        is stored into the model.
        The point is to store the status to retrieve it even when an insertion
        or a removal occurs.
        """
        return None

    def get_infos(self, parent_rows: Tuple[int, ...] = ()) -> OrderedDict[str, Any]:
        """Get the informations that can be added to the export in Markdown/HTML.

        The informations will appear as a list in the following format:
        - **{key}**: {value}
        """
        return OrderedDict()

    def converter(self) -> ItemsConverter[Self]:
        """Return the tree items converter.

        Can be used to convert the tree to a pandas dataframe or a markdown table
        or an html table.
        """
        return ItemsConverter(self)

    def _is_on_current_page(self, row: int) -> bool:
        return not self._view.has_pagination or (
            self.page_navigator.get_current_min_row()
            <= row
            <= self.page_navigator.get_current_max_row()
        )

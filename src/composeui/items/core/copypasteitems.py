from composeui.commontypes import AnyModel
from composeui.items.core.clipboarditems import ClipboardItems
from composeui.items.core.tabletotreeitems import TableToTreeItems
from composeui.items.table.abstracttableitems import AbstractTableItems
from composeui.items.tree.abstracttreeitems import AbstractTreeItems

from typing_extensions import OrderedDict

from typing import Any, List, Sequence, Set, Tuple, Union


class CopyPasteItems:
    def __init__(
        self, items: Union[AbstractTableItems[AnyModel], AbstractTreeItems[AnyModel]]
    ) -> None:
        self._items: AbstractTreeItems[AnyModel]
        if isinstance(items, AbstractTableItems):
            self._items = TableToTreeItems(items)
        else:
            self._items = items
        self.paste_successful: Set[Tuple[int, Tuple[int, ...], int]] = set()
        self.paste_failed: Set[Tuple[int, Tuple[int, ...], int]] = set()

    def clear(self) -> None:
        self.paste_successful = set()
        self.paste_failed = set()

    def copy(self) -> None:
        """Copy the selected items to the clipboard."""
        self.clear()
        ClipboardItems(self._items).write_selection()

    def paste(self) -> None:
        """Paste the data in the clipboard into the selected items.

        It mimic partially Excel's copy/paste functionality.
        It is divided into several branches based on the shape
        and structure of the copied data available in the clipboard.
        If the value can't be inserted/set it is ignored and logged.
        1. One value copied
            1.1 Empty selection: raise a ValueError
            1.2 Otherwise
                Copy the value for each (rows, column) selected item.
        2. Single row copied
            2.1 Empty selection
                2.1.1 The items is not associated then insert as new rows the copied data.
                2.1.2 Otherwise raise a ValueError
            2.2 The selected items correspond also to a single row
                2.2.1 The selected row correspond to a contiguous block
                    2.2.1.1 The contiguous block has a number of columns less or equal than the
                    copied data then paste data.
                    2.2.1.2 Otherwise raise a ValueError
                2.2.2 Otherwise, copy the first item of the copied data to each items of the
                selection
        3. Muliple rows copied
            3.1 Empty selection
                3.1.1 The items is not associated to a tree then insert as new rows
                the copied data.
                3.1.2 Otherwise raise a ValueError
            3.2 Otherwise
                3.2.1 One selected item
                    Copy the copied data as a block from the selected item and truncate
                    the excessive columns and insert the excessive rows.
                3.2.2 Otherwise
                    3.2.2.1 The selected items correspond to a contiguous block of the same
                        size of the copied data then copy each item of the copied data to each
                        item of the selection.
                        If the number of columns of the selected items is less or equal than
                        the number of columns of the copied then the excessive columns are
                        copied too.
                    3.2.2.2 The copied data and the selected items are not contiguous block
                        but have the same shape then copy paste item by item.
                        The copied data is considered not contiguous when it contains
                        nan values
                    3.2.2.2 The selected items are not contiguous then only the first item of
                    the copied data is pasted to each items of the selection.
                    3.2.2.3 Otherwise raise a ValueError
        """
        self.clear()
        parent_rows: Sequence[int]  # to avoid mypy error
        clipboard_items = ClipboardItems()
        try:
            clipboard_items.read_clipboard()
        except Exception:  # noqa: BLE001
            raise ValueError("Can't parse the data from the clipboard.") from None
        # get the current selected items
        selected_items = self._items.get_selected_items()
        if clipboard_items.shape == (1, 1):
            if len(selected_items) == 0:
                raise ValueError(
                    "Data in clipboard doesn't have enough columns to create new row(s)."
                ) from None
            else:
                for (*parent_rows, row), columns in selected_items.items():
                    for column in columns:
                        self._set_data(row, column, clipboard_items.data[0][0], parent_rows)
        elif clipboard_items.shape[0] == 1:
            if (
                len(selected_items) == 0
                # and copied_data.shape[1] == self._items.get_nb_columns()
                and not self._is_tree()
            ):
                # insert rows only if the copied data has the same number of columns
                # as the table and the table isn't a tree
                row = self._items.get_nb_rows()
                self._items.insert(row)
                for column in range(
                    min(clipboard_items.shape[1], self._items.get_nb_columns())
                ):
                    self._set_data(row, column, clipboard_items.data[0][column])
            elif len(selected_items) >= 1:
                selected_columns = set(map(tuple, selected_items.values()))
                selected_columns_size = {len(column) for column in selected_columns}
                if len(selected_columns_size) == 1 and all(
                    sorted(columns) == list(range(min(columns), max(columns) + 1))
                    for columns in selected_columns
                ):
                    # if next(iter(selected_columns_size)) <= copied_data.shape[1]:
                    # paste the data into the selected items if each of the columns
                    # for each row in the selection is a consecutive block with
                    # a number of columns less than the number of columns
                    # of the copied data
                    for (*parent_rows, row), columns in selected_items.items():
                        for i, column in enumerate(columns):
                            if i < clipboard_items.shape[1]:
                                self._set_data(
                                    row, column, clipboard_items.data[0][i], parent_rows
                                )
                            else:
                                self.paste_failed.add((row, tuple(parent_rows), column))
                elif self._same_shape(clipboard_items, selected_items):
                    # paste item by item if the selection has the same shape as the copied data
                    for i, ((*parent_rows, row), columns) in enumerate(selected_items.items()):
                        for j, column in enumerate(columns):
                            self._set_data(
                                row, column, clipboard_items.data[i][j], parent_rows
                            )
                else:
                    # paste only the first item of the copied data if the selection is
                    # not structured
                    for (*parent_rows, row), columns in selected_items.items():
                        for column in columns:
                            self._set_data(
                                row, column, clipboard_items.data[0][0], parent_rows
                            )
            else:
                raise ValueError("No selected items.")
        elif clipboard_items.shape[0] > 1:
            if len(selected_items) == 0 and not self._is_tree():
                # insert rows only if the copied data has the same number of columns
                # as the table and the table isn't a tree
                row = self._items.get_nb_rows()
                for i in range(clipboard_items.shape[0]):
                    self._items.insert(row + i)
                    for column in range(
                        min(clipboard_items.shape[1], self._items.get_nb_columns())
                    ):
                        self._set_data(row + i, column, clipboard_items.data[i][column])
            elif len(selected_items) >= 1:
                columns = next(iter(selected_items.values()))
                if len(selected_items) == 1 and len(columns) == 1:
                    # paste all the data using the selected item as the first item to paste
                    *parent_rows, row = next(iter(selected_items))
                    column = columns[0]
                    for i in range(clipboard_items.shape[0]):
                        if row + i >= self._items.get_nb_rows(tuple(parent_rows)):
                            self._items.insert(row + i, tuple(parent_rows))
                        for j in range(clipboard_items.shape[1]):
                            self._set_data(
                                row + i,
                                column + j,
                                clipboard_items.data[i][j],
                                tuple(parent_rows),
                            )
                else:
                    selected_parent_rows = {
                        tuple(parent_rows) for *parent_rows, _ in selected_items
                    }
                    selected_rows = sorted(row for *_, row in selected_items)
                    selected_columns = set(map(tuple, selected_items.values()))
                    selected_columns_size = {len(column) for column in selected_columns}
                    if (
                        len(selected_parent_rows) == 1
                        and len(selected_rows) <= clipboard_items.shape[0]
                        and selected_rows
                        == list(range(min(selected_rows), max(selected_rows) + 1))
                        and len(selected_columns_size) == 1
                        and all(
                            sorted(columns) == list(range(min(columns), max(columns) + 1))
                            for columns in selected_columns
                        )
                    ):
                        column_size = next(iter(selected_columns_size))
                        if column_size <= clipboard_items.shape[1]:
                            # paste the data into the selected items if each of row and column
                            # in the selection is a consecutive block with a number of rows
                            # and columns less than the number of columns of the copied data
                            parent_rows = next(iter(selected_parent_rows))
                            for i, ((*_, row), columns) in enumerate(selected_items.items()):
                                start_column = min(columns)
                                for j, column in enumerate(
                                    range(
                                        start_column,
                                        min(
                                            self._items.get_nb_columns(),
                                            start_column + clipboard_items.shape[1],
                                        ),
                                    )
                                ):
                                    self._set_data(
                                        row, column, clipboard_items.data[i][j], parent_rows
                                    )
                            if (
                                min(selected_rows) + clipboard_items.shape[0]
                                > self._items.get_nb_rows(tuple(parent_rows))
                                # and column_size == self._items.get_nb_columns()
                            ):
                                start_column = min(next(iter(selected_columns)))
                                for i, row in enumerate(
                                    range(
                                        self._items.get_nb_rows(tuple(parent_rows)),
                                        min(selected_rows) + clipboard_items.shape[0],
                                    ),
                                    start=len(selected_items),
                                ):
                                    self._items.insert(row, tuple(parent_rows))
                                    for j, column in enumerate(
                                        range(
                                            start_column,
                                            min(
                                                start_column + clipboard_items.shape[1],
                                                self._items.get_nb_columns(),
                                            ),
                                        )
                                    ):
                                        self._set_data(
                                            row,
                                            column,
                                            clipboard_items.data[i][j],
                                            parent_rows,
                                        )
                        else:
                            raise ValueError(
                                "The number of columns in the copied data is lesser "
                                "than the number of columns in the selected items."
                            )
                    elif self._same_shape(clipboard_items, selected_items):
                        # paste unstructured copied data to unstructured selected items
                        for i, ((*parent_rows, row), columns) in enumerate(
                            selected_items.items()
                        ):
                            for j, column in enumerate(columns):
                                self._set_data(
                                    row, column, clipboard_items.data[i][j], parent_rows
                                )
                    else:
                        # paste only the first item of the copied data if the selection is
                        # not structured
                        for (*parent_rows, row), columns in selected_items.items():
                            for column in columns:
                                self._set_data(
                                    row, column, clipboard_items.data[0][0], parent_rows
                                )
            else:
                raise ValueError("No selected items.")

    def _is_tree(self) -> bool:
        return not isinstance(self._items, TableToTreeItems)

    def _set_data(
        self, row: int, column: int, value: Any, parent_rows: Sequence[int] = ()
    ) -> None:
        parent_rows = tuple(parent_rows)
        if value is None:
            is_ok = False
        else:
            is_ok = self._items.set_data(row, column, str(value), parent_rows)
        if not is_ok:
            return self.paste_failed.add((row, parent_rows, column))
        return self.paste_successful.add((row, parent_rows, column))

    def _same_shape(
        self,
        clipboard_items: ClipboardItems,
        selected_items: OrderedDict[Tuple[int, ...], List[int]],
    ) -> bool:
        """Check if unstructured selection and copied data have the same shape.

        When the copied data contains nan value it is ignored.
        The copied data can then be considered as unstructured as well.
        """
        if len(selected_items) != clipboard_items.shape[0]:
            return False
        else:
            for i, columns in enumerate(selected_items.values()):
                nb_non_empty_column = 0
                for j in range(clipboard_items.shape[1]):
                    nb_non_empty_column += clipboard_items.data[i][j] is not None
                if nb_non_empty_column != len(columns):
                    return False
        return True

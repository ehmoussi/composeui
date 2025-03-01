from composeui.commontypes import AnyTreeItems
from composeui.core.tasks.abstracttask import AbstractTask
from composeui.items.core.views.itemsview import FormatExtension

import contextlib
from pathlib import Path
from typing import Any, List, Optional

with contextlib.suppress(ImportError, ModuleNotFoundError):
    from openpyxl.utils.exceptions import InvalidFileException
with contextlib.suppress(ImportError, ModuleNotFoundError):
    from xlrd.biffh import XLRDError

try:
    import pandas as pd
except (ImportError, ModuleNotFoundError):
    _HAS_PANDAS = False
else:
    _HAS_PANDAS = True


class ImportFileTreeTask(AbstractTask):
    def __init__(
        self,
        items: AnyTreeItems,
        filepath: Path,
        is_cleaning: bool,
        filepath_extension: FormatExtension,
    ) -> None:
        super().__init__(capture_exceptions_as_errors=True)
        self._items: AnyTreeItems = items
        self._filepath = filepath
        self._is_cleaning = is_cleaning
        self._extension = filepath_extension

    def _run(self) -> Optional[bool]:
        if not _HAS_PANDAS:
            raise ValueError("Can't import the tree without pandas installed.")
        try:
            if self._extension == FormatExtension.CSV:
                # TODO: Add option to choose the separator
                table_df = pd.read_csv(self._filepath, sep=";")
            elif self._extension == FormatExtension.EXCEL:
                try:
                    tables_df = pd.read_excel(
                        self._filepath, sheet_name=None, engine="openpyxl"
                    )
                except InvalidFileException:
                    try:
                        tables_df = pd.read_excel(
                            self._filepath, sheet_name=None, engine="xlrd"
                        )
                    except XLRDError:
                        # old versions of pandas don't manage the bad extension
                        # with openpyxl so it fallback to xlrd which don't know how
                        # to read .xlsx files
                        self.error_message = "Change the extension of the file to .xlsx"
                        return False
                table_df = pd.concat(tables_df, names=["__tree__"])
                # remove the index 0, 1, ... and keep only the keys of the dict which
                # are values of a column of the tree
                table_df.index = table_df.index.droplevel(-1)
                # reset the index to move the parent level as a column
                table_df = table_df.reset_index()
            elif self._extension == FormatExtension.JSON:
                table_df = pd.read_json(self._filepath)
            else:
                self.error_message = (
                    f"The extension '{self._filepath.suffix}' is not supported yet"
                )
                return False
        except (pd.errors.ParserError, pd.errors.EmptyDataError):
            self.error_message = "Unable to read the file due to an incorrect format"
            return False
        else:
            # TODO : Add option to choose what to do if the shape is not identical
            column_names = self._flatten_items_column_names()
            table_df_columns = list(table_df.columns)
            unknown_columns = list(set(table_df_columns) - set(column_names))
            empty_columns = list(set(column_names) - set(table_df_columns))
            if len(unknown_columns) == 1 and unknown_columns[0] == "__tree__":
                if len(empty_columns) == 1:
                    # manage the unknown column name stored as sheets for Excel
                    table_df_columns = [
                        name if name != "__tree__" else empty_columns[0]
                        for name in table_df_columns
                    ]
                    unknown_columns = []
                    empty_columns = []
                elif len(empty_columns) == 0:
                    # manage the case that all the tree is stored in one sheet
                    # the __tree__ column is just an artefact from reading all the sheets of
                    # the Excel file and need to be removed
                    table_df = table_df.drop("__tree__", axis=1)
                    unknown_columns = []
            if len(unknown_columns) == 0:
                if self._is_cleaning:
                    self._items.remove_all()
                if len(empty_columns) > 0:
                    msg = "Can't import a file with the following missing columns:\n"
                    for i in range(min(10, len(empty_columns))):
                        msg += f"- {empty_columns[i]}\n"
                    self.error_message = msg
                    return False
                self._fill_tree(table_df)
            else:
                msg = "Can't import a file with the following unknown columns:\n"
                for i in range(min(10, len(unknown_columns))):
                    msg += f"- {unknown_columns[i]}\n"
                self.error_message = msg
                return False
        return True

    def _flatten_items_column_names(self) -> List[str]:
        column_names: List[str] = []
        for level in range(self._items.depth + 1):
            level_names = self._items.get_exported_column_names((0,) * level)
            column_names.extend(level_names)
        return column_names

    def _fill_tree(self, table_df: "pd.DataFrame") -> None:
        """Fill the tree using the dataframe."""
        parent_rows = [0] * self._items.depth
        parent_rows[0] = self._items.get_nb_rows()
        # separate the columns of the table by level
        # e.g. [0, 2, 5] means the first level has 2 columns and the second level 3
        level_indices = [0]
        for level in range(self._items.depth):
            level_indices.append(
                level_indices[-1] + len(self._items.get_exported_column_indices((0,) * level))
            )
        # store the current parent values to detect a change which means a new parent
        # and a reset of the current row
        parent_values: List[Any] = []
        row = 0
        for _, row_df in table_df.iterrows():
            # initiate the parent values
            if len(parent_values) == 0:
                parent_values = row_df.iloc[: level_indices[-1]].tolist()
                for level in range(self._items.depth):
                    self._items.insert(parent_rows[level], tuple(parent_rows[:level]))
                    for i, column in enumerate(
                        self._items.get_exported_column_indices(tuple(parent_rows[:level]))
                    ):
                        value = parent_values[level_indices[level] + i]
                        self._items.set_data(parent_rows[level], column, value)
            # if the parent values differ insert rows in the parents
            elif parent_values != row_df.iloc[: len(parent_values)].tolist():
                for level in range(self._items.depth):
                    if (
                        parent_values[level_indices[level] : level_indices[level + 1]]
                        != row_df.iloc[
                            level_indices[level] : level_indices[level + 1]
                        ].tolist()
                    ):
                        # parent at the current level differ -> insert a new row
                        parent_rows[level] += 1
                        self._items.insert(parent_rows[level], tuple(parent_rows[:level]))
                        # set the values for each column of the parent
                        for i, column in enumerate(
                            self._items.get_exported_column_indices(tuple(parent_rows[:level]))
                        ):
                            value = row_df.iloc[level_indices[level] + i]
                            parent_values[level_indices[level] + i] = value
                            self._items.set_data(parent_rows[level], column, value)
                        # reset current row to zero because we have a new parent
                        row = 0
            # insert the values at the deepest level
            self._items.insert(row, tuple(parent_rows))
            for column in range(level_indices[-1], len(row_df)):
                self._items.set_data(row, column, row_df.iloc[column], tuple(parent_rows))
            # increment the current row
            row += 1

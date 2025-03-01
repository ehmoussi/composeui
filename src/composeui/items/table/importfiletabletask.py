from composeui.commontypes import AnyTableItems
from composeui.core.tasks.abstracttask import AbstractTask
from composeui.items.core.iitemsview import FormatExtension

import contextlib

with contextlib.suppress(ImportError, ModuleNotFoundError):
    from openpyxl.utils.exceptions import InvalidFileException
with contextlib.suppress(ImportError, ModuleNotFoundError):
    from xlrd.biffh import XLRDError

from pathlib import Path
from typing import Generic, Optional

try:
    import pandas as pd
except (ImportError, ModuleNotFoundError):
    _HAS_PANDAS = False
else:
    _HAS_PANDAS = True


class ImportFileTableTask(AbstractTask, Generic[AnyTableItems]):
    def __init__(
        self,
        items: AnyTableItems,
        filepath: Path,
        is_cleaning: bool,
        extension: FormatExtension,
    ) -> None:
        super().__init__(capture_exceptions_as_errors=True)
        self._items: AnyTableItems = items
        self._filepath = filepath
        self._is_cleaning = is_cleaning
        self._extension = extension

    def _run(self) -> Optional[bool]:
        if not _HAS_PANDAS:
            raise ValueError("Can't import the table without pandas installed.")
        try:
            if self._extension == FormatExtension.CSV:
                table_df = pd.read_csv(self._filepath, sep=";")
            elif self._extension == FormatExtension.EXCEL:
                try:
                    table_df = pd.read_excel(self._filepath, engine="openpyxl")
                except InvalidFileException:
                    try:
                        table_df = pd.read_excel(self._filepath, engine="xlrd")
                    except XLRDError:
                        # old versions of pandas don't manage the bad extension
                        # with openpyxl so it fallback to xlrd which don't know how
                        # to read .xlsx files
                        self.error_message = "Change the extension of the file to .xlsx"
                        return False
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
            column_names = self._items.get_exported_column_names()
            table_df_columns = table_df.columns
            unknown_columns = list(set(table_df_columns) - set(column_names))
            empty_columns = list(set(column_names) - set(table_df_columns))
            if len(unknown_columns) == 0:
                if self._is_cleaning:
                    self._items.remove_all()
                start_row = self._items.get_nb_rows()
                # insert rows
                for row in range(table_df.shape[0]):
                    self._items.insert(start_row + row)
                # set values
                for column_name in table_df_columns:
                    column = column_names.index(column_name)
                    for row in range(table_df.shape[0]):
                        self._items.set_data(
                            start_row + row, column, table_df[column_name].iloc[row]
                        )
                if len(empty_columns) > 0:
                    msg = "The following columns are missing:\n"
                    for i in range(min(10, len(empty_columns))):
                        msg += f"- {empty_columns[i]}\n"
                    if len(empty_columns) > 10:
                        msg += "- ...\n"
                    msg += "Default values are used for those columns."
                    self.warning_message = msg
            else:
                msg = "Can't import a file with the following unknown columns:\n"
                for i in range(min(10, len(unknown_columns))):
                    msg += f"- {unknown_columns[i]}\n"
                if len(unknown_columns) > 10:
                    msg += "- ..."
                self.error_message = msg
                return False
        return True

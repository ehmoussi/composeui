from composeui.commontypes import AnyDetailTableItems, AnyMasterTableItems
from composeui.core.tasks.abstracttask import AbstractTask
from composeui.items.core.iitemsview import FormatExtension

import contextlib
from pathlib import Path
from typing import Optional

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


class ImportFileLinkedTableTask(AbstractTask):
    def __init__(
        self,
        master_items: AnyMasterTableItems,
        detail_items: AnyDetailTableItems,
        filepath: Path,
        is_cleaning: bool,
        extension: FormatExtension,
    ) -> None:
        super().__init__(capture_exceptions_as_errors=True)
        self._master_items = master_items
        self._detail_items = detail_items
        self._filepath = filepath
        self._is_cleaning = is_cleaning
        self._extension = extension

    def _run(self) -> Optional[bool]:
        if not _HAS_PANDAS:
            raise ValueError("Can't import the linked table without pandas installed.")
        try:
            # TODO: Add option to choose the separator
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
            # check if the file is not empty
            if table_df.shape[0] == 0 or table_df.shape[1] == 0:
                self.error_message = "The parsing of the file failed or the file is empty"
                return False
            # Get the exported column indices of the master table and check if they are ok
            master_column_indices = self._master_items.get_exported_column_indices()
            if len(master_column_indices) == 0:
                self.error_message = "The exported column indices of the master table is empty"
                return False
            elif min(master_column_indices) < 0:
                self.error_message = (
                    "The exported column indices of the master table has an index < 0: "
                    f"{master_column_indices}"
                )
                return False
            elif max(master_column_indices) > self._master_items.get_nb_columns():
                self.error_message = (
                    "The exported column indices of the master table has an index greater "
                    f"than the number of columns: {master_column_indices}"
                )
                return False
            # Get the column names of the table corresponding to the master table
            # The lines of the master table are duplicated to be able to be exported
            # along with the detail table
            master_column_names = list(table_df.columns[: len(master_column_indices)])
            # The columns of the master table are used as an index to simplify the separation
            # of the detail table by the lines of the master table
            table_df = table_df.set_index(master_column_names)
            # If the user choose to clean the table then all the lines of the master table
            # are removed otherwise the insertion is after the last row of the master table
            if self._is_cleaning:
                self._master_items.remove_all()
                master_nb_rows = 0
            else:
                master_nb_rows = self._master_items.get_nb_rows()
            # The values for the master are extracted
            # Pandas manage differently when the index has one column or multiple columns
            if len(master_column_indices) == 1:
                master_values = {
                    (master_nb_rows + i): {master_column_indices[0]: value}
                    for i, value in enumerate(table_df.index.unique())
                }
            else:
                master_values = {
                    (master_nb_rows + i): dict(zip(master_column_indices, list(values)))
                    for i, values in enumerate(table_df.index.unique())
                }
            warning_messages = []
            # Iteration over the lines of the master table
            for master_row, values in master_values.items():
                # insertion of the row and set the data for each column
                self._master_items.insert(master_row)
                for master_column, value in values.items():
                    is_ok = self._master_items.set_data(master_row, master_column, value)
                    if not is_ok:
                        warning_messages.append(
                            f"- Failed to set '{value}' at {master_row, master_column} "
                            "of the master table"
                        )
                try:
                    # To avoid to modify the selection of the view the selection is suspended
                    # The selection is modified here to enable the different items of the
                    # detail table which is dependent of the selection of the master table
                    self._master_items.set_view_selection_suspend_status(True)
                    self._master_items.set_selected_rows([master_row])
                    # Extract the detail table for an index of the master table
                    detail_df = table_df.loc[tuple(values.values())]
                    detail_nb_rows = self._detail_items.get_nb_rows()
                    if len(detail_df.shape) == 2:
                        detail_df_nb_rows = detail_df.shape[0]
                        detail_df_nb_cols = detail_df.shape[1]
                    else:
                        detail_df_nb_rows = 1
                        detail_df_nb_cols = detail_df.shape[0]
                    # Iteration over the lines of the detail pandas table
                    for i in range(detail_df_nb_rows):
                        # Insertion of the line and set the data for each column which has been
                        # choosen to be exported
                        detail_row = detail_nb_rows + i
                        self._detail_items.insert(detail_row)
                        for j, detail_column in enumerate(
                            self._detail_items.get_exported_column_indices()
                        ):
                            if j >= detail_df_nb_cols:
                                nb_missing_columns = (
                                    len(self._detail_items.get_exported_column_indices())
                                    - detail_df_nb_cols
                                )
                                warning_messages.append(
                                    f"- Missing {nb_missing_columns} column(s) "
                                    "in the given file"
                                )
                                break
                            if len(detail_df.shape) == 1:
                                value = detail_df.iloc[j]
                            else:
                                value = detail_df.iloc[i, j]
                            is_ok = self._detail_items.set_data(
                                detail_row, detail_column, value
                            )
                            if not is_ok:
                                warning_messages.append(
                                    f"- Failed to set '{value}' at {detail_row, detail_column}"
                                    " of the detail table"
                                )
                finally:
                    # Even if the insertion on the detail table failed the selection
                    # of the master table view is restored
                    self._master_items.set_view_selection_suspend_status(False)
                # The warning messages are added to be displayed to the user
                # but the number of messages are limited to avoid having an illisible message
                self.warning_message = "\n".join(warning_messages[:10])
        return True

from composeui.commontypes import AnyDetailTableItems, AnyMasterTableItems
from composeui.core.tasks.abstracttask import AbstractTask
from composeui.items.core.views.itemsview import FormatExtension
from composeui.items.tree.treeview import ExportTreeOptions

from typing_extensions import OrderedDict

from pathlib import Path
from typing import List, Optional

try:
    import pandas as pd
except (ImportError, ModuleNotFoundError):
    _HAS_PANDAS = False
else:
    _HAS_PANDAS = True


class ExportFileLinkedTableTask(AbstractTask):
    def __init__(
        self,
        master_items: AnyMasterTableItems,
        detail_items: AnyDetailTableItems,
        filepath: Path,
        extension: FormatExtension,
        export_options: ExportTreeOptions,
        title: str,
    ) -> None:
        super().__init__(capture_exceptions_as_errors=True)
        self._master_items = master_items
        self._detail_items = detail_items
        self._filepath = filepath
        self._extension = extension
        self._export_options = export_options
        self._title = title

    def _run(self) -> Optional[bool]:
        if not _HAS_PANDAS:
            raise ValueError("Can't export the linked table without pandas installed.")
        detail_tables_df = self._build_detail_dataframes()
        if len(detail_tables_df) == 0:
            self.error_message = "Can't export empty tables"
            return False
        elif self._extension == FormatExtension.EXCEL:
            is_ok = True
            with pd.ExcelWriter(self._filepath, mode="w") as f:
                if ExportTreeOptions.USE_PARENT_SHEET_NAMES in self._export_options:
                    has_default_sheet_name = False
                    for i, (title, master_detail_table_df) in enumerate(
                        detail_tables_df.items()
                    ):
                        # each table is exported into one sheet
                        sheet_name = title
                        if sheet_name == "":
                            sheet_name = f"DetailTable {i}"
                            has_default_sheet_name = True
                        is_ok &= self._export(
                            master_detail_table_df, title=sheet_name, writer=f
                        )
                    if has_default_sheet_name and self.is_debug:
                        self.warning_message = (
                            "The default title is used. To avoid it implement the method "
                            "'get_title' of the detail table."
                        )
                else:
                    # all the tables concatenate in one big table and exported into one sheet
                    merged_table_df = pd.concat(detail_tables_df.values(), ignore_index=True)
                    is_ok = self._export(merged_table_df, title=self._title, writer=f)
            return is_ok
        else:
            # concatenation by row of all the detail tables to have only one table
            # that can be exported
            merged_table_df = pd.concat(detail_tables_df, ignore_index=True)
            return self._export(merged_table_df, title=self._title)

    def _export(
        self,
        table_df: "pd.DataFrame",
        *,
        title: str,
        writer: Optional["pd.ExcelWriter"] = None,
    ) -> bool:
        try:
            if self._extension == FormatExtension.CSV:
                table_df.to_csv(self._filepath, sep=";", index=False)
            elif self._extension == FormatExtension.EXCEL:
                sheet_name = title
                if sheet_name == "":
                    sheet_name = "LinkedTable"
                assert writer is not None, "The writer is mandatory for Excel"
                table_df.to_excel(writer, sheet_name=sheet_name, index=False)
            elif self._extension == FormatExtension.JSON:
                try:
                    # TODO: Maybe not using pandas for the linked table ?
                    table_df.to_json(self._filepath, orient="records", index=False)
                except ValueError:
                    self.error_message = (
                        f"The current version of pandas '{pd.__version__}' "
                        "is too old to export in json"
                    )
                    return False
            elif self._extension == FormatExtension.MARKDOWN:
                with open(self._filepath, "w") as f:
                    table_df.to_markdown(f, index=False)
            elif self._extension == FormatExtension.HTML:
                table_df.to_html(self._filepath, index=False)
            else:
                self.error_message = (
                    f"The extension '{self._filepath.suffix}' is not supported yet"
                )
                return False
        except PermissionError:
            self.error_message = "Can't write into the file if it's already open elsewhere."
            return False
        return True

    def _build_detail_dataframes(self) -> OrderedDict[str, "pd.DataFrame"]:
        """Build a detail dataframe for each lines of the master table."""
        # Iterate over the detail tables by changing the selection of the master table at
        # each iteration
        detail_tables_df = OrderedDict[str, pd.DataFrame]()
        initial_selected_rows = self._master_items.get_selected_rows()
        for detail_table_df in self._detail_items.converter().iter_dataframes():
            nb_rows = self._detail_items.get_nb_rows()
            # if the detail table is empty it is ignored
            if nb_rows > 0:
                # The iteration by the converter manage the update of the selection
                # Only one selected row should be used
                selected_rows = self._master_items.get_selected_rows()
                assert len(selected_rows) == 1, "Can manage only one selected row"
                current_selected_row = selected_rows[0]
                if (
                    ExportTreeOptions.EXPORT_ONLY_SELECTION in self._export_options
                    and current_selected_row not in initial_selected_rows
                ):
                    # Ignore the rows not selected initally if the only selection option
                    # is choosed
                    continue
                # extraction of the data of the selected row of the master table
                # and duplication of the row to have the same number of rows of the current
                # detail table
                master_table_columns = self._master_items.get_exported_column_names()
                master_table_df = pd.DataFrame(
                    [
                        [
                            self._master_items.get_edit_data(selected_rows[0], column)
                            for column in self._master_items.get_exported_column_indices()
                        ]
                    ]
                    * nb_rows,
                    columns=master_table_columns,
                )
                # clean the detail table columns to avoid duplicates
                detail_table_columns: List[str] = []
                for detail_column in detail_table_df.columns:
                    cleaned_column = detail_column
                    if detail_column in master_table_columns:
                        cleaned_column += ".1"
                    detail_table_columns.append(cleaned_column)
                detail_table_df.columns = pd.Index(detail_table_columns)
                # concatenate the master and detail table
                # add to the list the concatenation by columns of the master table and
                # detail table
                detail_tables_df[self._detail_items.get_title()] = pd.concat(
                    [master_table_df, detail_table_df], axis=1, sort=False
                )
        return detail_tables_df

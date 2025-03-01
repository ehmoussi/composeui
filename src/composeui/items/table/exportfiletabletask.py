from composeui.commontypes import AnyTableItems
from composeui.core.tasks.abstracttask import AbstractTask
from composeui.items.core.views.iitemsview import FormatExtension

from pathlib import Path
from typing import Generic, Optional

try:
    import pandas as pd
except (ImportError, ModuleNotFoundError):
    _HAS_PANDAS = False
else:
    _HAS_PANDAS = True


class ExportFileTableTask(AbstractTask, Generic[AnyTableItems]):
    def __init__(
        self,
        items: AnyTableItems,
        filepath: Path,
        extension: FormatExtension,
    ) -> None:
        super().__init__(capture_exceptions_as_errors=False)
        self._items: AnyTableItems = items
        self._filepath = filepath
        self._extension = extension

    def _run(self) -> Optional[bool]:
        if not _HAS_PANDAS:
            raise ValueError("Can't export the table without pandas installed.")
        table_df = self._items.converter().to_dataframe()
        try:
            if self._extension == FormatExtension.CSV:
                table_df.to_csv(self._filepath, sep=";", index=False)
            elif self._extension == FormatExtension.EXCEL:
                sheet_name = self._items.get_title()
                if sheet_name == "":
                    sheet_name = "Table"
                with pd.ExcelWriter(self._filepath, engine="openpyxl") as writer:
                    table_df.to_excel(
                        writer, engine="openpyxl", sheet_name=sheet_name, index=False
                    )
            elif self._extension == FormatExtension.JSON:
                try:
                    table_df.to_json(self._filepath, orient="records", index=False)
                except ValueError:
                    self.error_message = (
                        f"The current version of pandas '{pd.__version__}' "
                        "is too old to export in json"
                    )
                    return False
            elif self._extension == FormatExtension.MARKDOWN:
                try:
                    table_df.to_markdown(self._filepath, index=False)
                except AttributeError:  # old versions of pandas can't manage filepath directly
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

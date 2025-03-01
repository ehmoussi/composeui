from composeui.commontypes import AnyTreeItems
from composeui.core.tasks.abstracttask import AbstractTask
from composeui.items.core.views.itemsview import FormatExtension
from composeui.items.tree.treeview import ExportTreeOptions

from pathlib import Path
from typing import Generic, List, Optional, Tuple

try:
    import pandas as pd
except (ImportError, ModuleNotFoundError):
    _HAS_PANDAS = False
else:
    _HAS_PANDAS = True


class ExportFileTreeTask(AbstractTask, Generic[AnyTreeItems]):
    def __init__(
        self,
        items: AnyTreeItems,
        selected_positions: List[Tuple[int, ...]],
        filepath: Path,
        extension: FormatExtension,
        export_options: ExportTreeOptions,
    ) -> None:
        super().__init__(capture_exceptions_as_errors=True)
        self._items: AnyTreeItems = items
        self._selected_positions = selected_positions
        self._filepath = filepath
        self._extension = extension
        self._export_options = export_options

    def _run(self) -> Optional[bool]:
        if not _HAS_PANDAS:
            raise ValueError("Can't export the tree without pandas installed.")
        if len(self._selected_positions) > 0:
            index_most_upper_item = min(
                range(len(self._selected_positions)),
                key=lambda index: len(self._selected_positions[index]),
            )
            position = self._selected_positions[index_most_upper_item]
            if self._items.get_nb_rows(position) == 0:
                position = position[:-1]
        else:
            position = ()
        try:
            if self._extension == FormatExtension.EXCEL:
                is_ok = True
                with pd.ExcelWriter(self._filepath, mode="w") as f:
                    if (
                        len(position) < self._items.depth
                        and ExportTreeOptions.USE_PARENT_SHEET_NAMES in self._export_options
                    ):
                        for row in range(self._items.get_nb_rows(position)):
                            is_ok &= self._export((*position, row), writer=f)
                    else:
                        is_ok = self._export(position, writer=f)
                return is_ok
            else:
                return self._export(position)
        except PermissionError:
            self.error_message = "Can't write into the file if it's already open elsewhere."
            return False

    def _export(
        self, position: Tuple[int, ...], *, writer: Optional["pd.ExcelWriter"] = None
    ) -> bool:
        table_df = self._items.converter().to_flatten_dataframe(position)
        if self._extension == FormatExtension.CSV:
            table_df.to_csv(self._filepath, sep=";", index=False)
        elif self._extension == FormatExtension.EXCEL:
            sheet_name = self._items.get_title(position)
            if sheet_name == "":
                sheet_name = "Tree"
            assert writer is not None, "The writer is mandatory for Excel"
            table_df.to_excel(writer, sheet_name=sheet_name, index=False)
        elif self._extension == FormatExtension.JSON:
            try:
                # TODO: Maybe not using pandas for the tree to keep the hierarchy ?
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
        return True

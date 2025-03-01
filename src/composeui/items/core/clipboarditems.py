from composeui.commontypes import AnyModel
from composeui.items.core.tabletotreeitems import TableToTreeItems
from composeui.items.table.abstracttableitems import AbstractTableItems
from composeui.items.tree.abstracttreeitems import AbstractTreeItems

import pyperclip

import contextlib
import csv
import io
from typing import Any, List, Optional, Tuple, Type, Union

HAS_PANDAS = False
try:
    import pandas as pd
except (ImportError, ModuleNotFoundError):
    HAS_PANDAS = False
else:
    HAS_PANDAS = True

if HAS_PANDAS:
    ClipboardException: Type[Exception]
    try:
        from pandas.errors import PyperclipException

        ClipboardException = PyperclipException
    except ImportError:
        ClipboardException = Exception


class ClipboardItems:
    def __init__(
        self,
        items: Optional[
            Union[AbstractTableItems[AnyModel], AbstractTreeItems[AnyModel]]
        ] = None,
    ) -> None:
        self._items: Optional[AbstractTreeItems[AnyModel]] = None
        if isinstance(items, AbstractTableItems):
            self._items = TableToTreeItems(items)
        else:
            self._items = items
        self._data: List[List[Any]] = []

    @property
    def shape(self) -> Tuple[int, int]:
        return len(self._data), len(self._data[0]) if len(self._data) > 0 else 0

    @property
    def data(self) -> List[List[Any]]:
        return self._data

    def write_selection(self) -> None:
        """Write the selected items data to the clipboard."""
        if self._items is None:
            raise ValueError("No items available")
        selected_items = self._items.get_selected_items()
        data = (
            [
                str(self._items.get_edit_data(row, column, tuple(parent_rows)))
                for column in sorted(selected_items[(*parent_rows, row)])
            ]
            for (*parent_rows, row) in sorted(
                selected_items, key=lambda rows: (len(rows), *rows)
            )
        )
        if HAS_PANDAS:
            with contextlib.suppress(ClipboardException):
                pd.DataFrame(data).to_clipboard(sep="\t", header=None, index=False)
        else:
            csv_io = io.StringIO()
            writer = csv.writer(csv_io, delimiter="\t", quoting=csv.QUOTE_NONNUMERIC)
            writer.writerows(data)
            pyperclip.copy(csv_io.getvalue())

    def read_clipboard(self) -> None:
        """Read the current clipboard data."""
        self._data.clear()
        if HAS_PANDAS:
            self._data = (
                pd.read_clipboard(header=None, sep="\t")
                .replace({float("nan"): None})
                .to_numpy()
                .tolist()  # type: ignore[assignment, unused-ignore]
                # TODO: the assignment is a bug with mypy in python 3.10, 3.11 works
            )
        else:
            csv_io = io.StringIO(newline="")
            csv_io.write(pyperclip.paste())
            csv_io.seek(0)
            self._data = list(csv.reader(csv_io, delimiter="\t", quoting=csv.QUOTE_NONNUMERIC))
            nb_columns = max(map(len, self._data))
            for i in range(len(self._data)):
                if len(self._data[i]) < nb_columns:
                    self._data[i].extend([None] * (nb_columns - len(self._data[i])))

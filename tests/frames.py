"""Layouts with and without a title for the frame tests."""

from __future__ import annotations

from pathlib import Path

from composeui.core.view import (
    Frame,
    MainView,
    PageWidth,
    T,
    child,
    define_view,
)
from tests.grid import TablesGrid
from tests.horizontal import TablesRow
from tests.vertical import TableAndButtonColumn


@define_view
class FramedMainView(MainView):
    extension = ".frames"
    translations_dir = Path(__file__).parent / "locales"
    width = PageWidth.WIDE

    row: TablesRow = child(TablesRow, frame=Frame(title=T("Shape")))
    grid: TablesGrid = child(TablesGrid, frame=Frame())
    column: TableAndButtonColumn = child(
        TableAndButtonColumn, frame=Frame(title="<layout-title> & controls")
    )

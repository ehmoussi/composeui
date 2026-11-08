"""Views in a grid's cells, shared by the backend tests of `GridView`."""

from __future__ import annotations

import attrs

from composeui.core.view import (
    ButtonView,
    GridPosition,
    GridView,
    MainView,
    TableView,
    define_view,
    grid_cell,
)


@define_view
class TablesGrid(GridView):
    # taller than the button beside it, so the next row starts below the table
    first: TableView = grid_cell(
        (0, 0), TableView, headers=["First"], rows=[["North"], ["South"], ["East"]]
    )
    # its cell stays empty: the button doesn't move into it
    hidden: TableView = grid_cell((0, 1), TableView, headers=["Hidden"], is_visible=False)
    button: ButtonView = grid_cell((0, 2), ButtonView, text="Add")
    spanning: TableView = grid_cell(
        GridPosition(1, 0, column_span=3), TableView, headers=["Spanning"]
    )


@define_view
class GridMainView(MainView):
    app_title = "In a grid"
    extension = ".grid"

    tables: TablesGrid = attrs.Factory(TablesGrid)

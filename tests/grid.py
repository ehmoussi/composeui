"""Views in a grid's cells, shared by the backend tests of `GridView`."""

import attrs

from composeui.core.view import (
    GRID_POSITION,
    ButtonView,
    GridPosition,
    GridView,
    MainView,
    TableView,
    define_view,
)


@define_view
class TablesGrid(GridView):
    first: TableView = attrs.field(factory=TableView, metadata={GRID_POSITION: (0, 0)})
    # its cell stays empty: the button doesn't move into it
    hidden: TableView = attrs.field(factory=TableView, metadata={GRID_POSITION: (0, 1)})
    button: ButtonView = attrs.field(factory=ButtonView, metadata={GRID_POSITION: (0, 2)})
    spanning: TableView = attrs.field(
        factory=TableView, metadata={GRID_POSITION: GridPosition(1, 0, column_span=3)}
    )

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.first.headers = ["First"]
        # taller than the button beside it, so the next row starts below the table
        self.first.rows = [["North"], ["South"], ["East"]]
        self.hidden.headers = ["Hidden"]
        self.hidden.is_visible = False
        self.button.text = "Add"
        self.spanning.headers = ["Spanning"]


@define_view
class GridMainView(MainView):
    app_title = "In a grid"
    extension = ".grid"

    tables: TablesGrid = attrs.Factory(TablesGrid)

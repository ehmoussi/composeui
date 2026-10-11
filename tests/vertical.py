"""A table above its button, shared by the backend tests of `VerticalView`."""

import attrs
from attrs import Factory

from composeui.core.view import (
    ButtonView,
    HorizontalView,
    MainView,
    TableView,
    VerticalView,
    define_view,
)


@define_view
class TableAndButtonColumn(VerticalView):
    table: TableView = attrs.field(factory=TableView)
    button: ButtonView = attrs.field(factory=ButtonView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.table.headers = ["Short"]
        self.button.text = "Add"


@define_view
class ColumnAndTableRow(HorizontalView):
    column: TableAndButtonColumn = Factory(TableAndButtonColumn)
    tall: TableView = attrs.field(factory=TableView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.tall.headers = ["Tall"]
        # taller than the column's views, so the column has height to spare
        self.tall.rows = [[str(i)] for i in range(20)]


@define_view
class VerticalMainView(MainView):
    tables: ColumnAndTableRow = Factory(ColumnAndTableRow)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self._init_app_info(title="One above the other", extension=".above")

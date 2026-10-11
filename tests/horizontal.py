"""Tables side by side, shared by the backend tests of `HorizontalView`."""

import attrs
from attrs import Factory

from composeui.core.view import STRETCH, HorizontalView, MainView, TableView, define_view


@define_view
class TablesRow(HorizontalView):
    narrow: TableView = attrs.field(factory=TableView)  # the default share, 1
    wide: TableView = attrs.field(factory=TableView, metadata={STRETCH: 3})
    hidden: TableView = attrs.field(factory=TableView, metadata={STRETCH: 2})

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.narrow.headers = ["Narrow"]
        self.wide.headers = ["Wide"]
        self.hidden.headers = ["Hidden"]
        # takes no share of the row
        self.hidden.is_visible = False


@define_view
class HorizontalMainView(MainView):
    tables: TablesRow = Factory(TablesRow)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self._init_app_info(title="Side by side", extension=".side")

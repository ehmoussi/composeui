"""Rows of views side by side, shared by the backend tests of `HorizontalView`."""

import attrs
from attrs import Factory

from composeui.core.view import (
    STRETCH,
    Align,
    ButtonView,
    HorizontalView,
    MainView,
    TableView,
    define_view,
)


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


@define_view
class StartButtons(HorizontalView):
    """Buttons, as wide as their text by default, packed at the row's start (the default)."""

    first: ButtonView = Factory(ButtonView)
    second: ButtonView = Factory(ButtonView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.first.text = "Add"
        self.second.text = "Remove"


@define_view
class EndButtons(StartButtons):
    align = Align.END

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.first.text = "Cancel"
        self.second.text = "Save"


@define_view
class ButtonsMainView(MainView):
    start: StartButtons = Factory(StartButtons)
    end: EndButtons = Factory(EndButtons)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self._init_app_info(title="Buttons", extension=".buttons")

"""Rows of views side by side, shared by the backend tests of `HorizontalView` and of tables."""

from __future__ import annotations

import attrs
from attrs import Factory
from typing_extensions import override

from composeui.core.view import (
    STRETCH,
    Align,
    ButtonView,
    HorizontalView,
    LabelView,
    MainView,
    TableView,
    define_view,
)


@define_view
class TablesRow(HorizontalView):
    narrow: TableView = attrs.field(factory=TableView)  # the default share, 1
    wide: TableView = attrs.field(factory=TableView, metadata={STRETCH: 3})
    hidden: TableView = attrs.field(factory=TableView, metadata={STRETCH: 2})

    @override
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.narrow.headers = ["Narrow"]
        self.narrow.rows = [["North"], ["South"], ["East"]]
        self.wide.headers = ["Wide"]
        self.hidden.headers = ["Hidden"]
        # takes no share of the row
        self.hidden.is_visible = False


@define_view
class HorizontalMainView(MainView):
    app_title = "Side by side"
    extension = ".side"

    tables: TablesRow = Factory(TablesRow)


@define_view
class StartButtons(HorizontalView):
    """Buttons, as wide as their text by default, packed at the row's start (the default)."""

    first: ButtonView = Factory(ButtonView)
    second: ButtonView = Factory(ButtonView)

    @override
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.first.text = "Add"
        self.second.text = "Remove"


@define_view
class EndButtons(StartButtons):
    align = Align.END

    @override
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.first.text = "Cancel"
        self.second.text = "Save"


@define_view
class EndButtonsBesideHiddenTable(EndButtons):
    """Buttons packed at the end while the view taking the row's free width is hidden."""

    table: TableView = Factory(TableView)

    @override
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.first.text = "Close"
        self.second.text = "Apply"
        self.table.is_visible = False


@define_view
class ButtonsMainView(MainView):
    app_title = "Buttons"
    extension = ".buttons"

    start: StartButtons = Factory(StartButtons)
    end: EndButtons = Factory(EndButtons)
    beside_hidden: EndButtonsBesideHiddenTable = Factory(EndButtonsBesideHiddenTable)


@define_view
class ManyStartButtons(HorizontalView):
    """More buttons than a narrow page has room for on one line."""

    run: ButtonView = Factory(ButtonView)
    stop: ButtonView = Factory(ButtonView)
    reload: ButtonView = Factory(ButtonView)
    preview: ButtonView = Factory(ButtonView)
    profiles: ButtonView = Factory(ButtonView)
    export: ButtonView = Factory(ButtonView)
    open_folder: ButtonView = Factory(ButtonView)
    help: ButtonView = Factory(ButtonView)

    @override
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        for button, text in zip(self.buttons, _MANY_TEXTS):
            button.text = text

    @property
    def buttons(self) -> list[ButtonView]:
        return [view for view, _ in self.stretched_views if isinstance(view, ButtonView)]


_MANY_TEXTS = ("Run", "Stop", "Reload", "Preview", "Profiles", "Export", "Open folder", "Help")


@define_view
class ManyEndButtons(ManyStartButtons):
    align = Align.END


@define_view
class ButtonsBesideLabel(HorizontalView):
    """A label taking the row's free width, beside buttons keeping their own."""

    label: LabelView = Factory(LabelView)
    buttons: ManyStartButtons = attrs.field(factory=ManyStartButtons, metadata={STRETCH: 0})

    @override
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.label.text = "Actions"


@define_view
class NoteBesideButton(HorizontalView):
    """A note longer than its row, keeping its own width as the button beside it does."""

    note: LabelView = attrs.field(factory=LabelView, metadata={STRETCH: 0})
    retry: ButtonView = Factory(ButtonView)

    @override
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.note.text = " ".join(["A status note longer than its row."] * 8)
        self.retry.text = "Retry"


@define_view
class ManyButtonsMainView(MainView):
    app_title = "Many buttons"
    extension = ".many"
    # for the window to be narrower than its rows of buttons
    minimum_width: int = 300

    start: ManyStartButtons = Factory(ManyStartButtons)
    end: ManyEndButtons = Factory(ManyEndButtons)
    beside: ButtonsBesideLabel = Factory(ButtonsBesideLabel)
    noted: NoteBesideButton = Factory(NoteBesideButton)
    below: LabelView = Factory(LabelView)

    @override
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.below.text = "Below the buttons"

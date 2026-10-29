"""Form rows outside a form, shared by the backend tests of the layouts holding them."""

from __future__ import annotations

from typing import TYPE_CHECKING

from composeui.core.view import (
    LabelRowInputView,
    LabelRowSliderView,
    ListView,
    MainView,
    RowInputView,
    SidebarView,
    VerticalView,
    child,
    define_view,
)

if TYPE_CHECKING:
    from composeui.core.view import View


@define_view
class FiltersSidebar(SidebarView):
    hour: LabelRowSliderView = child(LabelRowSliderView, label="Hour", maximum=23, value=11)


@define_view
class NameColumn(VerticalView):
    name: LabelRowInputView = child(LabelRowInputView, label="Name")


@define_view
class NameRows(ListView[str]):
    """A row per name, its label the name."""

    def build_item(self, item: str) -> View:
        return LabelRowInputView(label=item)


@define_view
class LoneRowsMainView(MainView):
    app_title = "Lone rows"
    has_file_menu = False

    sidebar: FiltersSidebar = child(FiltersSidebar, title="Filters")
    column: NameColumn = child(NameColumn)
    #: a row without a label, straight in the main view
    note: RowInputView = child(RowInputView)
    names: NameRows = child(NameRows)

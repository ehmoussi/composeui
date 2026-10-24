"""Views holding one Qt shows no widget for: an app's own view a backend lacks, an action."""

from __future__ import annotations

import attrs
from attrs import Factory

from composeui.core.view import (
    GRID_POSITION,
    ActionView,
    ExpanderView,
    FormRowView,
    FormView,
    GridView,
    HorizontalView,
    LabelView,
    ListView,
    MainView,
    Menu,
    PageView,
    RowInputView,
    SplitterView,
    ToolBar,
    VerticalView,
    View,
    define_view,
)


@define_view
class UnregisteredView(View):
    """A view under a key no backend registers."""

    _renderer_key = "unregistered"


@define_view
class PartialRow(HorizontalView):
    shown: LabelView = Factory(LabelView)
    skipped: UnregisteredView = Factory(UnregisteredView)


@define_view
class PartialColumn(VerticalView):
    shown: LabelView = Factory(LabelView)
    skipped: UnregisteredView = Factory(UnregisteredView)


@define_view
class PartialGrid(GridView):
    shown: LabelView = attrs.field(factory=LabelView, metadata={GRID_POSITION: (0, 0)})
    skipped: UnregisteredView = attrs.field(
        factory=UnregisteredView, metadata={GRID_POSITION: (0, 1)}
    )


@define_view
class PartialSplitter(SplitterView):
    shown: LabelView = Factory(LabelView)
    skipped: UnregisteredView = Factory(UnregisteredView)


@define_view
class PartialExpander(ExpanderView):
    shown: LabelView = Factory(LabelView)
    skipped: UnregisteredView = Factory(UnregisteredView)


@define_view
class PartialPage(PageView):
    shown: LabelView = Factory(LabelView)
    skipped: UnregisteredView = Factory(UnregisteredView)


@define_view
class PartialMenu(Menu):
    shown: ActionView = Factory(ActionView)
    skipped: UnregisteredView = Factory(UnregisteredView)


@define_view
class PartialToolBar(ToolBar):
    shown: ActionView = Factory(ActionView)
    skipped: UnregisteredView = Factory(UnregisteredView)


@define_view
class UnregisteredRowView(FormRowView):
    """A form row whose field no backend registers."""

    _field_renderer_key = "unregistered"


@define_view
class PartialForm(FormView):
    shown: RowInputView = Factory(RowInputView)
    skipped: UnregisteredRowView = Factory(UnregisteredRowView)


@define_view
class PartialMainView(MainView):
    app_title = "Partial"
    extension = ".partial"

    menu: PartialMenu = Factory(PartialMenu)
    toolbar: PartialToolBar = Factory(PartialToolBar)
    row: PartialRow = Factory(PartialRow)
    column: PartialColumn = Factory(PartialColumn)
    grid: PartialGrid = Factory(PartialGrid)
    splitter: PartialSplitter = Factory(PartialSplitter)
    expander: PartialExpander = Factory(PartialExpander)
    page: PartialPage = Factory(PartialPage)
    form: PartialForm = Factory(PartialForm)
    items: ListView = Factory(ListView)
    shown: LabelView = Factory(LabelView)
    skipped: UnregisteredView = Factory(UnregisteredView)
    #: outside a menu and a toolbar: no QAction, and no place in the window
    action: ActionView = Factory(ActionView)

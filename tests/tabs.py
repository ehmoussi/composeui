"""A pipe's details in tabs, shared by the backend tests of `TabView`."""

from __future__ import annotations

import attrs

from composeui.core.view import (
    ButtonView,
    LabelView,
    MainView,
    TabPage,
    TabView,
    child,
    define_view,
)


@define_view
class DetailsTab(TabPage):
    length: LabelView = child(LabelView, text="Length: 12 m")
    edit: ButtonView = child(ButtonView, text="Edit")


@define_view
class HistoryTab(TabPage):
    created: LabelView = child(LabelView, text="Created on Monday")


@define_view
class NotesTab(TabPage):
    note: LabelView = child(LabelView, text="Insulated in 2024")


@define_view
class PipeTabs(TabView):
    details: DetailsTab = child(DetailsTab, title="Details")
    history: HistoryTab = child(HistoryTab, title="History")
    notes: NotesTab = child(NotesTab, title="Notes")


@define_view
class TabsMainView(MainView):
    app_title = "Pipe"
    extension = ".pipe"

    tabs: PipeTabs = attrs.Factory(PipeTabs)

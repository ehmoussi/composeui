"""A record's details, shared by the backend tests of `ExpanderView`."""

from __future__ import annotations

from attrs import Factory

from composeui.core.view import (
    Align,
    ButtonVariant,
    ButtonView,
    ExpanderView,
    HorizontalView,
    LabelView,
    MainView,
    child,
    define_view,
)


@define_view
class RecordButtons(HorizontalView):
    align = Align.END
    edit: ButtonView = child(ButtonView, text="Edit")
    delete: ButtonView = child(ButtonView, text="Delete", variant=ButtonVariant.DANGER)


@define_view
class HistoryExpander(ExpanderView):
    created: LabelView = child(LabelView, text="Created on Monday")


@define_view
class RecordExpander(ExpanderView):
    length: LabelView = child(LabelView, text="Length: 12 m")
    #: an expander in an expander: its toggles are its own
    history: HistoryExpander = child(HistoryExpander, title="History")
    buttons: RecordButtons = Factory(RecordButtons)


@define_view
class RecordMainView(MainView):
    app_title = "Records"
    extension = ".records"

    record: RecordExpander = child(RecordExpander, title="Pipe A")

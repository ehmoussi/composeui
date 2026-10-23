"""Views whose texts look like markup, shared by the Qt and Textual tests of plain text.

Qt reads a text with tags as HTML, and Textual one with square brackets as its own
markup: both must show these texts as they are.
"""

from __future__ import annotations

from composeui.core.view import (
    ButtonView,
    CheckBoxView,
    ComboboxView,
    DialogView,
    FormView,
    LabelRowInputView,
    LabelView,
    MainView,
    MarkdownView,
    TableView,
    child,
    define_view,
)

#: HTML, a tag Qt doesn't know, and Textual's markup: a tag closing nothing, an action
MARKUP = "<b>bold</b> <none> [b]bold[/b] [/] [@click=app.quit]quit[/]"


@define_view
class NameForm(FormView):
    name: LabelRowInputView = child(LabelRowInputView, label=MARKUP, help=MARKUP)


@define_view
class MarkupMainView(MainView):
    note: LabelView = child(LabelView, text=MARKUP)
    run: ButtonView = child(ButtonView, text=MARKUP)
    keep: CheckBoxView = child(CheckBoxView, text=MARKUP)
    size: ComboboxView[int] = child(ComboboxView, values={MARKUP: 1}, value=1)
    form: NameForm = child(NameForm)
    help: MarkdownView = child(MarkdownView, text=MARKUP)
    notes: TableView = child(TableView, headers=[MARKUP], rows=[[MARKUP]], filterable_columns=[0])
    warning: DialogView = child(DialogView, title=MARKUP, text=MARKUP)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.notes.filters = {0: "=" + MARKUP}  # its chip shows the text typed
        self.status_bar.message = MARKUP

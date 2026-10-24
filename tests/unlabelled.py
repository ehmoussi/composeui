"""A form row without a label, shared by the backend tests of forms."""

from __future__ import annotations

from attrs import Factory

from composeui.core.view import FormView, MainView, RowInputView, child, define_view


@define_view
class NoteForm(FormView):
    note: RowInputView = child(RowInputView, placeholder="A note")


@define_view
class NoteMainView(MainView):
    app_title = "Note"
    extension = ".note"

    form: NoteForm = Factory(NoteForm)

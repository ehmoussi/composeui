"""An opening hour, shared by the backend tests of `IntInputView`."""

from __future__ import annotations

from attrs import Factory

from composeui.core.view import FormView, LabelRowIntInputView, MainView, child, define_view


@define_view
class HoursForm(FormView):
    opening: LabelRowIntInputView = child(
        LabelRowIntInputView, label="Opening hour", minimum=0, maximum=23, value=8
    )


@define_view
class HoursMainView(MainView):
    app_title = "Hours"
    extension = ".hours"

    form: HoursForm = Factory(HoursForm)

"""A number of workers, shared by the backend tests of `SliderView`."""

from __future__ import annotations

from attrs import Factory

from composeui.core.view import (
    FormView,
    LabelRowIntInputView,
    LabelRowSliderView,
    MainView,
    child,
    define_view,
)


@define_view
class WorkersForm(FormView):
    # steps 2, 5, 8, 11 and 14: the last falls short of 16
    workers: LabelRowSliderView = child(
        LabelRowSliderView, label="Workers", minimum=2, maximum=16, step=3, value=5
    )
    #: a text field, for the slider's row to match
    retries: LabelRowIntInputView = child(LabelRowIntInputView, label="Retries", value=1)


@define_view
class WorkersMainView(MainView):
    app_title = "Workers"
    extension = ".workers"

    form: WorkersForm = Factory(WorkersForm)

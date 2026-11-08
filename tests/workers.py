"""Forms shared by the backend tests of `SliderView` and `FloatSliderView`."""

from __future__ import annotations

from attrs import Factory

from composeui.core.view import (
    FormView,
    LabelRowFloatSliderView,
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


@define_view
class OpacityForm(FormView):
    # steps 0.0, 0.1, 0.2 and 0.3: in floats, 0.3 // 0.1 is 2.0, and 3 * 0.1 isn't 0.3
    opacity: LabelRowFloatSliderView = child(
        LabelRowFloatSliderView, label="Opacity", maximum=0.3, step=0.1, value=0.1
    )


@define_view
class OpacityMainView(MainView):
    app_title = "Opacity"
    extension = ".opacity"

    form: OpacityForm = Factory(OpacityForm)

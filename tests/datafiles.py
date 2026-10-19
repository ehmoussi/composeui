"""A measurements file to read, shared by the backend tests of `FilePathInputView`."""

from __future__ import annotations

from attrs import Factory

from composeui.core.view import FormView, LabelRowFilePathInputView, MainView, child, define_view


@define_view
class DataFileForm(FormView):
    measurements: LabelRowFilePathInputView = child(
        LabelRowFilePathInputView,
        label="Measurements",
        extensions={"CSV": (".csv",), "Text": (".txt", ".text")},
        has_reload=True,
    )


@define_view
class DataFileMainView(MainView):
    app_title = "Measurements"
    extension = ".measurements"

    form: DataFileForm = Factory(DataFileForm)

"""A measurements file to read, shared by the backend tests of file fields."""

from __future__ import annotations

from attrs import Factory

from composeui.core.view import (
    FormView,
    LabelRowFilePathInputView,
    LabelRowFileUploadView,
    MainView,
    child,
    define_view,
)


@define_view
class DataFileForm(FormView):
    measurements: LabelRowFilePathInputView = child(
        LabelRowFilePathInputView,
        label="Measurements",
        extensions={"CSV": (".csv",), "Text": (".txt", ".text")},
        has_reload=True,
    )
    dataset: LabelRowFileUploadView = child(
        LabelRowFileUploadView, label="Dataset", extensions={"CSV": (".csv",)}
    )
    #: a shapefile's files, which name each other: given together
    shapes: LabelRowFileUploadView = child(
        LabelRowFileUploadView,
        label="Shapes",
        extensions={"Shapefile": (".shp", ".shx", ".dbf")},
        multiple=True,
    )


@define_view
class DataFileMainView(MainView):
    app_title = "Measurements"
    extension = ".measurements"

    form: DataFileForm = Factory(DataFileForm)

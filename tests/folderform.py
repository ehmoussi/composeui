"""A dialog's form listing a folder, shared by the backend tests of a form's other views."""

from __future__ import annotations

from pathlib import PurePosixPath

import attrs

from composeui.core.view import (
    ButtonView,
    FormView,
    HorizontalView,
    LabelRowInputView,
    MainView,
    TableView,
    TypedFormDialogView,
    child,
    define_view,
)


@define_view
class FolderButtons(HorizontalView):
    up: ButtonView = child(ButtonView, text="Parent folder")


@define_view
class FolderForm(FormView):
    """Its rows, a row of buttons and a table: one form, every view shown."""

    folder: LabelRowInputView = child(LabelRowInputView, label="Folder", text="/studies/beam")
    buttons: FolderButtons = attrs.Factory(FolderButtons)
    entries: TableView = child(TableView, headers=["Name"], rows=[["beam.export"]])

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.buttons.up.clicked.connect(self._go_up)

    def _go_up(self) -> None:
        folder = PurePosixPath(self.folder.text)
        self.folder.text = str(folder.parent)
        self.entries.rows = [[folder.name]]


@define_view
class OpenStudyDialog(TypedFormDialogView[FolderForm]):
    form: FolderForm = attrs.Factory(FolderForm)


@define_view
class StudyMainView(MainView):
    app_title = "Study"
    extension = ".study"

    open: ButtonView = child(ButtonView, text="Open")
    open_dialog: OpenStudyDialog = child(OpenStudyDialog, title="Open a study")

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.open.clicked.connect(self.open_dialog.open)

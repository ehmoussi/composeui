"""A study picked in a folder's dialog, shared by the tests of `ContentDialogView`."""

from __future__ import annotations

from pathlib import PurePosixPath

import attrs

from composeui.core.view import (
    ButtonView,
    ContentDialogView,
    LabelView,
    MainView,
    TableView,
    VerticalView,
    child,
    define_view,
)

#: the names in each folder; a name that is a folder too has its own entry
FOLDERS = {"/studies": ["beam", "notes.txt"], "/studies/beam": ["beam.export"]}


@define_view
class FolderView(VerticalView):
    folder: LabelView = attrs.Factory(LabelView)
    up: ButtonView = child(ButtonView, text="Parent folder")
    entries: TableView = child(TableView, headers=["Name"])


@define_view
class OpenStudyDialog(ContentDialogView[FolderView]):
    """Open on a folder shows it, the dialog left open; Open on a study closes it."""

    content: FolderView = attrs.Factory(FolderView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.title = "Open a study"
        self.accept_text = "Open"
        self.content.up.clicked.connect(self._go_up)
        self.content.entries.selection_changed.connect(self._follow_selection)
        self.show("/studies/beam")

    def show(self, folder: str) -> None:
        self.content.folder.text = folder
        self.content.entries.rows = [[name] for name in FOLDERS[folder]]
        self.content.entries.selected_rows = []
        self.is_accept_enabled = False

    @property
    def selected(self) -> str:
        (row,) = self.content.entries.selected_rows
        return str(PurePosixPath(self.content.folder.text) / self.content.entries.rows[row][0])

    def accept(self) -> None:
        if self.is_accept_enabled and self.selected in FOLDERS:
            self.show(self.selected)
            return
        super().accept()

    def _go_up(self) -> None:
        self.show(str(PurePosixPath(self.content.folder.text).parent))

    def _follow_selection(self, rows: list[int]) -> None:
        self.is_accept_enabled = len(rows) == 1


@define_view
class StudyDialogMainView(MainView):
    app_title = "Study"
    extension = ".study"

    open: ButtonView = child(ButtonView, text="Open")
    study: LabelView = child(LabelView, text="No study")
    open_dialog: OpenStudyDialog = attrs.Factory(OpenStudyDialog)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.open.clicked.connect(self.open_dialog.open)
        self.open_dialog.accepted.connect(self._open_study)

    def _open_study(self) -> None:
        self.study.text = self.open_dialog.selected

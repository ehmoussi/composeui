"""A study picked among the server's files, shared by the backend tests of `server_roots`."""

from __future__ import annotations

from pathlib import Path

from attrs import Factory

from composeui.core.view import (
    CellWidget,
    LabelRowFilePathInputView,
    LabelRowFolderPathInputView,
    MainView,
    TableView,
    child,
    define_view,
)


@define_view
class StudyFileMainView(MainView):
    """Its fields list the files and folders of this folder, until a test gives them roots.

    `scratch` has none: on the web, its folder is typed.
    """

    app_title = "Study file"
    extension = ".studyfile"

    study: LabelRowFilePathInputView = child(
        LabelRowFilePathInputView,
        label="Study",
        extensions={"Python": (".py",)},
        server_roots=(Path(__file__).parent,),
    )
    results: LabelRowFolderPathInputView = child(
        LabelRowFolderPathInputView, label="Results", server_roots=(Path(__file__).parent,)
    )
    scratch: LabelRowFolderPathInputView = child(LabelRowFolderPathInputView, label="Scratch")


@define_view
class StudyFilesTableMainView(MainView):
    """A study's input files, each picked in its row among the files of this folder.

    Until a test gives the column roots of its own.
    """

    app_title = "Study files"
    extension = ".studyfiles"

    inputs: TableView = Factory(TableView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.inputs.headers = ["Input", "File"]
        self.inputs.rows = [["Mesh", ""], ["Commands", ""]]
        self.inputs.editable_columns = [1]
        self.inputs.cell_widgets = {
            1: CellWidget.file_path({"Python": (".py",)}, server_roots=(Path(__file__).parent,))
        }

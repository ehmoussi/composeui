"""A study's paths, shared by the backend tests of `server_roots` and of `cell_widget`."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Optional

from attrs import Factory

from composeui.core.view import (
    CellWidget,
    LabelRowFilePathInputView,
    LabelRowFolderPathInputView,
    LabelRowSavePathInputView,
    MainView,
    TableView,
    child,
    define_view,
)

if TYPE_CHECKING:
    from collections.abc import Iterable


@define_view
class StudyFileMainView(MainView):
    """Its fields list the files and folders of this folder, until a test gives them roots.

    `scratch` has none: on the web, its folder is typed. `report` saves a `.py` file.
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
    report: LabelRowSavePathInputView = child(
        LabelRowSavePathInputView,
        label="Report",
        extensions={"Python": (".py",)},
        server_roots=(Path(__file__).parent,),
    )


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


@define_view
class StudyPathsTableView(TableView):
    """A study's inputs, each a file or a folder, which the table's cells don't show."""

    _folders: tuple[int, ...] = ()
    _roots: tuple[Path, ...] = ()

    def show_paths(
        self, rows: list[list[str]], folders: Iterable[int], roots: Iterable[Path] = ()
    ) -> None:
        """Show `rows`, the paths of `folders` picking a folder, in `roots` if any."""
        self._folders, self._roots = tuple(folders), tuple(roots)
        self.rows = rows

    def cell_widget(self, row: int, column: int) -> Optional[CellWidget]:
        if column != 1:
            return None
        if row in self._folders:
            return CellWidget.folder_path(server_roots=self._roots)
        return CellWidget.file_path(server_roots=self._roots)


@define_view
class StudyPathsMainView(MainView):
    """Two inputs named alike, one a file, the other a folder: their kind isn't a cell's."""

    app_title = "Study paths"
    extension = ".studypaths"

    inputs: StudyPathsTableView = Factory(StudyPathsTableView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.inputs.headers = ["Input", "Path"]
        self.inputs.editable_columns = [1]
        self.inputs.show_paths([["Mesh", ""], ["Mesh", ""]], folders=[1])

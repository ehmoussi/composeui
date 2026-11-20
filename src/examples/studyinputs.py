"""A study's files: `python -m examples.studyinputs --study FOLDER --backend qt`.

`--study` is the app's own option: the study's folder, the current one by default. Each
row of the table is a file or a folder of the study, and its kind, picked in a combobox,
says what the "…" button of its path picks: a file to read, a folder, or a file to write,
which may not exist yet. Changing the kind changes the button. The paths are relative to
the study's folder, whatever folder the app started in, and the line under the table shows
where the selected row's path leads. On the web, the "…" button lists the study's folder.

"Save summary" writes the table's rows to the text file of the field beside it. Over a file
that exists, it asks first, unless the user already agreed in the field's "…" picker.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import TYPE_CHECKING

from attrs import Factory
from typing_extensions import override

from composeui.core.application import run
from composeui.core.view import (
    ButtonView,
    CellWidget,
    HorizontalView,
    LabelView,
    MainView,
    SavePathInputView,
    T,
    TableView,
    child,
    define_view,
)

if TYPE_CHECKING:
    import argparse

#: the kinds of the study's files, as the Kind column shows them
INPUT_FILE, INPUT_FOLDER, OUTPUT_FILE, OUTPUT_FOLDER = (
    "Input file",
    "Input folder",
    "Output file",
    "Output folder",
)
KIND, PATH = 1, 2


def path_widget(study: Path) -> CellWidget:
    """Get the Path column's widget: by the row's kind, from the study's folder."""
    roots = (study,)
    return CellWidget.path_by(
        KIND,
        {
            INPUT_FILE: CellWidget.file_path(server_roots=roots),
            INPUT_FOLDER: CellWidget.folder_path(server_roots=roots),
            OUTPUT_FILE: CellWidget.save_path({"Text": (".txt",)}, server_roots=roots),
            OUTPUT_FOLDER: CellWidget.folder_path(server_roots=roots),
        },
        base_folder=study,
    )


@define_view
class SummaryRow(HorizontalView):
    """Where to save the summary of the table, and the button saving it."""

    file: SavePathInputView = child(SavePathInputView, extensions={"Text": (".txt",)})
    save: ButtonView = child(ButtonView, text=T("Save summary"))


def write_summary(path: Path, rows: list[list[str]]) -> None:
    """Write `rows` to the text file `path`: a line per row, its cells separated by tabs."""
    path.write_text("".join("\t".join(cells) + "\n" for cells in rows), encoding="utf-8")


@define_view
class StudyInputsMainView(MainView):
    app_title = T("Study Inputs")
    extension = ".studyinputs"

    files: TableView = child(
        TableView,
        headers=["Name", "Kind", "Path"],
        rows=[
            ["Mesh", INPUT_FILE, "inputs/mesh.med"],
            ["Materials", INPUT_FOLDER, "inputs/materials"],
            ["Report", OUTPUT_FILE, "report.txt"],
            ["Results", OUTPUT_FOLDER, "results"],
        ],
        editable_columns=[KIND, PATH],
        cell_widgets={
            KIND: CellWidget.combobox([INPUT_FILE, INPUT_FOLDER, OUTPUT_FILE, OUTPUT_FOLDER])
        },
    )
    resolved: LabelView = Factory(LabelView)
    summary: SummaryRow = Factory(SummaryRow)

    @override
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.show_study(Path.cwd())
        self.files.selection_changed.connect(self._show_resolved)
        self.files.cell_edited.connect(self._show_edited)
        self.resolved.text = self.tr("Select a row to see where its path leads.")
        self.summary.file.placeholder = self.tr("summary.txt")
        self.summary.save.clicked.connect(self.save_summary)

    @override
    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--study", type=Path, metavar="FOLDER", help="Read the paths from FOLDER."
        )

    @override
    def apply_arguments(self, args: argparse.Namespace) -> None:
        if args.study is not None:
            self.show_study(args.study)

    def show_study(self, study: Path) -> None:
        """Read the paths from the folder `study`, and list it on the web."""
        self.files.cell_widgets = {**self.files.cell_widgets, PATH: path_widget(study)}
        self.summary.file.base_folder = study
        self.summary.file.server_roots = (study,)
        self._show_resolved()

    def save_summary(self) -> None:
        """Write the rows shown now to the summary's file, asking first over a file that exists."""
        if self.summary.file.path is None:
            self.status_bar.show_message(self.tr("Type or pick where to save the summary."))
            return
        # the rows as the user sees them now: an answer that comes later writes these
        rows = [list(cells) for cells in self.files.rows]
        self.write_file(self.summary.file, functools.partial(self._write_summary, rows=rows))

    def _write_summary(self, path: Path, rows: list[list[str]]) -> None:
        try:
            write_summary(path, rows)
        except OSError as error:
            message = self.tr("Can't save {name}: {error}")
            self.status_bar.show_message(message.format(name=repr(path.name), error=error))
            return
        self.status_bar.show_message(self.tr("Saved {name}").format(name=path.name))

    def _show_edited(self, row: int, column: int, text: str) -> None:
        # emitted while `rows` holds the old text: the row as the edit leaves it
        cells = list(self.files.rows[row])
        cells[column] = text
        self._show_path(cells)

    def _show_resolved(self) -> None:
        if len(self.files.selected_rows) > 0:
            self._show_path(self.files.rows[self.files.selected_rows[0]])

    def _show_path(self, cells: list[str]) -> None:
        """Show where the path of the row `cells` leads, if its kind has a path."""
        widget = self.files.cell_widgets[PATH].for_row(cells)
        text = cells[PATH]
        if widget is None or text.strip() == "":
            self.resolved.text = ""
            return
        self.resolved.text = f"{text} → {widget.path(text)}"


def main() -> None:
    run(StudyInputsMainView)


if __name__ == "__main__":
    main()

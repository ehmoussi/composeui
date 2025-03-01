r"""File view."""

from composeui.core.qt.view import View
from composeui.mainview.interfaces.ifileview import IFileView

from qtpy.QtWidgets import QFileDialog, QWidget

from dataclasses import dataclass, field


@dataclass(eq=False)
class FileView(View, IFileView):
    r"""Display a modal view to select files or directories."""

    view: None = field(init=False, default=None)
    parent: QWidget

    def open_file(self) -> str:
        return str(
            QFileDialog.getOpenFileName(
                self.parent,
                "Open File",
                "",
                self.filter_path,
            )[0]
        )

    def save_file(self) -> str:
        return str(
            QFileDialog.getSaveFileName(
                self.parent,
                "Save File",
                "",
                self.filter_path,
            )[0]
        )

    def existing_directory(self) -> str:
        return str(
            QFileDialog.getExistingDirectory(
                self.parent,
                "Existing Directory",
                "",
            )
        )

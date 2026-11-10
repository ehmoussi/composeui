"""A main view giving its user a file it made, shared by the backends' tests of downloads."""

from __future__ import annotations

from pathlib import Path  # noqa: TC003 (attrs resolves the view's annotations)
from typing import Union

import attrs

from composeui.core.view import OMIT, ButtonView, MainView, define_view


@define_view
class ReportMainView(MainView):
    """Export gives the report, under a name that a folder comes before."""

    has_file_menu = False

    export: ButtonView = attrs.field(factory=lambda: ButtonView(text="Export"))
    #: changes the page without giving a file
    note: ButtonView = attrs.field(factory=lambda: ButtonView(text="Note"))
    # private: no widget shows it
    _report: Union[bytes, Path] = attrs.field(
        default=b"a,b\n1,2\n", init=False, metadata={OMIT: True}
    )

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.export.clicked.connect(self._export)
        self.note.clicked.connect(lambda: self.status_bar.show_message("Noted."))

    @property
    def report(self) -> Union[bytes, Path]:
        """Get what Export gives: bytes, or the path of a file the app wrote."""
        return self._report

    @report.setter
    def report(self, report: Union[bytes, Path]) -> None:
        self._report = report

    def _export(self) -> None:
        self.download("out/../report é.csv", self._report)

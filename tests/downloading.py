"""A main view giving its user files it makes, shared by the backends' tests of downloads."""

from __future__ import annotations

from pathlib import Path  # noqa: TC003 (attrs resolves the view's annotations)
from typing import Union

import attrs

from composeui.core.view import (
    OMIT,
    ButtonView,
    DownloadView,
    MainView,
    StreamContent,
    define_view,
)


@define_view
class ReportMainView(MainView):
    """Export gives the report at once, Export later in a job, under a name with a folder."""

    has_file_menu = False

    export: DownloadView = attrs.field(
        factory=lambda: DownloadView(text="Export", filename="out/../report é.csv")
    )
    later: DownloadView = attrs.field(
        factory=lambda: DownloadView(text="Export later", filename="later.csv", in_job=True)
    )
    #: changes the page without giving a file
    note: ButtonView = attrs.field(factory=lambda: ButtonView(text="Note"))
    # private: no widget shows it
    _report: Union[bytes, Path, StreamContent] = attrs.field(
        default=b"a,b\n1,2\n", init=False, metadata={OMIT: True}
    )

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.export.content = self.later.content = self._make_report
        self.note.clicked.connect(lambda: self.status_bar.show_message("Noted."))

    @property
    def report(self) -> Union[bytes, Path, StreamContent]:
        """Get what the buttons give: bytes, the path of a file the app wrote, or its writer."""
        return self._report

    @report.setter
    def report(self, report: Union[bytes, Path, StreamContent]) -> None:
        self._report = report

    def _make_report(self) -> Union[bytes, Path, StreamContent]:
        return self._report

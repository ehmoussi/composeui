"""OCC view."""

from composeui.salomewrapper.core import displayer
from composeui.salomewrapper.core.views.ioccview import IOCCView
from composeui.salomewrapper.core.qt.qtsalomeview import QtSalomeView

from dataclasses import dataclass
from typing import List


@dataclass(eq=False)
class QtOCCView(QtSalomeView, IOCCView):

    def display_entries(self, entries: List[str]) -> None:
        displayer.display_only_entities(entries)

"""OCC view."""

from composeui.salomewrapper.core import displayer
from composeui.salomewrapper.core.ioccview import IOCCView
from composeui.salomewrapper.core.qt.salomeview import SalomeView

from dataclasses import dataclass
from typing import List


@dataclass(eq=False)
class OCCView(SalomeView, IOCCView):

    def display_entries(self, entries: List[str]) -> None:
        displayer.display_only_entities(entries)

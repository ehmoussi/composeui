from composeui.salomewrapper.core.views.salomeview import SalomeView

from dataclasses import dataclass
from typing import List


@dataclass(eq=False)
class OCCView(SalomeView):

    def display_entries(self, entries: List[str]) -> None: ...

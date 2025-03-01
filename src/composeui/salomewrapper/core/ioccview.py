from composeui.salomewrapper.core.isalomeview import ISalomeView

from dataclasses import dataclass
from typing import List


@dataclass(eq=False)
class IOCCView(ISalomeView):

    def display_entries(self, entries: List[str]) -> None: ...

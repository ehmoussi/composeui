from composeui.core.basesignal import BaseSignal
from composeui.core.views.view import View

from dataclasses import dataclass, field
from typing import List


@dataclass(eq=False)
class SalomeTree(View):
    current_selections: List[str] = field(init=False, default_factory=list)
    selection_changed: BaseSignal = field(init=False, repr=False, default=BaseSignal())
    data_changed: BaseSignal = field(init=False, repr=False, default=BaseSignal())
    geometry_entries_removed: BaseSignal = field(init=False, repr=False, default=BaseSignal())

    def get_last_entries_removed(self) -> List[str]:
        return []

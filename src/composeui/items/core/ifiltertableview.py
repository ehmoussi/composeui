from composeui.core.basesignal import BaseSignal
from composeui.core.interfaces.iview import IView

from dataclasses import dataclass, field
from typing import Tuple


@dataclass(eq=False)
class IFilterTableView(IView):
    text: str = field(init=False, default="")
    info_text: str = field(init=False, default="")
    match_case: bool = field(init=False, default=False)
    match_whole_word: bool = field(init=False, default=False)
    use_regex: bool = field(init=False, default=False)
    selected_column_indices: Tuple[int, ...] = field(init=False, default_factory=tuple)
    filter_changed: BaseSignal = field(init=False, default=BaseSignal())

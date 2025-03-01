"""View definition for the pagination of a table/tree."""

from composeui.core.basesignal import BaseSignal
from composeui.core.views.iview import IView

from dataclasses import dataclass, field
from typing import List


@dataclass(eq=False)
class IPaginationView(IView):
    current_page: int = field(init=False, default=0)
    current_page_size_index: int = field(init=False, default=0)

    # view parameters
    is_first_enabled: bool = field(init=False, default=True)
    is_previous_enabled: bool = field(init=False, default=True)
    is_next_enabled: bool = field(init=False, default=True)
    is_last_enabled: bool = field(init=False, default=True)

    page_size_values: List[int] = field(init=False, default_factory=list)

    row_summary: str = field(init=False, default="")
    page_navigation_description: str = field(init=False, default="")

    # signals
    size_changed: BaseSignal = field(init=False, default=BaseSignal())
    current_page_changed: BaseSignal = field(init=False, default=BaseSignal())
    current_page_size_changed: BaseSignal = field(init=False, default=BaseSignal(int))
    first_clicked: BaseSignal = field(init=False, default=BaseSignal())
    previous_clicked: BaseSignal = field(init=False, default=BaseSignal())
    next_clicked: BaseSignal = field(init=False, default=BaseSignal())
    last_clicked: BaseSignal = field(init=False, default=BaseSignal())

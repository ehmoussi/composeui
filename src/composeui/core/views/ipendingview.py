from composeui.core.views.iview import View

from dataclasses import dataclass, field


@dataclass(eq=False)
class PendingView(View):
    is_update_pending: bool = field(init=False, default=False)

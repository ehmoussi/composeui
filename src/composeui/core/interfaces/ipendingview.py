from composeui.core.interfaces.iview import IView

from dataclasses import dataclass, field


@dataclass(eq=False)
class IPendingView(IView):
    is_update_pending: bool = field(init=False, default=False)

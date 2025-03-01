from composeui.core.views.ipendingview import PendingView

from functools import wraps
from typing import Callable, TypeVar

T = TypeVar("T", bound=PendingView)


def pending_until_visible(update: Callable[[T], None]) -> Callable[[T], None]:
    r"""Add the update of the pending attribute and update only if visible"""

    @wraps(update)
    def update_with_pending(self: T) -> None:
        if self.is_visible:
            update(self)
            self.is_update_pending = False
        else:
            self.is_update_pending = True

    return update_with_pending

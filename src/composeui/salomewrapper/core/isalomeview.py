from composeui.core.interfaces.iview import IView

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(eq=False)
class ISalomeView(IView):
    module_name: str
    view_type: str
    main_id: Optional[int] = field(default=None)
    is_active: bool = field(init=False, default=False)
    is_closable: bool = field(init=False, default=True)
    title: str = field(init=False, default="")
    _view_id: int = field(init=False, default=-1)

    def get_view_id(self) -> int:
        return self._view_id

    def generate_view(self) -> None:
        pass

    def create_view(self) -> int:
        return -1

    def get_views(self) -> List[int]:
        return []

    def move_view(self) -> None:
        pass

    def get_active_view(self) -> int:
        return -1

    def activate_view(self, view_id: int) -> None:
        pass

from composeui.salomewrapper.core.isalomeview import ISalomeView

from qtpy.QtWidgets import QWidget
from salome.gui import helper  # noqa: F811, RUF100

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(eq=False)
class SalomeView(ISalomeView):
    view: Optional[QWidget] = field(default=None)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.generate_view()

    def get_view_id(self) -> int:
        self.generate_view()
        return self._view_id

    def generate_view(self) -> None:
        existing_view_ids = self.get_views()
        if self._view_id == -1 or self._view_id not in existing_view_ids:
            if len(existing_view_ids) > 0:
                self._view_id = existing_view_ids[-1]
            else:
                self._view_id = self.create_view()

    def create_view(self) -> int:
        if self.view is None:
            return int(helper.sgPyQt.createView(self.view_type))
        else:
            return int(helper.sgPyQt.createView(self.view_type, self.view))

    def get_views(self) -> List[int]:
        """Get the list of ids of the views with the same type."""
        return list(helper.sgPyQt.findViews(self.view_type))

    def move_view(self) -> None:
        """Set the view with the given id as the active view."""
        current_view_id: int = self.get_active_view()
        if self._view_id not in (-1, current_view_id):
            helper.sgPyQt.moveView(current_view_id, self._view_id, False)

    def get_active_view(self) -> int:
        """Get the current active view."""
        return int(helper.sgPyQt.getActiveView())

    def activate_view(self, view_id: int) -> None:
        """Activate the view with the given id."""
        if view_id != -1:
            helper.sgPyQt.activateView(view_id)

    @property  # type: ignore[misc]
    def title(self) -> str:
        if self._view_id != -1:
            return str(helper.sgPyQt.getViewTitle(self._view_id))
        return ""

    @title.setter
    def title(self, title: str) -> None:
        if self._view_id != -1:
            helper.sgPyQt.setViewTitle(self._view_id, title)

    @property  # type: ignore[misc]
    def is_visible(self) -> bool:
        if self._view_id != -1:
            return bool(helper.sgPyQt.isViewVisible(self._view_id))
        return False

    @is_visible.setter
    def is_visible(self, is_visible: bool) -> None:
        view_id = self.get_view_id()
        helper.sgPyQt.setViewVisible(view_id, is_visible)
        if is_visible:
            self.is_active = True

    @property  # type: ignore[misc]
    def is_active(self) -> bool:
        return self.get_active_view() == self._view_id

    @is_active.setter
    def is_active(self, is_active: bool) -> None:
        if is_active:
            self.move_view()
        elif self.main_id is not None:
            self.activate_view(self.main_id)

    @property  # type: ignore[misc]
    def is_closable(self) -> bool:
        if self._view_id != -1:
            return bool(helper.sgPyQt.isViewClosable(self._view_id))
        return True

    @is_closable.setter
    def is_closable(self, is_closable: bool) -> None:
        if self._view_id != -1:
            helper.sgPyQt.setViewClosable(self._view_id, is_closable)

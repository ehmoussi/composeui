"""View."""

from composeui.core.qt.qtview import QtView
from composeui.core.views.view import GroupView

from qtpy.QtWidgets import QGroupBox

from dataclasses import dataclass, field


@dataclass(eq=False)
class QtGroupView(QtView, GroupView):
    """View with a groupbox."""

    view: QGroupBox = field(init=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.view = QGroupBox()

    @property  # type: ignore[misc]
    def title(self) -> str:
        return str(self.view.title())

    @title.setter
    def title(self, title: str) -> None:
        self.view.setTitle(title)

    @property  # type: ignore[misc]
    def is_checkable(self) -> bool:
        return bool(self.view.isCheckable())

    @is_checkable.setter
    def is_checkable(self, is_checkable: bool) -> None:
        self.view.setCheckable(is_checkable)

    @property  # type: ignore[misc]
    def is_checked(self) -> bool:
        return bool(self.view.isChecked())

    @is_checked.setter
    def is_checked(self, is_checked: bool) -> None:
        self.view.setChecked(is_checked)

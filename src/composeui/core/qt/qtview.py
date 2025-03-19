"""View."""

from composeui.core.views.view import View

from qtpy.QtWidgets import QAction, QWidget

from dataclasses import dataclass, field
from typing import Optional, Union


@dataclass(eq=False)
class QtView(View):
    """View."""

    view: Optional[Union[QAction, QWidget]] = field(init=False, repr=False)

    _block_signals: bool = field(init=False, repr=False, default=False)

    @property  # type: ignore[misc]
    def is_visible(self) -> bool:
        if self.view is not None:
            return bool(self.view.isVisible())
        return True

    @is_visible.setter
    def is_visible(self, is_visible: bool) -> None:
        if self.view is not None:
            self.view.setVisible(is_visible)

    @property  # type: ignore[misc]
    def is_enabled(self) -> bool:
        if self.view is not None:
            return bool(self.view.isEnabled())
        return True

    @is_enabled.setter
    def is_enabled(self, is_enabled: bool) -> None:
        if self.view is not None:
            self.view.setEnabled(is_enabled)

    @property  # type: ignore[misc]
    def minimum_width(self) -> int:
        if isinstance(self.view, QWidget):
            return self.view.minimumWidth()
        return 0

    @minimum_width.setter
    def minimum_width(self, width: int) -> None:
        if isinstance(self.view, QWidget):
            self.view.setMinimumWidth(width)

    @property  # type: ignore[misc]
    def minimum_height(self) -> int:
        if isinstance(self.view, QWidget):
            return self.view.minimumHeight()
        return 0

    @minimum_height.setter
    def minimum_height(self, height: int) -> None:
        if isinstance(self.view, QWidget):
            self.view.setMinimumHeight(height)

    @property  # type: ignore[misc]
    def block_signals(self) -> bool:
        return self._block_signals

    @block_signals.setter
    def block_signals(self, block_signals: bool) -> None:
        self._block_signals = block_signals
        if self.view is not None:
            self.view.blockSignals(block_signals)

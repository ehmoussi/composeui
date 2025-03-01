"""View."""

from composeui.core.views.iview import IView

from qtpy.QtWidgets import QAction, QWidget

from dataclasses import dataclass, field
from typing import Optional, Union


@dataclass(eq=False)
class QtView(IView):
    """View."""

    view: Optional[Union[QAction, QWidget]] = field(init=False)

    _block_signals: bool = field(init=False, default=False)

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
    def block_signals(self) -> bool:
        return self._block_signals

    @block_signals.setter
    def block_signals(self, block_signals: bool) -> None:
        self._block_signals = block_signals
        if self.view is not None:
            self.view.blockSignals(block_signals)

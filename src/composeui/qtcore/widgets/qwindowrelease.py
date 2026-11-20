from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from qtpy.QtCore import QEvent, QObject, QTimer
from qtpy.QtWidgets import QWidget
from typing_extensions import override

if TYPE_CHECKING:
    from qtpy.QtGui import QWindow


class _WindowReleaser(QObject):
    """Release its window's native window once hidden, until it's shown again."""

    @override
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Hide and isinstance(watched, QWidget):
            # once the hide is done, and only if nothing showed it again meanwhile; the
            # window as context, so a window deleted meanwhile (its parent's) drops it
            QTimer.singleShot(0, watched, lambda: _release(watched))
        return False


def _release(window: QWidget) -> None:
    handle: Optional[QWindow] = window.windowHandle()  # None before the window is shown
    if handle is not None and not window.isVisible():
        handle.destroy()


def release_when_hidden(window: QWidget) -> None:
    """Destroy the native window of `window`, a dialog, each time it's hidden.

    WSLg's Wayland compositor can keep drawing a dialog Qt has hidden, e.g. in a window
    holding a form beside another dialog. A click on its buttons answers, then it stays
    on screen. Without a native window there is nothing left to draw; Qt makes a new one
    when the dialog shows again, its widgets keeping their state.
    """
    window.installEventFilter(_WindowReleaser(window))

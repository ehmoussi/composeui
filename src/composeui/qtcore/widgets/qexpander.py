from __future__ import annotations

from typing import Any

from qtpy.QtCore import Qt
from qtpy.QtCore import Signal as QtSignal
from qtpy.QtWidgets import QSizePolicy, QToolButton, QVBoxLayout, QWidget

#: pixels the content is indented by, under the header's title
_INDENT = 20


class QExpander(QWidget):
    """A collapsible section: a header button with an arrow, then its content.

    The content shows only while the section is expanded. `expanded_changed` reports the
    user's clicks on the header; `set_expanded` is quiet, and so is any change while the
    expander's signals are blocked (the renderers block them while refreshing).
    """

    #: the user expanded (True) or collapsed (False) the section
    expanded_changed = QtSignal(bool)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.header = QToolButton()
        self.header.setCheckable(True)
        self.header.setAutoRaise(True)
        self.header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        # the whole row is the header to click, not only its text
        self.header.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        # flat: a checkable button draws itself pressed while expanded, not a header's look
        self.header.setStyleSheet("QToolButton { border: none; padding: 2px 0; }")
        font = self.header.font()
        font.setBold(True)
        self.header.setFont(font)
        self.header.toggled.connect(self._on_header_toggled)
        layout.addWidget(self.header)
        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        # under the title, past the arrow, so a nested section reads as nested
        self.content_layout.setContentsMargins(_INDENT, 0, 0, 0)
        layout.addWidget(self.content)
        self._show_expanded(is_expanded=False)

    def set_expanded(self, is_expanded: bool) -> None:
        self.header.blockSignals(True)  # noqa: FBT003
        self.header.setChecked(is_expanded)
        self.header.blockSignals(False)  # noqa: FBT003
        self._show_expanded(is_expanded=is_expanded)

    def _show_expanded(self, *, is_expanded: bool) -> None:
        self.header.setArrowType(Qt.ArrowType.DownArrow if is_expanded else Qt.ArrowType.RightArrow)
        self.content.setVisible(is_expanded)

    def _on_header_toggled(self, is_expanded: bool) -> None:
        self._show_expanded(is_expanded=is_expanded)
        self.expanded_changed.emit(is_expanded)

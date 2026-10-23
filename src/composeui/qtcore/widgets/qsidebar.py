from __future__ import annotations

from typing import Any

from qtpy.QtCore import Qt
from qtpy.QtCore import Signal as QtSignal
from qtpy.QtWidgets import (
    QDockWidget,
    QHBoxLayout,
    QMainWindow,
    QScrollArea,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from composeui.qtcore.widgets.qplaintext import plain_label

#: pixels a sidebar is wide at least while expanded, e.g. room for a form's fields
_MINIMUM_WIDTH = 280
#: Qt's largest widget size, a widget's maximum when nothing limits it
_QWIDGETSIZE_MAX = 16777215


class QSidebar(QDockWidget):
    """A dock for the window's left: a header, its title and a button, then its content.

    The dock stays where it is: it can't be closed, moved or floated, as the sidebar is
    part of the app's layout. Its own title bar is left out for the header. The header's
    button retracts the sidebar to a strip holding only the button, and expands it back;
    `expanded_changed` reports those clicks, and `set_expanded` is quiet, as is any change
    while the dock's signals are blocked (the renderers block them while refreshing).
    """

    #: the user expanded (True) or retracted (False) the sidebar
    expanded_changed = QtSignal(bool)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        self.setTitleBarWidget(QWidget())
        self._width = _MINIMUM_WIDTH
        body = QWidget()
        body_layout = self._body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        self._header = QHBoxLayout()
        header = self._header
        self.title = plain_label()
        font = self.title.font()
        font.setBold(True)
        self.title.setFont(font)
        header.addWidget(self.title, 1)
        self.toggle = QToolButton()
        self.toggle.setAutoRaise(True)
        self.toggle.clicked.connect(self._on_toggle_clicked)
        header.addWidget(self.toggle, 0, Qt.AlignmentFlag.AlignTop)
        body_layout.addLayout(header)
        content = QWidget()
        self.content_layout = QVBoxLayout(content)
        self.content_scroll = QScrollArea()
        self.content_scroll.setMinimumWidth(_MINIMUM_WIDTH)
        self.content_scroll.setWidgetResizable(True)
        self.content_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        # as wide as its content: no horizontal scroll bar
        self.content_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.content_scroll.setWidget(content)
        body_layout.addWidget(self.content_scroll, 1)
        # the strip's room below the button, once retracted
        body_layout.addStretch(0)
        self.setWidget(body)
        self._show_expanded(is_expanded=True)

    def finish_content(self) -> None:
        """Leave the height to spare below the content, once it is added, not between it."""
        self.content_layout.addStretch()

    def is_expanded(self) -> bool:
        return self.content_scroll.isVisibleTo(self)

    def set_expanded(self, is_expanded: bool) -> None:
        self._show_expanded(is_expanded=is_expanded)

    def set_title(self, title: str) -> None:
        self.title.setText(title)
        self.title.setVisible(title != "" and self.is_expanded())

    def _show_expanded(self, *, is_expanded: bool) -> None:
        if not is_expanded and self.content_scroll.isVisibleTo(self):
            self._width = self.width()  # given back once expanded
        self.content_scroll.setVisible(is_expanded)
        self.title.setVisible(is_expanded and self.title.text() != "")
        # pointing the way the sidebar goes: left to retract it, right to expand it
        arrow = Qt.ArrowType.LeftArrow if is_expanded else Qt.ArrowType.RightArrow
        self.toggle.setArrowType(arrow)
        style = self.style()
        left = style.pixelMetric(QStyle.PixelMetric.PM_LayoutLeftMargin)
        right = style.pixelMetric(QStyle.PixelMetric.PM_LayoutRightMargin)
        top = style.pixelMetric(QStyle.PixelMetric.PM_LayoutTopMargin)
        # expanded, inset like the rows under it (their column's margin, then their own);
        # retracted, the strip only as wide as the button and a margin
        inset = 2 if is_expanded else 1
        self._header.setContentsMargins(inset * left, top, inset * right, 0)
        self._body_layout.activate()
        # a dock keeps the width it has: retracted, as narrow as the strip; expanded, back
        # to its width before
        self.setMaximumWidth(_QWIDGETSIZE_MAX if is_expanded else self.minimumSizeHint().width())
        window = self.parentWidget()
        if is_expanded and isinstance(window, QMainWindow):
            window.resizeDocks([self], [self._width], Qt.Orientation.Horizontal)

    def _on_toggle_clicked(self) -> None:
        is_expanded = not self.is_expanded()
        self._show_expanded(is_expanded=is_expanded)
        self.expanded_changed.emit(is_expanded)

"""A Qt Location map embedded in a Widgets layout, without a browser engine."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from qtpy.QtCore import Qt, QUrl
from qtpy.QtCore import Signal as QtSignal
from qtpy.QtQuickWidgets import QQuickWidget
from qtpy.QtWidgets import QLabel, QVBoxLayout, QWidget
from typing_extensions import override

from composeui.qtcore.widgets.qplaintext import plain_label

if TYPE_CHECKING:
    from qtpy.QtGui import QResizeEvent


class _MapCanvas(QQuickWidget):
    resized = QtSignal()

    @override
    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self.resized.emit()


class QMap(QWidget):
    """A title above a Qt Location map with a single canvas for its points."""

    viewport_moved = QtSignal(float, float, float)
    point_clicked = QtSignal(float, float)

    def __init__(self, user_agent: str, *, tiles: bool) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.title: QLabel = plain_label()
        layout.addWidget(self.title)
        self.map = _MapCanvas()
        self.map.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.map.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        layout.addWidget(self.map)
        self._settings: tuple[str, bool] | None = None
        self.configure(user_agent, tiles=tiles)

    def configure(self, user_agent: str, *, tiles: bool) -> None:
        """Load the component with its tile settings, which Qt's plugin reads only once."""
        if self._settings == (user_agent, tiles):
            return
        self._settings = (user_agent, tiles)
        self.map.setSource(QUrl())
        self.map.rootContext().setContextProperty("mapUserAgent", user_agent)
        self.map.setInitialProperties({"tiles": tiles})
        self.map.setSource(QUrl.fromLocalFile(str(Path(__file__).with_name("map.qml"))))
        self.root.viewportMoved.connect(self.viewport_moved)
        self.root.pointClicked.connect(self.point_clicked)

    @property
    def root(self) -> Any:
        """Get the map's QML root after loading its component."""
        root = self.map.rootObject()
        if root is None:
            message = "; ".join(error.toString() for error in self.map.errors())
            message = f"Cannot load the Qt Location map: {message}"
            raise RuntimeError(message)
        return root

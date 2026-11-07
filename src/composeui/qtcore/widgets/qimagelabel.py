from __future__ import annotations

from typing import TYPE_CHECKING

from qtpy.QtCore import QRect, QSize, Qt
from qtpy.QtGui import QPainter, QPixmap
from qtpy.QtWidgets import QLabel, QSizePolicy

if TYPE_CHECKING:
    from qtpy.QtGui import QPaintEvent


class QImageLabel(QLabel):
    """An image in its proportions, shrunk to the label's size; its text without an image."""

    def __init__(self) -> None:
        super().__init__()
        self._image = QPixmap()
        self._height: int | None = None
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setWordWrap(True)
        policy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def set_image(self, content: bytes | None) -> None:
        """Show the image in `content`; the text for none, or for content Qt can't read."""
        image = QPixmap()
        if content is not None:
            image.loadFromData(content)
        self._image = image
        self.updateGeometry()
        self.update()

    def set_image_height(self, height: int | None) -> None:
        """Give the image this height, grown to it if need be; None: its own."""
        self._height = height
        self.updateGeometry()
        self.update()

    def _shown_size(self) -> QSize:
        """Get the image's size where it has all the room it asks for."""
        size = self._image.size()
        if self._height is None:
            return size
        return QSize(max(1, size.width() * self._height // size.height()), self._height)

    def sizeHint(self) -> QSize:  # noqa: N802
        return super().sizeHint() if self._image.isNull() else self._shown_size()

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        # the layout may shrink the image, as `paintEvent` does
        return super().minimumSizeHint() if self._image.isNull() else QSize(1, 1)

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        if self._image.isNull():
            return super().heightForWidth(width)
        size = self._shown_size()
        return min(size.height(), max(1, size.height() * width // size.width()))

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        if self._image.isNull():
            super().paintEvent(event)
            return
        size = self._shown_size()
        if size.width() > self.width() or size.height() > self.height():
            size = size.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(QRect(0, 0, size.width(), size.height()), self._image)
        # before the paint event ends: Python would free it at any later time
        painter.end()

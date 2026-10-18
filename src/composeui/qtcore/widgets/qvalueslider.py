from typing import Any

from qtpy.QtCore import QRect, QSize, Qt
from qtpy.QtCore import Signal as QtSignal
from qtpy.QtGui import QPainter, QPaintEvent
from qtpy.QtWidgets import QSlider, QStyle, QStyleOptionSlider

#: pixels between the value and the handle
_GAP = 2


class QValueSlider(QSlider):
    """A horizontal slider from `first` by `step`, its value painted above the handle.

    Its own range counts steps (positions 0 to the last), so the handle only stops on
    a step; `shown_value` is the value at the handle. The value is painted in the room
    left above the handle, the handle staying vertically centered, where the style's
    mouse handling expects it.
    """

    #: the user moved the handle to the value; never while signals are blocked
    shown_value_changed = QtSignal(int)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(Qt.Orientation.Horizontal, *args, **kwargs)
        self.first = 0
        self.step = 1
        self.valueChanged.connect(self._emit_shown_value)

    def shown_value(self) -> int:
        return self.first + self.value() * self.step

    def value_rect(self) -> QRect:
        """Get where the value is painted: centered above the handle, within the slider."""
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        handle = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderHandle, self
        )
        metrics = self.fontMetrics()
        width = metrics.horizontalAdvance(str(self.shown_value()))
        left = min(max(0, handle.center().x() - width // 2), self.width() - width)
        return QRect(left, handle.top() - _GAP - metrics.height(), width, metrics.height())

    def sizeHint(self) -> QSize:  # noqa: N802
        return self._with_value_room(super().sizeHint())

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self._with_value_room(super().minimumSizeHint())

    def _with_value_room(self, size: QSize) -> QSize:
        # the value's height above the handle, and as much below to keep it centered
        return QSize(size.width(), size.height() + 2 * (self.fontMetrics().height() + _GAP))

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.drawText(self.value_rect(), Qt.AlignmentFlag.AlignCenter, str(self.shown_value()))
        painter.end()

    def _emit_shown_value(self, _position: int) -> None:
        self.shown_value_changed.emit(self.shown_value())

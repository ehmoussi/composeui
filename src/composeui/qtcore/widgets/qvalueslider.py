from typing import Any

from qtpy.QtCore import QRect, QSize, Qt
from qtpy.QtCore import Signal as QtSignal
from qtpy.QtGui import QPainter, QPaintEvent
from qtpy.QtWidgets import QSlider, QStyleOptionSlider

#: pixels between the track and the value
_GAP = 8


class QValueSlider(QSlider):
    """A horizontal slider from `first` by `step`, its value on the right of the track.

    Its own range counts steps (positions 0 to the last), so the handle only stops on
    a step; `shown_value` is the value at the handle. The value has a slot as wide as
    the widest one, so the track keeps its length as the value changes; the style lays
    the slider out left of it (`initStyleOption`), which painting and the mouse both
    use. Beside the track rather than above the handle, the slider is no taller than a
    plain one, so its form row is as tall as the others.
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
        """Get the value's slot, on the right of the track, as tall as the slider."""
        width = self._slot_width()
        return QRect(self.width() - width, 0, width, self.height())

    def _slot_width(self) -> int:
        metrics = self.fontMetrics()
        ends = (self.first, self.first + self.maximum() * self.step)
        return max(metrics.horizontalAdvance(str(end)) for end in ends)

    def initStyleOption(self, option: QStyleOptionSlider) -> None:  # noqa: N802
        super().initStyleOption(option)
        option.rect.setRight(option.rect.right() - self._slot_width() - _GAP)

    def sizeHint(self) -> QSize:  # noqa: N802
        # no `minimumSizeHint`: a horizontal slider's is its `sizeHint`, the slot in already
        size = super().sizeHint()
        return QSize(size.width() + self._slot_width() + _GAP, size.height())

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        align = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        painter.drawText(self.value_rect(), align, str(self.shown_value()))
        painter.end()

    def _emit_shown_value(self, _position: int) -> None:
        self.shown_value_changed.emit(self.shown_value())

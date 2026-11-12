"""A slider with two handles, for a range: its ends on the right of the track."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from qtpy.QtCore import QRect, QSize, Qt
from qtpy.QtCore import Signal as QtSignal
from qtpy.QtGui import QPainter
from qtpy.QtWidgets import QSlider, QStyle, QStyleOptionSlider

from composeui.core.view import RANGE_DASH, SliderMixin

if TYPE_CHECKING:
    from qtpy.QtGui import QKeyEvent, QMouseEvent, QPaintEvent

#: pixels between the track and the ends
_GAP = 8


class QRangeSlider(QSlider):
    """A horizontal slider with a low and a high handle, from `first` by `step`.

    As `QValueSlider`, its positions count steps (0 to the last), and its ends show in a
    slot on the right of the track, as wide as the widest ends, so the track keeps its
    length. Qt has no such slider: it paints the style's groove without its fill, the fill
    between the handles, then each handle. A click moves the nearest handle; the arrow
    keys, Page Up/Down, move the last handle pressed (the low one at first); Home moves
    the low one to the start, End the high one to the end. A handle stops on the other.
    `moved` reports the user's moves only, with both positions.
    """

    #: the user moved a handle: the low and the high position
    moved = QtSignal(int, int)

    _KEY_STEPS: ClassVar[dict[Qt.Key, int]] = {
        Qt.Key.Key_Left: -1,
        Qt.Key.Key_Down: -1,
        Qt.Key.Key_Right: 1,
        Qt.Key.Key_Up: 1,
    }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(Qt.Orientation.Horizontal, *args, **kwargs)
        self.first: float = 0
        self.step: float = 1
        #: the arithmetic of the steps: `SliderMixin`, or `FloatSliderMixin` for decimals
        self.steps: Any = SliderMixin
        self.low = 0
        self.high = 0
        #: the handle the keys move: 0 the low one, 1 the high one
        self.active = 0
        self._is_dragging = False
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def set_positions(self, low: int, high: int) -> None:
        """Show the handles at `low` and `high`, without `moved`."""
        self.low, self.high = low, high
        self.update()

    def ends_text(self) -> str:
        return self._text_at(self.low) + RANGE_DASH + self._text_at(self.high)

    def _text_at(self, position: int) -> str:
        value = self.steps.value_at(position, self.first, self.step)
        return self.steps.shown_text(value, self.first, self.step)  # type: ignore[no-any-return]

    def value_rect(self) -> QRect:
        """Get the ends' slot, on the right of the track, as tall as the slider."""
        width = self._slot_width()
        return QRect(self.width() - width, 0, width, self.height())

    def _slot_width(self) -> int:
        metrics = self.fontMetrics()
        widest = max(metrics.horizontalAdvance(self._text_at(end)) for end in (0, self.maximum()))
        return 2 * widest + metrics.horizontalAdvance(RANGE_DASH)

    def initStyleOption(self, option: QStyleOptionSlider) -> None:  # noqa: N802
        super().initStyleOption(option)
        option.rect.setRight(option.rect.right() - self._slot_width() - _GAP)

    def sizeHint(self) -> QSize:  # noqa: N802
        size = super().sizeHint()
        return QSize(size.width() + self._slot_width() + _GAP, size.height())

    def _option_at(self, position: int) -> QStyleOptionSlider:
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        option.sliderPosition = option.sliderValue = position
        return option

    def _handle_rect(self, position: int) -> QRect:
        option = self._option_at(position)
        style = self.style()
        return style.subControlRect(
            QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderHandle, self
        )

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        style = self.style()
        option = self._option_at(self.minimum())
        option.subControls = QStyle.SubControl.SC_SliderGroove
        style.drawComplexControl(QStyle.ComplexControl.CC_Slider, option, painter, self)
        # the style's own fill, up to the high handle, shown only from the low one: as a
        # plain slider's, whatever the style
        left = self._handle_rect(self.low).center().x()
        right = self._handle_rect(self.high).center().x()
        filled = self._option_at(self.high)
        filled.subControls = QStyle.SubControl.SC_SliderGroove
        painter.save()
        painter.setClipRect(QRect(left, 0, right - left, self.height()))
        style.drawComplexControl(QStyle.ComplexControl.CC_Slider, filled, painter, self)
        painter.restore()
        for handle, position in enumerate((self.low, self.high)):
            option = self._option_at(position)
            option.subControls = QStyle.SubControl.SC_SliderHandle
            if handle != self.active:
                option.state &= ~QStyle.StateFlag.State_HasFocus
            style.drawComplexControl(QStyle.ComplexControl.CC_Slider, option, painter, self)
        align = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        painter.drawText(self.value_rect(), align, self.ends_text())
        painter.end()

    def _position_at(self, x: int) -> int:
        """Get the position under the pixel column `x`, as the style lays the track out."""
        option = self._option_at(self.minimum())
        style = self.style()
        groove = style.subControlRect(
            QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderGroove, self
        )
        handle = self._handle_rect(self.minimum()).width()
        span = max(1, groove.width() - handle)
        return QStyle.sliderValueFromPosition(
            self.minimum(), self.maximum(), x - groove.x() - handle // 2, span
        )

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            event.ignore()
            return
        position = self._position_at(event.position().toPoint().x())
        if self.low == self.high:
            # on one another: the one on the side of the click; on them, the one that can
            # move away from the end they are near, as the web's does
            if position == self.low:
                self.active = 0 if self.low > self.maximum() / 2 else 1
            else:
                self.active = 0 if position < self.low else 1
        else:
            self.active = 0 if abs(position - self.low) <= abs(position - self.high) else 1
        self._is_dragging = True
        self._move_active(position)
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._is_dragging:
            self._move_active(self._position_at(event.position().toPoint().x()))
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._is_dragging = False
        event.accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        key = Qt.Key(event.key())
        page = max(1, self.maximum() // 10)
        positions = (self.low, self.high)
        if key in self._KEY_STEPS:
            self._move_active(positions[self.active] + self._KEY_STEPS[key])
        elif key in (Qt.Key.Key_PageUp, Qt.Key.Key_PageDown):
            direction = 1 if key == Qt.Key.Key_PageUp else -1
            self._move_active(positions[self.active] + direction * page)
        elif key == Qt.Key.Key_Home:
            self.active = 0
            self._move_active(self.minimum())
        elif key == Qt.Key.Key_End:
            self.active = 1
            self._move_active(self.maximum())
        else:
            super().keyPressEvent(event)
            return
        event.accept()

    def _move_active(self, position: int) -> None:
        """Move the active handle to `position`, stopping on the other one and in range."""
        position = min(max(self.minimum(), position), self.maximum())
        if self.active == 0:
            low, high = min(position, self.high), self.high
        else:
            low, high = self.low, max(position, self.low)
        if (low, high) != (self.low, self.high):
            self.low, self.high = low, high
            self.update()
            self.moved.emit(low, high)
        else:
            self.update()  # the active handle shows its focus

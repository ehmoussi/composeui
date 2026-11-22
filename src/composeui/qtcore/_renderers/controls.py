"""Qt renderers for buttons, check boxes, progress bars and sliders."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from qtpy.QtWidgets import QCheckBox, QProgressBar, QPushButton
from typing_extensions import Protocol, override

from composeui.core.renderer import ViewLike
from composeui.core.view import (
    ButtonVariant,
    DialogButtonView,
    FloatRangeSliderMixin,
    FloatSliderMixin,
    ProgressBarView,
    RangeSliderMixin,
    SliderMixin,
)
from composeui.qtcore.qtrenderer import QtWidgetRenderer
from composeui.qtcore.widgets.qrangeslider import QRangeSlider
from composeui.qtcore.widgets.qvalueslider import QValueSlider

if TYPE_CHECKING:
    from collections.abc import Callable

    from composeui.core.signal import Signal, SignalNoArgs


class SliderViewLike(ViewLike, Protocol):
    value: float
    minimum: float
    maximum: float
    step: float
    is_filled: bool
    value_changed: Signal[float]


class QtSliderRenderer(QtWidgetRenderer[SliderViewLike, QValueSlider]):
    """A horizontal slider stopping on each step, its value painted beside the track."""

    _invalid_style = "QSlider { border: 1px solid red; }"
    #: the arithmetic of its steps
    _steps: ClassVar[Any] = SliderMixin

    def __init__(self, view: SliderViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "value": self._refresh_value,
                "minimum": self._refresh_minimum,
                "maximum": self._refresh_maximum,
                "step": self._refresh_step,
                "is_filled": self._refresh_is_filled,
            }
        )

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QValueSlider()
            self._rendered_object.steps = self._steps
            # first, so the view's callbacks see the new value
            self._connect(
                self._rendered_object.shown_value_changed,
                self._update_value,
                self._view.value_changed.call_callbacks,
            )
            self.refresh()

    @classmethod
    def _refresh_value(
        cls, view: SliderViewLike, rendered_object: QValueSlider, value: float
    ) -> None:
        cls._show(rendered_object, value, view.minimum, view.maximum, view.step)

    @classmethod
    def _refresh_minimum(
        cls, view: SliderViewLike, rendered_object: QValueSlider, value: float
    ) -> None:
        cls._show(rendered_object, view.value, value, view.maximum, view.step)

    @classmethod
    def _refresh_maximum(
        cls, view: SliderViewLike, rendered_object: QValueSlider, value: float
    ) -> None:
        cls._show(rendered_object, view.value, view.minimum, value, view.step)

    @classmethod
    def _refresh_step(
        cls, view: SliderViewLike, rendered_object: QValueSlider, value: float
    ) -> None:
        cls._show(rendered_object, view.value, view.minimum, view.maximum, value)

    @staticmethod
    def _refresh_is_filled(
        _view: SliderViewLike, rendered_object: QValueSlider, value: bool
    ) -> None:
        rendered_object.is_filled = value
        rendered_object.update()

    @classmethod
    def _show(
        cls,
        rendered_object: QValueSlider,
        value: float,
        minimum: float,
        maximum: float,
        step: float,
    ) -> None:
        last = cls._steps.last_position(minimum, maximum, step)
        rendered_object.first, rendered_object.step = minimum, step
        rendered_object.drop_report()  # the app's value, not the user's drag
        rendered_object.setRange(0, last)
        rendered_object.setPageStep(max(1, last // 10))
        rendered_object.setValue(cls._steps.position(value, minimum, maximum, step))
        rendered_object.updateGeometry()  # the value's slot follows the widest value
        rendered_object.update()  # the value painted, even if the handle didn't move

    def _update_value(self, value: float) -> None:
        with self.stop_refresh():
            self._view.value = value


class QtFloatSliderRenderer(QtSliderRenderer):
    """A slider stopping on each decimal step."""

    _steps = FloatSliderMixin


class RangeSliderViewLike(ViewLike, Protocol):
    value: tuple[float, float]
    minimum: float
    maximum: float
    step: float
    value_changed: Signal[tuple[float, float]]


class QtRangeSliderRenderer(QtWidgetRenderer[RangeSliderViewLike, QRangeSlider]):
    """A horizontal slider with two handles stopping on each step, its ends beside the track."""

    _invalid_style = "QSlider { border: 1px solid red; }"
    #: the rules of its two ends
    _range: ClassVar[Any] = RangeSliderMixin

    def __init__(self, view: RangeSliderViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {name: self._refresher(name) for name in ("value", "minimum", "maximum", "step")}
        )
        # the web's handles, each an input of its own; this one widget is named by its row
        self._refresh_dispatcher.update(
            dict.fromkeys(("low_text", "high_text"), lambda _view, _rendered_object, _value: None)
        )

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QRangeSlider()
            self._rendered_object.steps = self._range.step_rules
            self._connect(self._rendered_object.moved, self._update_value)
            self.refresh()

    def _refresher(self, name: str) -> Callable[[RangeSliderViewLike, QRangeSlider, Any], None]:
        """Show the handles once the attribute `name` is set to the value given."""

        def refresh(view: RangeSliderViewLike, rendered_object: QRangeSlider, value: Any) -> None:
            state = {
                "value": view.value,
                "minimum": view.minimum,
                "maximum": view.maximum,
                "step": view.step,
                name: value,
            }
            self._show(rendered_object, **state)

        return refresh

    def _show(
        self,
        rendered_object: QRangeSlider,
        *,
        value: tuple[float, float],
        minimum: float,
        maximum: float,
        step: float,
    ) -> None:
        last = self._range.step_rules.last_position(minimum, maximum, step)
        rendered_object.first, rendered_object.step = minimum, step
        rendered_object.setRange(0, last)
        rendered_object.set_positions(*self._range.positions(value, minimum, maximum, step))
        rendered_object.updateGeometry()  # the ends' slot follows the widest ends

    def _update_value(self, low: int, high: int) -> None:
        view = self._view
        # the slider reports only a move, so the range changes
        value = self._range.moved(view.value, (low, high), view.minimum, view.maximum, view.step)
        with self.stop_refresh():
            view.value = value
        view.value_changed.emit(view.value)


class QtFloatRangeSliderRenderer(QtRangeSliderRenderer):
    """A slider with two handles stopping on each decimal step."""

    _range = FloatRangeSliderMixin


class CheckBoxViewLike(ViewLike, Protocol):
    text: str
    is_checked: bool
    toggled: Signal[bool]


class QtCheckBoxRenderer(QtWidgetRenderer[CheckBoxViewLike, QCheckBox]):
    _invalid_style = "QCheckBox { color: red; }"

    def __init__(self, view: CheckBoxViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "text": self._refresh_text,
                "is_checked": self._refresh_is_checked,
            }
        )

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QCheckBox()
            # first, so the view's callbacks see the new check state
            self._connect(
                self._rendered_object.toggled,
                self._update_checked,
                self._view.toggled.call_callbacks,
            )
            self.refresh()

    @staticmethod
    def _refresh_text(_view: CheckBoxViewLike, rendered_object: QCheckBox, value: str) -> None:
        rendered_object.setText(value)

    @staticmethod
    def _refresh_is_checked(
        _view: CheckBoxViewLike, rendered_object: QCheckBox, value: bool
    ) -> None:
        rendered_object.setChecked(value)

    def _update_checked(self, is_checked: bool) -> None:
        with self.stop_refresh():
            self._view.is_checked = is_checked


class ButtonViewLike(ViewLike, Protocol):
    text: str
    variant: ButtonVariant
    clicked: SignalNoArgs


class QtButtonRenderer(QtWidgetRenderer[ButtonViewLike, QPushButton]):
    def __init__(self, view: ButtonViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {"text": self._refresh_text, "variant": self._refresh_variant}
        )

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QPushButton()
            # Qt's own `clicked` also passes the check state, which a button doesn't have
            self._connect(self._rendered_object.clicked, self._emit_clicked)
            self.refresh()

    @staticmethod
    def _refresh_text(_view: ButtonViewLike, rendered_object: QPushButton, value: str) -> None:
        rendered_object.setText(value)

    @staticmethod
    def _refresh_variant(
        _view: ButtonViewLike, rendered_object: QPushButton, value: ButtonVariant
    ) -> None:
        # Qt has no variants: the style draws a default button emphasized, and a
        # destroying one is red like an invalid field
        rendered_object.setDefault(value is ButtonVariant.PRIMARY)
        is_danger = value is ButtonVariant.DANGER
        rendered_object.setStyleSheet("QPushButton { color: red; }" if is_danger else "")

    def _emit_clicked(self) -> None:
        self._view.clicked.emit()


class QtDownloadRenderer(QtButtonRenderer):
    """A button giving a file: what makes the file is read on each click."""

    def __init__(self, view: ButtonViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            dict.fromkeys(
                ("filename", "media_type", "content", "in_job", "prepare", "enabled_if"), self._noop
            )
        )

    @staticmethod
    def _noop(_view: ButtonViewLike, _rendered_object: QPushButton, _value: object) -> None:
        pass


class QtDialogButtonRenderer(QtButtonRenderer):
    """A dialog's own button, e.g. Apply: its click goes through its dialog, which checks first."""

    def __init__(self, view: DialogButtonView) -> None:
        super().__init__(view)
        self._dialog_button = view
        self._refresh_dispatcher.update(
            {
                "is_enabled": self._refresh_button_enabled,
                "is_blocked": self._refresh_is_blocked,
                "closes": self._noop,
                "checks": self._noop,
            }
        )

    @override
    def render(self) -> None:
        super().render()
        assert self._rendered_object is not None
        # not the dialog's default button: Enter is still OK
        self._rendered_object.setAutoDefault(False)

    # each is told its own field's new value, not yet the view's
    def _refresh_button_enabled(
        self, _view: ButtonViewLike, rendered_object: QPushButton, value: bool
    ) -> None:
        rendered_object.setEnabled(value and not self._dialog_button.is_blocked)

    def _refresh_is_blocked(
        self, _view: ButtonViewLike, rendered_object: QPushButton, value: bool
    ) -> None:
        rendered_object.setEnabled(self._dialog_button.is_enabled and not value)

    @staticmethod
    def _noop(_view: ButtonViewLike, _rendered_object: QPushButton, _value: bool) -> None:
        pass  # read on each click

    @override
    def _emit_clicked(self) -> None:
        self._dialog_button.click()


class ProgressBarViewLike(ViewLike, Protocol):
    value: int
    maximum: int | None


class QtProgressBarRenderer(QtWidgetRenderer[ProgressBarViewLike, QProgressBar]):
    def __init__(self, view: ProgressBarViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {"value": self._refresh_value, "maximum": self._refresh_maximum}
        )

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QProgressBar()
            self.refresh()

    @staticmethod
    def _refresh_value(
        view: ProgressBarViewLike, rendered_object: QProgressBar, value: int
    ) -> None:
        # clamped: Qt ignores a value out of range, leaving the bar where it was
        rendered_object.setValue(ProgressBarView.clamp(value, view.maximum))

    @staticmethod
    def _refresh_maximum(
        view: ProgressBarViewLike, rendered_object: QProgressBar, value: int | None
    ) -> None:
        # an empty range is Qt's busy bar, for a task of unknown length
        rendered_object.setRange(0, 0 if value is None else value)
        rendered_object.setValue(ProgressBarView.clamp(view.value, value))

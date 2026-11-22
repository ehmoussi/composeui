"""Textual buttons, check boxes, sliders and progress bars."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from textual.content import Content
from textual.widgets import ProgressBar
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
from composeui.textualcore.textualrenderer import TextualWidgetRenderer
from composeui.textualcore.widgets.composebutton import ComposeButton
from composeui.textualcore.widgets.composecheckbox import ComposeCheckBox
from composeui.textualcore.widgets.composerange import ComposeRangeSlider
from composeui.textualcore.widgets.composeslider import ComposeSlider

if TYPE_CHECKING:
    from collections.abc import Callable

    from textual.widgets.button import ButtonVariant as ButtonVariantName

    from composeui.core.signal import Signal, SignalNoArgs


class SliderViewLike(ViewLike, Protocol):
    value: float
    minimum: float
    maximum: float
    step: float
    is_filled: bool
    value_changed: Signal[float]


class TextualSliderRenderer(TextualWidgetRenderer[SliderViewLike, ComposeSlider]):
    _marks_invalid = True
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
            self._rendered_object = ComposeSlider()
            self._rendered_object.steps = self._steps
            self._rendered_object.moved.connect(self._update_value)

    @classmethod
    def _refresh_value(
        cls, view: SliderViewLike, rendered_object: ComposeSlider, value: float
    ) -> None:
        cls._show(rendered_object, value, view.minimum, view.maximum, view.step)

    @classmethod
    def _refresh_minimum(
        cls, view: SliderViewLike, rendered_object: ComposeSlider, value: float
    ) -> None:
        cls._show(rendered_object, view.value, value, view.maximum, view.step)

    @classmethod
    def _refresh_maximum(
        cls, view: SliderViewLike, rendered_object: ComposeSlider, value: float
    ) -> None:
        cls._show(rendered_object, view.value, view.minimum, value, view.step)

    @classmethod
    def _refresh_step(
        cls, view: SliderViewLike, rendered_object: ComposeSlider, value: float
    ) -> None:
        cls._show(rendered_object, view.value, view.minimum, view.maximum, value)

    @staticmethod
    def _refresh_is_filled(
        _view: SliderViewLike, rendered_object: ComposeSlider, value: bool
    ) -> None:
        rendered_object.is_filled = value
        rendered_object.refresh()

    @classmethod
    def _show(
        cls,
        rendered_object: ComposeSlider,
        value: float,
        minimum: float,
        maximum: float,
        step: float,
    ) -> None:
        rendered_object.set_steps(
            minimum,
            step,
            cls._steps.last_position(minimum, maximum, step),
            cls._steps.position(value, minimum, maximum, step),
        )

    def _update_value(self, value: float) -> None:
        with self.stop_refresh():
            self._view.value = value
        self._view.value_changed.emit(value)


class TextualFloatSliderRenderer(TextualSliderRenderer):
    """A slider stopping on each decimal step."""

    _steps = FloatSliderMixin


class RangeSliderViewLike(ViewLike, Protocol):
    value: tuple[float, float]
    minimum: float
    maximum: float
    step: float
    value_changed: Signal[tuple[float, float]]


class TextualRangeSliderRenderer(TextualWidgetRenderer[RangeSliderViewLike, ComposeRangeSlider]):
    """A slider with two handles stopping on each step, its ends beside the track."""

    _marks_invalid = True
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
            self._rendered_object = ComposeRangeSlider()
            self._rendered_object.steps = self._range.step_rules
            self._rendered_object.moved.connect(self._update_value)

    def _refresher(
        self, name: str
    ) -> Callable[[RangeSliderViewLike, ComposeRangeSlider, Any], None]:
        """Show the handles once the attribute `name` is set to the value given."""

        def refresh(
            view: RangeSliderViewLike, rendered_object: ComposeRangeSlider, value: Any
        ) -> None:
            state = {
                "value": view.value,
                "minimum": view.minimum,
                "maximum": view.maximum,
                "step": view.step,
                name: value,
            }
            minimum, maximum, step = state["minimum"], state["maximum"], state["step"]
            steps = self._range.step_rules
            rendered_object.set_steps(
                minimum,
                step,
                steps.last_position(minimum, maximum, step),
                *self._range.positions(state["value"], minimum, maximum, step),
            )

        return refresh

    def _update_value(self, low: int, high: int) -> None:
        view = self._view
        # the slider reports only a move, so the range changes
        value = self._range.moved(view.value, (low, high), view.minimum, view.maximum, view.step)
        with self.stop_refresh():
            view.value = value
        view.value_changed.emit(view.value)


class TextualFloatRangeSliderRenderer(TextualRangeSliderRenderer):
    """A slider with two handles stopping on each decimal step."""

    _range = FloatRangeSliderMixin


class CheckBoxViewLike(ViewLike, Protocol):
    text: str
    is_checked: bool
    toggled: Signal[bool]


class TextualCheckBoxRenderer(TextualWidgetRenderer[CheckBoxViewLike, ComposeCheckBox]):
    _marks_invalid = True

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
            self._rendered_object = ComposeCheckBox()
            self._rendered_object.toggled.connect(self._update_checked)

    @staticmethod
    def _refresh_text(
        _view: CheckBoxViewLike, rendered_object: ComposeCheckBox, value: str
    ) -> None:
        rendered_object.label = Content(value)

    @staticmethod
    def _refresh_is_checked(
        _view: CheckBoxViewLike, rendered_object: ComposeCheckBox, value: bool
    ) -> None:
        rendered_object.set_checked(value)

    def _update_checked(self, is_checked: bool) -> None:
        with self.stop_refresh():
            self._view.is_checked = is_checked
        self._view.toggled.emit(is_checked)


class ButtonViewLike(ViewLike, Protocol):
    text: str
    variant: ButtonVariant
    clicked: SignalNoArgs


#: each button variant as Textual's
_BUTTON_VARIANTS: dict[ButtonVariant, ButtonVariantName] = {
    ButtonVariant.PRIMARY: "primary",
    ButtonVariant.SECONDARY: "default",
    ButtonVariant.DANGER: "error",
}


class TextualButtonRenderer(TextualWidgetRenderer[ButtonViewLike, ComposeButton]):
    def __init__(self, view: ButtonViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {"text": self._refresh_text, "variant": self._refresh_variant}
        )

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = ComposeButton()
            self._rendered_object.clicked.connect(self._view.clicked.emit)

    @staticmethod
    def _refresh_text(_view: ButtonViewLike, rendered_object: ComposeButton, value: str) -> None:
        rendered_object.label = Content(value)

    @staticmethod
    def _refresh_variant(
        _view: ButtonViewLike, rendered_object: ComposeButton, value: ButtonVariant
    ) -> None:
        rendered_object.variant = _BUTTON_VARIANTS[value]


class TextualDownloadRenderer(TextualButtonRenderer):
    """A button giving a file: what makes the file is read on each click."""

    def __init__(self, view: ButtonViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            dict.fromkeys(
                ("filename", "media_type", "content", "in_job", "prepare", "enabled_if"), self._noop
            )
        )

    @staticmethod
    def _noop(_view: ButtonViewLike, _rendered_object: ComposeButton, _value: object) -> None:
        pass


class TextualDialogButtonRenderer(TextualButtonRenderer):
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
        if self._rendered_object is None:
            self._rendered_object = ComposeButton()
            self._rendered_object.clicked.connect(self._dialog_button.click)

    # each is told its own field's new value, not yet the view's
    def _refresh_button_enabled(
        self, _view: ButtonViewLike, rendered_object: ComposeButton, value: bool
    ) -> None:
        rendered_object.disabled = not (value and not self._dialog_button.is_blocked)

    def _refresh_is_blocked(
        self, _view: ButtonViewLike, rendered_object: ComposeButton, value: bool
    ) -> None:
        rendered_object.disabled = not (self._dialog_button.is_enabled and not value)

    @staticmethod
    def _noop(_view: ButtonViewLike, _rendered_object: ComposeButton, _value: bool) -> None:
        pass  # read on each click


class ProgressBarViewLike(ViewLike, Protocol):
    value: int
    maximum: int | None


class TextualProgressBarRenderer(TextualWidgetRenderer[ProgressBarViewLike, ProgressBar]):
    def __init__(self, view: ProgressBarViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {"value": self._refresh_value, "maximum": self._refresh_maximum}
        )

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            # no time left: neither Qt nor the web estimates one
            self._rendered_object = ProgressBar(show_eta=False)

    @staticmethod
    def _refresh_value(view: ProgressBarViewLike, rendered_object: ProgressBar, value: int) -> None:
        rendered_object.update(progress=ProgressBarView.clamp(value, view.maximum))

    @staticmethod
    def _refresh_maximum(
        view: ProgressBarViewLike, rendered_object: ProgressBar, value: int | None
    ) -> None:
        # no total is Textual's own bar for a task of unknown length
        rendered_object.update(total=value, progress=ProgressBarView.clamp(view.value, value))

"""The web renderers of controls: check boxes, buttons, progress bars and sliders."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any, ClassVar, Final

from markupsafe import Markup
from typing_extensions import Protocol

from composeui.core.renderer import ViewLike
from composeui.core.view import (
    DRAG_REPORT_DELAY_MS,
    RANGE_DASH,
    ButtonVariant,
    DialogButtonView,
    FloatRangeSliderMixin,
    FloatSliderMixin,
    ProgressBarView,
    RangeSliderMixin,
    SliderMixin,
)
from composeui.webcore.webrenderer import WebRenderer

if TYPE_CHECKING:
    from collections.abc import Mapping

    from composeui.core.signal import Signal, SignalNoArgs


class CheckBoxViewLike(ViewLike, Protocol):
    text: str
    is_checked: bool
    toggled: Signal[bool]


class WebCheckBoxRenderer(WebRenderer[CheckBoxViewLike]):
    """A checkbox with its text, posting each toggle.

    The root is a `<div role="group">`, as for a radio group: the box's own `<label>`
    names it with its text, and a row's label names the group. Like a radio group,
    the box is never swapped back after a toggle; it is when the server changes it.
    """

    _role = "checkbox"
    is_labelable = False

    def __init__(self, view: CheckBoxViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "text": self._mark_dirty,
                "is_checked": self._mark_dirty,
            }
        )

    def to_html(self, *, oob: bool = False) -> Markup:
        checked = " checked" if self._view.is_checked else ""
        disabled = "" if self.is_enabled else " disabled"
        # an unchecked box posts no value at all: `checked` is told apart by its presence
        return Markup(
            '<div {root_attributes}{row_attributes} role="group"'
            ' class="flex">'
            '<label class="label cursor-pointer gap-2 text-base-content">'
            '<input type="checkbox" class="checkbox checkbox-sm checkbox-primary"'
            ' name="checked" value="on"{checked} hx-post="/widget/{widget_id}"'
            ' hx-trigger="change" hx-vals=\'{{"event": "change"}}\' hx-swap="none"'
            ' autocomplete="off"{disabled}>'
            "{text}</label></div>"
        ).format(
            root_attributes=self._root_attributes(oob=oob),
            row_attributes=self._row_attributes(),
            checked=checked,
            widget_id=self.widget_id,
            disabled=disabled,
            text=self._view.text,
        )

    def dispatch(self, event: str, form: Mapping[str, str]) -> None:
        if event != "change":
            super().dispatch(event, form)
        is_checked = "checked" in form
        if is_checked == self._view.is_checked:
            return
        with self.stop_refresh():
            self._view.is_checked = is_checked
        self._view.toggled.emit(is_checked)


class ButtonViewLike(ViewLike, Protocol):
    text: str
    variant: ButtonVariant
    clicked: SignalNoArgs


#: each button variant as daisyUI's
_BUTTON_CLASSES: Final[dict[ButtonVariant, str]] = {
    ButtonVariant.PRIMARY: "btn-primary",
    ButtonVariant.SECONDARY: "btn-soft",
    ButtonVariant.DANGER: "btn-error",
}


class WebButtonRenderer(WebRenderer[ButtonViewLike]):
    """A button posting each click; like every control, never swapped back after one."""

    _role = "button"

    def __init__(self, view: ButtonViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update({"text": self._mark_dirty, "variant": self._mark_dirty})

    def to_html(self, *, oob: bool = False) -> Markup:
        disabled = "" if self.is_enabled else " disabled"
        variant = _BUTTON_CLASSES[self._view.variant]
        # `self-start`: as wide as its text, not the page's whole column
        return Markup(
            '<button {root_attributes} type="button"'
            ' class="btn {variant} self-start"'
            """ hx-post="/widget/{widget_id}" hx-vals='{{"event": "click"}}'"""
            ' hx-swap="none"{disabled}>{text}</button>'
        ).format(
            root_attributes=self._root_attributes(oob=oob),
            variant=variant,
            widget_id=self.widget_id,
            disabled=disabled,
            text=self._view.text,
        )

    def dispatch(self, event: str, form: Mapping[str, str]) -> None:
        # a disabled button can't be clicked: a post saying otherwise is refused
        if event != "click" or not self.is_enabled:
            super().dispatch(event, form)
        self._view.clicked.emit()


class WebDownloadRenderer(WebButtonRenderer):
    """A button giving a file: its click posts, and the answer names the file to fetch."""

    _role = "download"

    def __init__(self, view: ButtonViewLike) -> None:
        super().__init__(view)
        # nothing shown: each click reads them
        self._refresh_dispatcher.update(
            dict.fromkeys(("filename", "media_type", "content", "in_job"), self._noop)
        )

    @staticmethod
    def _noop(_view: ButtonViewLike, _rendered_object: str, _value: object) -> None:
        pass


class WebDialogButtonRenderer(WebButtonRenderer):
    """A dialog's own button, e.g. Apply: its click goes through its dialog, which checks first.

    Its dialog swaps closed when the click closes it, as on OK.
    """

    _role = "dialog_button"

    def __init__(self, view: DialogButtonView) -> None:
        super().__init__(view)
        self._dialog_button = view
        # `closes` and `checks` show nothing (each click reads them): a redraw is harmless
        self._refresh_dispatcher.update(
            dict.fromkeys(("is_blocked", "closes", "checks"), self._mark_dirty)
        )

    @property
    def is_enabled(self) -> bool:
        """Whether it can be pressed: enabled, with its dialog, and no check of its fails."""
        return super().is_enabled and not self._dialog_button.is_blocked

    def dispatch(self, event: str, form: Mapping[str, str]) -> None:
        # a disabled button can't be clicked: a post saying otherwise is refused
        if event != "click" or not self.is_enabled:
            WebRenderer.dispatch(self, event, form)
        self._dialog_button.click()


class ProgressBarViewLike(ViewLike, Protocol):
    value: int
    maximum: int | None


class WebProgressBarRenderer(WebRenderer[ProgressBarViewLike]):
    """A `<progress>` bar; one with no value is the browser's own for a task of unknown length."""

    _role = "progress_bar"

    def __init__(self, view: ProgressBarViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update({"value": self._mark_dirty, "maximum": self._mark_dirty})

    def to_html(self, *, oob: bool = False) -> Markup:
        value, maximum = self._view.value, self._view.maximum
        clamped = ProgressBarView.clamp(value, maximum)
        progress = (
            "" if maximum is None else Markup(' value="{}" max="{}"').format(clamped, maximum)
        )
        return Markup('<progress {} class="progress progress-primary w-full"{}></progress>').format(
            self._root_attributes(oob=oob), progress
        )


class SliderViewLike(ViewLike, Protocol):
    value: float
    minimum: float
    maximum: float
    step: float
    is_filled: bool
    value_changed: Signal[float]


class WebSliderRenderer(WebRenderer[SliderViewLike]):
    """A range input posting the handle's moves, its value in an `<output>` on its right.

    The browser stops the handle on each step. The moves are posted debounced
    (`input`) and on release (`change`); meanwhile the page's script keeps the value
    in step (see `page.js`). Beside the track rather than above the handle, and in a
    slot as wide as the widest value. So the row is as tall as a text field's and the
    track keeps its length. The root is a `<div>` holding both, so a row's label names
    the input with `aria-labelledby`. Like every control, never swapped back after a
    move; it is when the server changes it.
    """

    _role = "slider"
    is_labelable = False
    #: the arithmetic of its steps
    _steps: ClassVar[Any] = SliderMixin

    def __init__(self, view: SliderViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "value": self._mark_dirty,
                "minimum": self._mark_dirty,
                "maximum": self._mark_dirty,
                "step": self._mark_dirty,
                "is_filled": self._mark_dirty,
            }
        )

    def to_html(self, *, oob: bool = False) -> Markup:
        minimum, step = self._view.minimum, self._view.step
        last = self._steps.last_position(minimum, self._view.maximum, step)
        position = self._steps.position(self._view.value, minimum, self._view.maximum, step)
        value = self._steps.value_at(position, minimum, step)
        top = self._steps.value_at(last, minimum, step)
        digits = max(
            len(self._steps.shown_text(minimum, minimum, step)),
            len(self._steps.shown_text(top, minimum, step)),
        )
        disabled = "" if self.is_enabled else " disabled"
        input_id = f"{self.widget_id}-input"
        return Markup(
            '<div {root_attributes} class="cui-slider"'
            ' style="--slider-digits: {digits}">'
            '<input id="{input_id}"{row_attributes} type="range" data-slider'
            ' data-decimals="{decimals}"{fill} class="range range-primary" name="value"'
            ' min="{minimum}" max="{top}" step="{step}" value="{value}"'
            ' hx-post="/widget/{widget_id}" hx-trigger="input changed delay:{delay}ms, change"'
            ' data-post-event hx-swap="none" hx-sync="this:queue all"'
            ' autocomplete="off"{disabled}>'
            # read out by the input itself, as its value
            '<output for="{input_id}" class="cui-slider-value" aria-hidden="true">{text}</output>'
            "</div>"
        ).format(
            root_attributes=self._root_attributes(oob=oob),
            digits=digits,
            delay=DRAG_REPORT_DELAY_MS,
            input_id=input_id,
            row_attributes=self._row_attributes(),
            minimum=minimum,
            top=top,
            step=step,
            value=value,
            text=self._steps.shown_text(value, minimum, step),
            decimals=self._steps.decimals(minimum, step),
            fill=Markup() if self._view.is_filled else Markup(' style="--range-fill: 0"'),
            widget_id=self.widget_id,
            disabled=disabled,
        )

    @staticmethod
    def _posted(text: str) -> float | None:
        """Get the number that the page posted, None for anything else."""
        try:
            return int(text)
        except ValueError:
            return None

    def dispatch(self, event: str, form: Mapping[str, str]) -> None:
        if event not in ("input", "change"):
            super().dispatch(event, form)
        posted = self._posted(form.get("value", ""))
        if posted is None:
            return  # a range input always posts a number; nothing else is a move
        minimum, maximum, step = self._view.minimum, self._view.maximum, self._view.step
        position = self._steps.position(posted, minimum, maximum, step)
        value = self._steps.value_at(position, minimum, step)
        # `change` posts the value of a still-debounced `input` too: emitted once
        if value == self._view.value:
            return
        with self.stop_refresh():
            self._view.value = value
        self._view.value_changed.emit(value)


class WebFloatSliderRenderer(WebSliderRenderer):
    """A range input stopping on each decimal step."""

    _steps = FloatSliderMixin

    @staticmethod
    def _posted(text: str) -> float | None:
        try:
            number = float(text)
        except ValueError:
            return None
        return number if math.isfinite(number) else None  # `float` reads "nan" and "inf"


class RangeSliderViewLike(ViewLike, Protocol):
    value: tuple[float, float]
    minimum: float
    maximum: float
    step: float
    low_text: str
    high_text: str
    value_changed: Signal[tuple[float, float]]


class WebRangeSliderRenderer(WebRenderer[RangeSliderViewLike]):
    """Two range inputs on one track, the low and the high handle, their ends on the right.

    The inputs count steps (0 to the last), so the browser stops each handle on a step,
    and a decimal step needs no decimal arithmetic in the page. Each posts both positions
    (`hx-include`), debounced and on release, as the page shows them. Meanwhile the page's
    script stops a handle on the other, and keeps the fill and the ends in step (see
    `page.js`). The server takes the positions by `RangeSliderMixin.moved`. The root is a
    `<div>`: a row's label names the group, and each input its end's text.
    """

    _role = "range_slider"
    is_labelable = False
    #: the rules of its two ends
    _range: ClassVar[Any] = RangeSliderMixin

    def __init__(self, view: RangeSliderViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            dict.fromkeys(
                ("value", "minimum", "maximum", "step", "low_text", "high_text"),
                self._mark_dirty,
            )
        )

    def to_html(self, *, oob: bool = False) -> Markup:
        view, steps = self._view, self._range.step_rules
        minimum, step = view.minimum, view.step
        last = steps.last_position(minimum, view.maximum, step)
        positions = self._range.positions(view.value, minimum, view.maximum, step)
        texts = [
            steps.shown_text(steps.value_at(p, minimum, step), minimum, step) for p in positions
        ]
        widest = max(
            len(steps.shown_text(steps.value_at(end, minimum, step), minimum, step))
            for end in (0, last)
        )
        disabled = "" if self.is_enabled else " disabled"
        inputs = Markup("").join(
            Markup(
                '<input id="{widget_id}-{name}" type="range" class="range range-primary"'
                ' name="{name}" min="0" max="{last}" step="1" value="{position}"'
                ' aria-label="{label}" aria-valuetext="{text}" data-range-end="{name}"'
                ' hx-post="/widget/{widget_id}" hx-trigger="input changed delay:{delay}ms, change"'
                ' hx-include="closest .cui-range-track" data-post-event hx-swap="none"'
                ' hx-sync="closest .cui-range-track:queue all" autocomplete="off"{disabled}>'
            ).format(
                widget_id=self.widget_id,
                delay=DRAG_REPORT_DELAY_MS,
                name=name,
                last=last,
                position=position,
                label=label,
                text=text,
                disabled=disabled,
            )
            for name, position, label, text in zip(
                ("low", "high"), positions, (view.low_text, view.high_text), texts
            )
        )
        return Markup(
            '<div {root_attributes}{row_attributes} role="group" class="cui-slider"'
            ' style="--slider-digits: {digits}">'
            '<div class="cui-range-track" data-first="{minimum}" data-step="{step}"'
            ' data-decimals="{decimals}"{low_on_top}'
            ' style="--range-low: {low}; --range-high: {high}; --range-last: {range_last}">'
            "{inputs}</div>"
            # read out by the inputs themselves, as their values
            '<output class="cui-slider-value" aria-hidden="true">{ends}</output></div>'
        ).format(
            root_attributes=self._root_attributes(oob=oob),
            row_attributes=self._row_attributes(),
            digits=2 * widest + len(RANGE_DASH),
            minimum=minimum,
            step=step,
            decimals=steps.decimals(minimum, step),
            # on one another in the upper half: the low handle on top, which can move down
            low_on_top=Markup(" data-low-on-top")
            if positions[0] == positions[1] and positions[0] > last / 2
            else Markup(),
            low=positions[0],
            high=positions[1],
            range_last=max(1, last),  # the fill divides by it
            inputs=inputs,
            ends=RANGE_DASH.join(texts),
        )

    def dispatch(self, event: str, form: Mapping[str, str]) -> None:
        if event not in ("input", "change"):
            super().dispatch(event, form)
        try:
            positions = (int(form.get("low", "")), int(form.get("high", "")))
        except ValueError:
            return  # the inputs always post their positions; nothing else is a move
        view = self._view
        last = self._range.step_rules.last_position(view.minimum, view.maximum, view.step)
        low, high = (min(max(0, position), last) for position in positions)
        value = self._range.moved(view.value, (low, high), view.minimum, view.maximum, view.step)
        # `change` posts the positions of a still-debounced `input` too: emitted once
        if value == view.value:
            return
        with self.stop_refresh():
            view.value = value
        view.value_changed.emit(view.value)


class WebFloatRangeSliderRenderer(WebRangeSliderRenderer):
    """Two range inputs on one track, stopping on each decimal step."""

    _range = FloatRangeSliderMixin

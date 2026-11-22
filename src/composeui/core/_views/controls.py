"""The check box, the buttons, the progress bar and the sliders."""

from __future__ import annotations

import decimal
import enum
import math
from collections.abc import Callable
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Optional,
    Union,
    cast,
)

import attrs
from typing_extensions import override

from composeui.core._views.base import (
    OMIT,
    UI_TEXT,
    LogType,
    View,
    define_view,
    notify_renderer,
)
from composeui.core._views.files import DownloadedFile, StreamContent
from composeui.core._views.inputs import _RANGE_ENDS
from composeui.core.jobs import Task
from composeui.core.reactivity import (
    follow,
)
from composeui.core.signal import Signal, SignalNoArgs
from composeui.core.translation import (
    T,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from composeui.core._views.main import MainView
    from composeui.core.jobs import Job


#: the most steps a slider takes: Qt's sliders count them in a 32-bit integer
MAX_SLIDER_STEPS = 2**31 - 1
#: the milliseconds a dragged slider's handle rests before the slider reports its value (and
#: on release): a report at each step would make the app's work on it, such as a dashboard
#: drawn again, lag behind the handle
DRAG_REPORT_DELAY_MS = 150


def _check_steps(instance: Any, attribute: attrs.Attribute[Any], value: float) -> None:
    """Reject a range of more than `MAX_SLIDER_STEPS` steps, once `attribute` is `value`."""
    limits = {
        "minimum": instance.minimum,
        "maximum": instance.maximum,
        "step": instance.step,
        attribute.name: value,
    }
    if limits["step"] <= 0:
        return  # no steps to count: the step's own check refuses it
    # the arithmetic of the steps: a range slider's, else the slider's own
    steps = getattr(instance, "step_rules", instance)
    last = steps.last_position(limits["minimum"], limits["maximum"], limits["step"])
    if last > MAX_SLIDER_STEPS:
        msg = (
            f"Cannot set {type(instance).__name__}.{attribute.name} to {value}: the range would "
            f"take {last} steps, more than {MAX_SLIDER_STEPS}. Set a larger step first."
        )
        raise ValueError(msg)


@define_view
class SliderMixin:
    """The fields of a slider: its `value`, its range and its `step`."""

    def _check_step(self, _attribute: attrs.Attribute[Any], step: int) -> None:
        if step <= 0:
            msg = f"Cannot set {type(self).__name__}.step to {step}: it must be positive."
            raise ValueError(msg)

    #: from `minimum` to `maximum` by `step`; shown at its nearest step (see `position`)
    value: int = attrs.field(default=0)
    minimum: int = attrs.field(default=0, validator=[_check_steps])
    #: the last step, if ``maximum - minimum`` is not a whole number of steps, falls short of it
    maximum: int = attrs.field(default=100, validator=[_check_steps])
    step: int = attrs.field(default=1, validator=[_check_step, _check_steps])
    #: the track is drawn in the accent color up to the handle
    is_filled: bool = attrs.field(default=True)
    #: the user moved the handle; not emitted when `value` is set in code
    value_changed: Signal[int] = attrs.Factory(Signal[int])

    @staticmethod
    def last_position(minimum: int, maximum: int, step: int) -> int:
        """Get the steps from `minimum` to the last one at most `maximum`; 0 if none."""
        return max(0, (maximum - minimum) // step)

    @staticmethod
    def position(value: int, minimum: int, maximum: int, step: int) -> int:
        """Get the handle's position, in steps from `minimum`: `value`'s nearest, in range.

        Takes them all, as a renderer refreshes one before the view holds the new value.
        """
        last = SliderMixin.last_position(minimum, maximum, step)
        # a value halfway between two steps goes up, whatever the step (`round` goes even)
        return min(max(0, (value - minimum + step // 2) // step), last)

    @staticmethod
    def value_at(position: int, minimum: int, step: int) -> int:
        """Get the value at `position` steps from `minimum`."""
        return minimum + position * step

    @staticmethod
    def decimals(_minimum: int, _step: int) -> int:
        """Get the decimals that a value shows: none."""
        return 0

    @staticmethod
    def shown_text(value: int, _minimum: int, _step: int) -> str:
        """Get the text that shows `value`."""
        return str(value)


@define_view
class SliderView(SliderMixin, View):
    """A whole number picked by dragging a handle, e.g. a number of workers.

    Its value is shown beside the track, so that its row is no taller than a field's.
    """

    _renderer_key = "slider"


#: wider than the digits between any two floats, so that no count of steps is rounded
_EXACT_CONTEXT = decimal.Context(prec=1000)


def _exact(number: float) -> decimal.Decimal:
    # by its text: `Decimal(0.1)` would hold the binary float's 55 decimals, not 0.1
    return decimal.Decimal(str(number))


@define_view
class FloatSliderMixin:
    """The fields of a decimal slider: its `value`, its range and its `step`."""

    def _check_finite(self, attribute: attrs.Attribute[Any], number: float) -> None:
        if not math.isfinite(number):
            msg = f"Cannot set {type(self).__name__}.{attribute.name} to {number}: not finite."
            raise ValueError(msg)

    def _check_step(self, _attribute: attrs.Attribute[Any], step: float) -> None:
        if step <= 0:
            msg = f"Cannot set {type(self).__name__}.step to {step}: it must be positive."
            raise ValueError(msg)

    #: from `minimum` to `maximum` by `step`; shown at its nearest step
    value: float = attrs.field(default=0.0, validator=[_check_finite])
    minimum: float = attrs.field(default=0.0, validator=[_check_finite, _check_steps])
    #: the last step, if ``maximum - minimum`` is not a whole number of steps, falls short of it
    maximum: float = attrs.field(default=1.0, validator=[_check_finite, _check_steps])
    step: float = attrs.field(default=0.1, validator=[_check_finite, _check_step, _check_steps])
    #: the track is drawn in the accent color up to the handle
    is_filled: bool = attrs.field(default=True)
    #: the user moved the handle; not emitted when `value` is set in code
    value_changed: Signal[float] = attrs.Factory(Signal[float])

    @staticmethod
    def last_position(minimum: float, maximum: float, step: float) -> int:
        """Get the steps from `minimum` to the last one at most `maximum`; 0 if none."""
        with decimal.localcontext(_EXACT_CONTEXT):
            return max(0, int((_exact(maximum) - _exact(minimum)) // _exact(step)))

    @staticmethod
    def position(value: float, minimum: float, maximum: float, step: float) -> int:
        """Get the handle's position, in steps from `minimum`: `value`'s nearest, in range."""
        last = FloatSliderMixin.last_position(minimum, maximum, step)
        with decimal.localcontext(_EXACT_CONTEXT):
            # a value halfway between two steps goes up, as on `SliderMixin`
            exact_step = _exact(step)
            steps = (_exact(value) - _exact(minimum) + exact_step / 2) // exact_step
            return min(max(0, int(steps)), last)

    @staticmethod
    def value_at(position: int, minimum: float, step: float) -> float:
        """Get the value at `position` steps from `minimum`: 3 steps of 0.1 are 0.3."""
        with decimal.localcontext(_EXACT_CONTEXT):
            return float(_exact(minimum) + position * _exact(step))

    @staticmethod
    def decimals(minimum: float, step: float) -> int:
        """Get the decimals that every value shows: those of `minimum` or `step`, the most."""
        exponents = (_exact(minimum).as_tuple().exponent, _exact(step).as_tuple().exponent)
        return max(0, *(-int(exponent) for exponent in exponents))

    @staticmethod
    def shown_text(value: float, minimum: float, step: float) -> str:
        """Get the text that shows `value`, with the same decimals at every step."""
        return f"{_exact(value):.{FloatSliderMixin.decimals(minimum, step)}f}"


@define_view
class FloatSliderView(FloatSliderMixin, View):
    """A decimal number picked by dragging a handle, e.g. an opacity from 0 to 1.

    Its value is shown beside the track, with the decimals of its `step`.
    """

    _renderer_key = "float_slider"


def _int_pair(pair: Iterable[int]) -> tuple[int, int]:
    """Get a range's ends as a tuple, e.g. from a list; its validator checks them."""
    return cast("tuple[int, int]", tuple(pair))


def _float_pair(pair: Iterable[float]) -> tuple[float, float]:
    """Get a range's ends as a tuple of floats, e.g. from a list of ints."""
    return cast("tuple[float, float]", tuple(float(end) for end in pair))


#: between the two ends of a range, as the backends show them: an en dash
RANGE_DASH = " \u2013 "


def _check_range(instance: Any, attribute: attrs.Attribute[Any], pair: tuple[Any, ...]) -> None:
    """Reject a range that isn't two ends, or whose low end is above its high end."""
    if len(pair) != _RANGE_ENDS:
        msg = f"Cannot set {type(instance).__name__}.{attribute.name} to {pair}: not two ends."
        raise ValueError(msg)
    low, high = pair
    if low > high:
        msg = (
            f"Cannot set {type(instance).__name__}.{attribute.name} to {pair}: its low end is "
            "above its high end."
        )
        raise ValueError(msg)


class _RangeSliderBase:
    """What both range sliders do with their two ends, by the arithmetic of their steps."""

    #: the arithmetic of the steps: `SliderMixin`, or `FloatSliderMixin` for decimals
    step_rules: ClassVar[Any] = SliderMixin

    @classmethod
    def positions(
        cls, value: tuple[float, float], minimum: float, maximum: float, step: float
    ) -> tuple[int, int]:
        """Get the handles' positions, in steps from `minimum`: each end's nearest, in range.

        Takes them all, as a renderer refreshes one before the view holds the new value.
        """
        low, high = (cls.step_rules.position(end, minimum, maximum, step) for end in value)
        return low, high

    @classmethod
    def moved(
        cls,
        current: tuple[float, float],
        positions: tuple[int, int],
        minimum: float,
        maximum: float,
        step: float,
    ) -> tuple[Any, Any]:
        """Get the range that the user moved the handles to, at these `positions`.

        A handle moved past the other stops on it: the two never cross. Both moved at once,
        as a stale page can post them, they are put in order.
        """
        low, high = positions
        if low > high:
            was_low, was_high = cls.positions(current, minimum, maximum, step)
            if high == was_high:
                low = high  # the low handle moved past the high one
            elif low == was_low:
                high = low
            else:
                low, high = high, low
        return cls.step_rules.value_at(low, minimum, step), cls.step_rules.value_at(
            high, minimum, step
        )


@define_view
class RangeSliderMixin(_RangeSliderBase):
    """The fields of a range slider: its `value`, a pair of ends, its range and its `step`."""

    def _check_step(self, _attribute: attrs.Attribute[Any], step: int) -> None:
        if step <= 0:
            msg = f"Cannot set {type(self).__name__}.step to {step}: it must be positive."
            raise ValueError(msg)

    #: the low and the high end, from `minimum` to `maximum` by `step`; each shown at its
    #: nearest step; the low end can't be above the high one
    value: tuple[int, int] = attrs.field(
        default=(0, 100),
        converter=_int_pair,
        validator=[_check_range],
        on_setattr=[attrs.setters.convert, attrs.setters.validate, notify_renderer],
    )
    minimum: int = attrs.field(default=0, validator=[_check_steps])
    #: the last step, if ``maximum - minimum`` is not a whole number of steps, falls short of it
    maximum: int = attrs.field(default=100, validator=[_check_steps])
    step: int = attrs.field(default=1, validator=[_check_step, _check_steps])
    #: the names of the low and the high handle, as a screen reader reads them out
    low_text: str = attrs.field(default=T("From"), metadata={UI_TEXT: True})
    high_text: str = attrs.field(default=T("To"), metadata={UI_TEXT: True})
    #: the user moved a handle; not emitted when `value` is set in code
    value_changed: Signal[tuple[int, int]] = attrs.Factory(Signal[tuple[int, int]])


@define_view
class RangeSliderView(RangeSliderMixin, View):
    """A range of whole numbers picked by dragging two handles, e.g. the hours to show.

    Its two ends are shown beside the track, so that its row is no taller than a field's.
    """

    _renderer_key = "range_slider"


@define_view
class FloatRangeSliderMixin(_RangeSliderBase):
    """The fields of a decimal range slider: its `value`, a pair of ends, its range and step."""

    step_rules = FloatSliderMixin

    def _check_finite(self, attribute: attrs.Attribute[Any], number: float) -> None:
        if not math.isfinite(number):
            msg = f"Cannot set {type(self).__name__}.{attribute.name} to {number}: not finite."
            raise ValueError(msg)

    def _check_finite_pair(
        self, attribute: attrs.Attribute[Any], pair: tuple[float, float]
    ) -> None:
        for end in pair:
            self._check_finite(attribute, end)

    def _check_step(self, _attribute: attrs.Attribute[Any], step: float) -> None:
        if step <= 0:
            msg = f"Cannot set {type(self).__name__}.step to {step}: it must be positive."
            raise ValueError(msg)

    #: the low and the high end, from `minimum` to `maximum` by `step`; each shown at its
    #: nearest step; the low end can't be above the high one
    value: tuple[float, float] = attrs.field(
        default=(0.0, 1.0),
        converter=_float_pair,
        validator=[_check_range, _check_finite_pair],
        on_setattr=[attrs.setters.convert, attrs.setters.validate, notify_renderer],
    )
    minimum: float = attrs.field(default=0.0, validator=[_check_finite, _check_steps])
    #: the last step, if ``maximum - minimum`` is not a whole number of steps, falls short of it
    maximum: float = attrs.field(default=1.0, validator=[_check_finite, _check_steps])
    step: float = attrs.field(default=0.1, validator=[_check_finite, _check_step, _check_steps])
    #: the names of the low and the high handle, as a screen reader reads them out
    low_text: str = attrs.field(default=T("From"), metadata={UI_TEXT: True})
    high_text: str = attrs.field(default=T("To"), metadata={UI_TEXT: True})
    #: the user moved a handle; not emitted when `value` is set in code
    value_changed: Signal[tuple[float, float]] = attrs.Factory(Signal[tuple[float, float]])


@define_view
class FloatRangeSliderView(FloatRangeSliderMixin, View):
    """A range of decimal numbers picked by dragging two handles, e.g. the trips' distances.

    Its two ends are shown beside the track, with the decimals of its `step`.
    """

    _renderer_key = "float_range_slider"


@define_view
class CheckBoxMixin:
    """The fields of a check box: its `text`, its state and `toggled`."""

    #: shown next to the box
    text: str = attrs.field(default="", metadata={UI_TEXT: True})
    is_checked: bool = False
    #: the user checked or unchecked the box; not emitted when `is_checked` is set in code
    toggled: Signal[bool] = attrs.Factory(Signal[bool])
    #: the views shown only while the box is checked (see `shows`)
    _shown: list[View] = attrs.field(
        factory=list[View], init=False, repr=False, eq=False, metadata={OMIT: True}
    )

    @property
    def shown_views(self) -> list[View]:
        """Get the views shown only while the box is checked (see `shows`)."""
        return list(self._shown)

    def shows(self, *views: View) -> None:
        """Show `views` only while the box is checked, from now on, e.g. an optional part.

        They follow the box however it changes: as the user clicks it, as code sets
        `is_checked`, and as a study opens or New starts one.
        """
        self._shown.extend(views)

        def show_checked() -> None:
            is_checked = self.is_checked
            for view in views:
                view.is_visible = is_checked

        # as a reactive method of the box: `is_checked` is its input
        follow(cast("View", self), "shows", show_checked)


@define_view
class CheckBoxView(CheckBoxMixin, View):
    """A check box with a text, for an option that is on or off."""

    _renderer_key = "checkbox"


class ButtonVariant(enum.Enum):
    """How much a button stands out, for the user to tell actions apart."""

    #: the page's main action, e.g. submitting its form
    PRIMARY = enum.auto()
    #: an action beside the main one
    SECONDARY = enum.auto()
    #: an action destroying something, e.g. removing rows
    DANGER = enum.auto()


@define_view
class ButtonView(View):
    """A button the user clicks to act on what the page shows, e.g. to submit a form."""

    _renderer_key = "button"
    # as wide as its text in a row: a button spanning a whole row is rarely wanted
    default_stretch = 0

    text: str = attrs.field(default="", metadata={UI_TEXT: True})
    variant: ButtonVariant = attrs.field(default=ButtonVariant.PRIMARY)
    #: the user clicked the button
    clicked: SignalNoArgs = attrs.Factory(SignalNoArgs)


#: what a `DownloadView` makes: the file, or the file with its name and type
_Download = Union[bytes, Path, StreamContent, DownloadedFile]


@define_view
class DownloadView(ButtonView):
    """A button that gives the user a file that the app makes on the click, e.g. a report.

    The click calls `content`, which returns the file's bytes, the path of a file that the
    app wrote, or a `StreamContent`, which writes a large file as the user receives it. To
    name the file at the click, e.g. after a selected run, it returns a `DownloadedFile`
    instead, whose name and type replace `filename` and `media_type`. Then the main view
    gives the file (`MainView.download`): the web downloads it, and Qt and Textual ask where
    to save it. With `in_job`, `content` runs in a job, and the button is disabled until the
    file is made; a notification says why it failed.
    """

    _renderer_key = "download"

    variant: ButtonVariant = attrs.field(default=ButtonVariant.SECONDARY)
    #: the name offered for the file, unless `content` returns a `DownloadedFile`
    filename: str = attrs.field(default="download", metadata={OMIT: True})
    #: what the file holds, e.g. "text/csv"; guessed from `filename` when None
    media_type: Optional[str] = attrs.field(default=None, metadata={OMIT: True})
    #: makes the file: its bytes, the path of a file the app wrote, a `StreamContent` that
    #: writes it as the user receives it, or a `DownloadedFile` that also names it; None
    #: gives nothing
    content: Optional[Callable[[], _Download]] = attrs.field(
        default=None, eq=False, repr=False, metadata={OMIT: True}
    )
    #: whether `content` runs in a job, for a file that takes a while to make
    in_job: bool = attrs.field(default=False, metadata={OMIT: True})
    #: makes the file in a job, built at the first click with `in_job`
    _task: Optional[Task[Any, Any, Any]] = attrs.field(
        default=None, init=False, repr=False, eq=False, metadata={OMIT: True}
    )

    @override
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.clicked.connect(self._give)

    def _give(self, main_view: MainView) -> None:
        content = self.content
        if content is None:
            return
        if not self.in_job:
            self._made(content(), main_view)
            return
        if self._task is None:
            self._task = self.build_task(_make)
            self._task.disables(self)
            self._task.finished.connect(self._made)
            self._task.failed.connect(self._failed)
        self._task.start(content)

    def _made(self, content: _Download, main_view: MainView) -> None:
        if isinstance(content, DownloadedFile):
            main_view.download(content.filename, content.content, content.media_type)
        else:
            main_view.download(self.filename, content, self.media_type)

    def _failed(self, error: Exception, main_view: MainView) -> None:
        failed = self.tr("Can't make {name}: {error}.")
        main_view.notify(failed.format(name=self.filename, error=error), LogType.ERROR)


def _make(_job: Job[_Download, Any], content: Callable[[], _Download]) -> _Download:
    """Make a `DownloadView`'s file, in its job."""
    return content()


@define_view
class ProgressBarView(View):
    """How far a long task has gone, e.g. a computation working through its cases."""

    _renderer_key = "progress_bar"

    def _check_maximum(self, _attribute: attrs.Attribute[Any], maximum: Optional[int]) -> None:
        if maximum is not None and maximum <= 0:
            msg = f"Cannot set {type(self).__name__}.maximum to {maximum}: it must be positive."
            raise ValueError(msg)

    #: steps done, from 0 to `maximum`; shown clamped to that range (see `clamp`)
    value: int = attrs.field(default=0)
    #: steps the task takes; None while unknown, the bar then only showing that it runs
    maximum: Optional[int] = attrs.field(default=100, validator=[_check_maximum])

    @staticmethod
    def clamp(value: int, maximum: Optional[int]) -> int:
        """Get `value` within the bar's range of `maximum` steps: a count may overshoot.

        Takes both, as a renderer refreshes one before the view holds the new value.
        """
        value = max(0, value)
        return value if maximum is None else min(value, maximum)


@define_view
class DialogButtonView(ButtonView):
    """A button of a dialog's own, between Cancel and OK, e.g. Apply: a field of the dialog.

    Clicking it fires `clicked`, and the dialog stays open. With `closes`, the dialog closes
    once `clicked` has fired, without `accepted` or `rejected`, unless the app's work refused
    the change in it (`OkCancelDialogView.refusing`). With `checks`, it runs the dialog's
    checks first, as OK does: it does nothing while one fails, and can't be pressed
    meanwhile (`is_blocked`).
    """

    _renderer_key = "dialog_button"

    variant: ButtonVariant = attrs.field(default=ButtonVariant.SECONDARY)
    #: whether clicking it closes the dialog
    closes: bool = attrs.field(default=False)
    #: whether it runs the dialog's checks first, and waits for them to pass
    checks: bool = attrs.field(default=True)
    #: set by its dialog: it checks, and a check fails, so it can't be pressed
    is_blocked: bool = attrs.field(default=False, init=False)
    #: its dialog's answer to a click, once the dialog is built; not the dialog, not a child
    _answer_click: Optional[Callable[[], None]] = attrs.field(
        default=None, init=False, repr=False, eq=False, metadata={OMIT: True}
    )

    def click(self) -> None:
        """Act as the user's click: through its dialog, which checks and closes as asked."""
        if self._answer_click is None:
            self.clicked.emit()
        else:
            self._answer_click()

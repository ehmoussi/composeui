"""The chart view and its values: series, axes and reference lines."""

from __future__ import annotations

import datetime
import enum
import math
from typing import (
    TYPE_CHECKING,
    Any,
    Optional,
    Union,
)

import attrs

from composeui.core._views.base import (
    _COLOR_PATTERN,
    OMIT,
    UI_TEXT,
    ItemList,
    View,
    _check_height,
    define_view,
)
from composeui.core.signal import Signal
from composeui.core.translation import (
    T,
    Translate,
    translate_again,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence


def _to_floats(values: Iterable[float]) -> list[float]:
    """Get `values` as a new list of floats, e.g. from a tuple or a numpy array."""
    return ItemList((float(value) for value in values), "Series.y")


#: a value of a chart's axis: a number, or on a time axis (`Scale.TIME`) a date or a time too
ChartValue = Union[float, datetime.date]

_EPOCH = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)
#: a day of a time axis (`Scale.TIME`), whose values are seconds
SECONDS_PER_DAY = 86400


def _chart_value(value: ChartValue) -> float:
    """Get a value as a chart holds it: a date or a time as its seconds since 1970, in UTC.

    A naive time is taken as UTC, so the chart shows it as written; an aware one is shown
    at its instant, in UTC. A date is its midnight.
    """
    if isinstance(value, datetime.datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=datetime.timezone.utc)
        return (aware - _EPOCH).total_seconds()
    if isinstance(value, datetime.date):
        return float((value - _EPOCH.date()).days * SECONDS_PER_DAY)
    return float(value)


def _to_chart_values(values: Iterable[ChartValue]) -> list[float]:
    return ItemList((_chart_value(value) for value in values), "Series.x")


class ChartKind(enum.Enum):
    """How a `Series` draws its points."""

    #: joined by a line, e.g. a result against time
    LINE = enum.auto()
    #: as dots, e.g. measurements over a model's curve
    SCATTER = enum.auto()
    #: as bars, one at each x: beside the other series' bars there, in a group
    BAR = enum.auto()


class BarMode(enum.Enum):
    """How a `ChartView` places the bars of its series at an x."""

    #: beside each other, in a group
    GROUPED = enum.auto()
    #: on top of each other, e.g. the parts of a total: the values over 0 up from it, those
    #: under 0 down. Each y axis has its own stack
    STACKED = enum.auto()


#: the share of the room between two x that a group of bars takes
BAR_GROUP_WIDTH = 0.8


@attrs.frozen
class Series:
    """A layer of a `ChartView`: its points, x against y, under `name` in the legend.

    Make one with `line`, `scatter` or `bars`. A chart draws its series over the same
    axes, e.g. a line over bars. A point whose x or y is NaN is not drawn: a line has a
    gap there.
    """

    def _check_y(self, _attribute: attrs.Attribute[Any], y: list[float]) -> None:
        if len(y) != len(self.x):
            msg = f"Cannot make the series {self.name!r}: {len(self.x)} x for {len(y)} y."
            raise ValueError(msg)

    def _check_color(self, _attribute: attrs.Attribute[Any], color: Optional[str]) -> None:
        if color is not None and _COLOR_PATTERN.fullmatch(color) is None:
            msg = f"Cannot color the series {self.name!r} {color!r}: give it as #rrggbb."
            raise ValueError(msg)

    #: the legend's entry
    name: str
    #: on a time axis (`Scale.TIME`), seconds since 1970 in UTC; given as dates or times too
    x: list[float] = attrs.field(converter=_to_chart_values)
    y: list[float] = attrs.field(converter=_to_floats, validator=[_check_y])
    #: how it is drawn: as a line, dots or bars
    kind: ChartKind = attrs.field(kw_only=True)
    #: its color, as #rrggbb, the same in every theme, e.g. a logo's or a code's; None:
    #: the backend's theme picks it
    color: Optional[str] = attrs.field(default=None, kw_only=True, validator=[_check_color])
    #: whether the area between its line and 0 is filled, e.g. a shape
    fill: bool = attrs.field(default=False, kw_only=True)
    #: whether its line holds each value until the next point, in steps, e.g. the jobs
    #: running over time; with `fill`, a step area
    step: bool = attrs.field(default=False, kw_only=True)
    #: with `fill`, the area's color, as #rrggbb, e.g. a pale area under a strong line;
    #: None: the color of its line
    fill_color: Optional[str] = attrs.field(default=None, kw_only=True, validator=[_check_color])
    #: whether its y are on the chart's second y axis, `ChartView.y2`, at the right
    on_y2: bool = attrs.field(default=False, kw_only=True)

    @classmethod
    def line(  # noqa: PLR0913 (a line's options, each by its name)
        cls,
        name: str,
        x: Iterable[ChartValue],
        y: Iterable[float],
        *,
        color: Optional[str] = None,
        fill: bool = False,
        step: bool = False,
        fill_color: Optional[str] = None,
        on_y2: bool = False,
    ) -> Series:
        """Make a series drawn as a line through its points, e.g. a result against time."""
        return cls(
            name,
            x,
            y,
            kind=ChartKind.LINE,
            color=color,
            fill=fill,
            step=step,
            fill_color=fill_color,
            on_y2=on_y2,
        )

    @classmethod
    def scatter(
        cls,
        name: str,
        x: Iterable[ChartValue],
        y: Iterable[float],
        *,
        color: Optional[str] = None,
        on_y2: bool = False,
    ) -> Series:
        """Make a series drawn as dots, e.g. measurements over a model's curve."""
        return cls(name, x, y, kind=ChartKind.SCATTER, color=color, on_y2=on_y2)

    @classmethod
    def bars(
        cls,
        name: str,
        values: Iterable[float],
        *,
        x: Optional[Iterable[ChartValue]] = None,
        color: Optional[str] = None,
        on_y2: bool = False,
    ) -> Series:
        """Make a series drawn as bars: a bar per value, in its chart's `categories` in order.

        With `x`, a bar at each of them instead: a category's index, or a value of the x
        axis of a chart without categories.
        """
        heights = list(values)
        return cls(
            name,
            range(len(heights)) if x is None else x,
            heights,
            kind=ChartKind.BAR,
            color=color,
            on_y2=on_y2,
        )


class LineStyle(enum.Enum):
    """How a reference line is drawn; a terminal draws each solid."""

    SOLID = enum.auto()
    DASHED = enum.auto()
    DOTTED = enum.auto()
    #: dashes and dots in turn
    DASH_DOT = enum.auto()


@attrs.frozen
class ReferenceLine:
    """A line across a `ChartView` at a value, e.g. a capacity ("Max: 40") or now.

    It is no series: not in the legend, but labeled beside itself. The chart's range
    takes it in, so it shows even away from the data.
    """

    def _check_color(self, _attribute: attrs.Attribute[Any], color: Optional[str]) -> None:
        if color is not None and _COLOR_PATTERN.fullmatch(color) is None:
            msg = f"Cannot color the reference line {self.label!r} {color!r}: give it as #rrggbb."
            raise ValueError(msg)

    #: where it crosses its axis: a y, or an x if `vertical` (with categories, an index;
    #: on a time axis, a date or a time too)
    value: float = attrs.field(converter=_chart_value)
    #: shown beside it, e.g. "Max: 40"; empty: none
    label: str = ""
    #: whether it stands at an x, across the y axis, rather than lying at a y
    vertical: bool = False
    #: its color, as #rrggbb, the same in every theme; None: the theme's text color
    color: Optional[str] = attrs.field(default=None, validator=[_check_color])
    #: dashed by default: told apart from the series, which are solid
    style: LineStyle = LineStyle.DASHED
    #: whether its y is on the chart's second y axis, `ChartView.y2`; not a vertical line's
    on_y2: bool = attrs.field(default=False, kw_only=True)

    @property
    def is_on_y2(self) -> bool:
        """Tell whether it lies at a y of the second y axis: a vertical one stands at an x."""
        return self.on_y2 and not self.vertical


class Scale(enum.Enum):
    """How an `Axis` places its values."""

    #: evenly, a value's distance from another by their difference
    LINEAR = enum.auto()
    #: by their logarithm, e.g. a decay over decades; it shows only values over 0
    LOG = enum.auto()
    #: as dates and times, e.g. measurements over a week: an x axis' only. Its values are
    #: seconds since 1970 in UTC, given as `datetime.date` or `datetime.datetime` too
    TIME = enum.auto()


def _to_bound(value: Optional[ChartValue]) -> Optional[float]:
    return None if value is None else _chart_value(value)


@attrs.frozen
class Axis:
    """An axis of a `ChartView`: its title, its unit and how it places its values.

    E.g. ``Axis("Time", unit="s")``, labeled "Time (s)". The chart shows the unit with
    the values the user hovers too. Assign a new one to change it:
    ``chart.y = attrs.evolve(chart.y, scale=Scale.LOG)``.

    Its range fits the chart's data, unless the app gives a bound: ``minimum=0`` starts
    it at 0, its top still fitting the data. A bound wins over what else widens the
    range, e.g. a reference line or bars standing on 0. The user's zoom still moves past
    it, and back out to it. An x axis of categories has no bounds.
    """

    title: str = ""
    #: shown after the title, as "Time (s)", and with the values the user hovers
    unit: str = attrs.field(default="", kw_only=True)
    scale: Scale = attrs.field(default=Scale.LINEAR, kw_only=True)
    #: where it starts, e.g. 0 for a load that is never negative; None: it fits the data
    minimum: Optional[float] = attrs.field(default=None, kw_only=True, converter=_to_bound)
    #: where it ends, e.g. 100 for a percentage; None: it fits the data
    maximum: Optional[float] = attrs.field(default=None, kw_only=True, converter=_to_bound)

    def __attrs_post_init__(self) -> None:
        bounds = [bound for bound in (self.minimum, self.maximum) if bound is not None]
        if not all(math.isfinite(bound) for bound in bounds):
            msg = f"Cannot bound the axis {self.title!r} at {bounds}: give finite numbers."
            raise ValueError(msg)
        if self.is_log and not all(bound > 0 for bound in bounds):
            msg = f"Cannot bound the log axis {self.title!r} at {bounds}: it shows only > 0."
            raise ValueError(msg)
        if (
            self.minimum is not None
            and self.maximum is not None
            and not self.minimum < self.maximum
        ):
            msg = f"Cannot bound the axis {self.title!r} from {self.minimum} to {self.maximum}."
            raise ValueError(msg)

    @property
    def is_time(self) -> bool:
        """Tell whether it shows dates and times (`Scale.TIME`)."""
        return self.scale is Scale.TIME

    @property
    def has_bounds(self) -> bool:
        """Tell whether the app bounds it, at one end or both."""
        return self.minimum is not None or self.maximum is not None

    def bounded(self, low: float, high: float) -> tuple[float, float]:
        """Get the range from `low` to `high`, which fit the data, at the axis' bounds.

        A bound past the data's other end leaves the axis a unit (a power of 10 on a log
        axis) on its side, rather than no range.
        """
        if self.minimum is not None:
            low = self.minimum
        if self.maximum is not None:
            high = self.maximum
        if low < high:
            return low, high
        if self.maximum is None:
            return low, low * 10 if self.is_log else low + 1
        return (high / 10 if self.is_log else high - 1), high

    @property
    def is_log(self) -> bool:
        """Tell whether it is a log axis, which shows only values over 0."""
        return self.scale is Scale.LOG

    @property
    def label(self) -> str:
        """Get its label: its title with its unit, as "Time (s)"."""
        if self.unit == "":
            return self.title
        return f"({self.unit})" if self.title == "" else f"{self.title} ({self.unit})"

    def translated(self, translate: Translate) -> Axis:
        """Get it with its title translated again; itself if `tr` didn't translate it."""
        title = translate_again(self.title, translate)
        return self if title is self.title else attrs.evolve(self, title=title)


def _check_value_axis(view: View, attribute: attrs.Attribute[Any], axis: Axis) -> None:
    if axis.is_time:
        msg = f"Cannot show {type(view).__name__}.{attribute.name} as times: only x can."
        raise ValueError(msg)
    if axis.is_log and getattr(view, "bar_mode", BarMode.GROUPED) is BarMode.STACKED:
        msg = f"Cannot make {type(view).__name__}.{attribute.name} a log axis: bars stack on 0."
        raise ValueError(msg)


def _check_bar_mode(view: View, _attribute: attrs.Attribute[Any], mode: BarMode) -> None:
    axes = [getattr(view, name) for name in ("y", "y2")]
    if mode is BarMode.STACKED and any(axis.is_log for axis in axes):
        msg = f"Cannot stack the bars of {type(view).__name__} on a log axis: they stack on 0."
        raise ValueError(msg)


def _check_horizontal(view: View, attribute: attrs.Attribute[Any], value: object) -> None:
    """Check that a horizontal chart holds what it draws: bars alone, on `y`, at numbers."""
    chart = {name: getattr(view, name) for name in ("horizontal", "x", "series", "reference_lines")}
    chart[attribute.name] = value
    if not chart["horizontal"]:
        return
    name = type(view).__name__
    for curve in chart["series"]:
        if curve.kind is not ChartKind.BAR:
            msg = f"Cannot show the series {curve.name!r} in a horizontal {name}: only bars."
            raise ValueError(msg)
        if curve.on_y2:
            msg = f"Cannot show the series {curve.name!r} on y2 in a horizontal {name}: only y."
            raise ValueError(msg)
    for line in chart["reference_lines"]:
        if line.is_on_y2:
            msg = f"Cannot show the line {line.label!r} on y2 in a horizontal {name}: only y."
            raise ValueError(msg)
    if chart["x"].is_time:
        msg = f"Cannot show {name}.x as times in a horizontal chart: only numbers."
        raise ValueError(msg)


#: a time axis' round steps between two ticks, in seconds, each with its labels' format
_TIME_STEPS = (
    *((seconds, "%H:%M:%S") for seconds in (1, 2, 5, 10, 15, 30)),
    *((minutes * 60, "%m-%d %H:%M") for minutes in (1, 2, 5, 10, 15, 30)),
    *((hours * 3600, "%m-%d %H:%M") for hours in (1, 2, 3, 6, 12)),
    *((days * SECONDS_PER_DAY, "%Y-%m-%d") for days in (1, 2, 7, 14, 30, 91, 182)),
)


#: past it, a float's digits no longer tell the whole number it is (see `ChartView.is_whole`)
_WHOLE_LIMIT = 1e15


@define_view
class ChartView(View):
    """A chart of results, e.g. a quantity against time or a swept dimension.

    The view holds data and labels. Each backend draws it in its own theme's colors and
    fonts, unless a series has a color of its own (`Series.color`). Assign a new `series`
    list to redraw it, e.g. when a job adds points. The user's zoom stays, where the
    backend has one.

    Its series are layers over the same axes, each drawn as its own kind: a line, dots
    or bars. With `categories`, the x axis shows them, and a series' x is the index of a
    category. The bars at an x stand beside each other, in a group, or stacked
    (`bar_mode`). A chart of bars alone can lie them along its y axis (`horizontal`).

    Its axes, `x` and `y`, hold their titles, units and scales (see `Axis`). They are the
    app's, as a title is: a study doesn't save them. A series or a reference line with
    `on_y2` is on a second y axis, `y2`, at the right, which shows once one is on it, e.g.
    a revenue over the orders it comes from.

    A log axis (`Scale.LOG`) leaves out the values it can't show, those <= 0. A point
    at such an x isn't drawn, and such a y leaves a gap (see `drawn_points`). A reference
    line at such a value isn't drawn either (see `drawn_lines`). So a job's points never
    make the chart fail. An x axis that shows categories or bars is never a log axis.

    A time x axis (`Scale.TIME`) shows its values, seconds since 1970, as dates and times
    in UTC: as written, when given as naive `datetime.datetime` values.
    """

    _renderer_key = "chart"

    title: str = attrs.field(default="", metadata={UI_TEXT: True})
    x: Axis = attrs.field(factory=Axis, validator=[_check_horizontal], metadata={UI_TEXT: True})
    y: Axis = attrs.field(factory=Axis, validator=[_check_value_axis], metadata={UI_TEXT: True})
    #: the second y axis, at the right, of the series and reference lines with `on_y2`
    y2: Axis = attrs.field(factory=Axis, validator=[_check_value_axis], metadata={UI_TEXT: True})
    series: list[Series] = attrs.field(factory=list[Series], validator=[_check_horizontal])
    #: lines at values, e.g. a limit, drawn over the series
    reference_lines: list[ReferenceLine] = attrs.field(
        factory=list[ReferenceLine], validator=[_check_horizontal]
    )
    #: what the x axis shows instead of numbers, by the index each series' x names
    categories: list[str] = attrs.field(factory=list[str])
    #: how the bars at an x stand: beside each other, or stacked, on linear y axes. The
    #: app's layout, not a study's
    bar_mode: BarMode = attrs.field(
        default=BarMode.GROUPED, validator=[_check_bar_mode], metadata={OMIT: True}
    )
    #: whether the bars lie along the value axis, `y`, drawn at the bottom, with `x` down
    #: the left side, its first category at the top, e.g. for long names. Bars alone, on
    #: `y`. The app's layout, not a study's
    horizontal: bool = attrs.field(
        default=False, validator=[_check_horizontal], metadata={OMIT: True}
    )
    #: the action saving the chart as a report's image (see `composeui.core.chartimage`),
    #: where the backend has one: with the `report` extra installed
    save_image_text: str = attrs.field(default=T("Save Image"), metadata={UI_TEXT: True})
    #: its height on screen, in pixels (a terminal's rows of about 16), e.g. to keep a
    #: shape's proportions; None: the backend's own. The app's layout, not a study's
    height: Optional[int] = attrs.field(
        default=None, validator=[_check_height], metadata={OMIT: True}
    )
    #: the user clicked the chart at a point, as the axes' values (x, then y), e.g. to
    #: pick a curve's point; where the backend has a pointer: Qt and the web, not Textual
    clicked: Signal[float, float] = attrs.Factory(Signal[float, float])

    @staticmethod
    def is_x_log(x: Axis, categories: list[str], series: list[Series]) -> bool:
        """Tell whether the x axis is drawn as a log axis: not one of categories or bars.

        Takes the chart's values, as a renderer refreshes each before the view holds it.
        """
        return (
            x.is_log
            and len(categories) == 0
            and all(curve.kind is not ChartKind.BAR for curve in series)
        )

    @staticmethod
    def is_x_time(x: Axis, categories: list[str]) -> bool:
        """Tell whether the x axis shows dates and times: not one of categories."""
        return x.is_time and len(categories) == 0

    @staticmethod
    def time_format(values: Iterable[float]) -> str:
        """Get the `strftime` format that shows these times: the date alone if all are dates.

        Then with hours and minutes, and seconds only if some have them. NaN is no time.
        """
        seconds = [value for value in values if math.isfinite(value)]
        if all(value % SECONDS_PER_DAY == 0 for value in seconds):
            return "%Y-%m-%d"
        if all(value % 60 == 0 for value in seconds):
            return "%Y-%m-%d %H:%M"
        return "%Y-%m-%d %H:%M:%S"

    @staticmethod
    def time_text(seconds: float, time_format: str) -> str:
        """Get a time of a time axis, seconds since 1970, as text in UTC: as it was given."""
        return (_EPOCH + datetime.timedelta(seconds=seconds)).strftime(time_format)

    @staticmethod
    def time_ticks(low: float, high: float, count: int) -> tuple[list[float], list[str]]:
        """Get at most `count` (2 or more) ticks of a time axis from `low` to `high`, labeled.

        At the smallest round step, a second up to half a year, that takes no more, else at
        New Year every so many years. Each label is in UTC, with what changes at that step,
        e.g. the day.
        """
        intervals = max(count, 2) - 1
        span = max(high - low, 0)
        for step, time_format in _TIME_STEPS:
            if span / step <= intervals:
                first, last = math.ceil(low / step), math.floor(high / step)
                # within the range: a division can round, e.g. a tiny `low` down to 0
                ticks = [
                    float(tick * step)
                    for tick in range(first, last + 1)
                    if low <= tick * step <= high
                ]
                return ticks, [ChartView.time_text(tick, time_format) for tick in ticks]
        first_year = (_EPOCH + datetime.timedelta(seconds=low)).year + 1
        last_year = (_EPOCH + datetime.timedelta(seconds=high)).year
        years = math.ceil((last_year - first_year + 1) / (intervals + 1))
        ticks = [
            _chart_value(datetime.date(year, 1, 1))
            for year in range(first_year, last_year + 1)
            if year % years == 0
        ]
        return ticks, [ChartView.time_text(tick, "%Y") for tick in ticks]

    @staticmethod
    def loadable_state(data: dict[str, Any]) -> dict[str, Any]:
        """Get a chart's saved state as it is saved now, from a study saved before.

        Then, the chart held a kind, which a series without one took, and a bar chart drew
        every series as bars.
        """
        if "kind" not in data:
            return data
        chart_kind = data["kind"]
        series = [
            {
                **curve,
                "kind": chart_kind
                if chart_kind == ChartKind.BAR.value or curve.get("kind") is None
                else curve["kind"],
            }
            for curve in data.get("series", [])
        ]
        return {**data, "series": series}

    @staticmethod
    def drawn_points(
        series: Series, *, x_log: bool, y_log: bool
    ) -> tuple[list[float], list[float]]:
        """Get the points of `series` its axes can show: a log axis can't show 0 or less.

        A point whose x a log x axis can't show is left out; a y a log y axis can't show
        is NaN, a gap. As they are without a log axis.
        """
        if not x_log and not y_log:
            return series.x, series.y
        xs: list[float] = []
        ys: list[float] = []
        for x, y in zip(series.x, series.y):
            if x_log and not x > 0:
                continue
            xs.append(x)
            ys.append(math.nan if y_log and not y > 0 else y)
        return xs, ys

    @staticmethod
    def step_points(xs: list[float], ys: list[float]) -> tuple[list[float], list[float]]:
        """Get the corners of a step line through the points: each y held until the next x.

        A NaN y stays a gap, up to the next point.
        """
        step_xs: list[float] = []
        step_ys: list[float] = []
        for index, (x, y) in enumerate(zip(xs, ys)):
            step_xs.append(x)
            step_ys.append(y)
            if index + 1 < len(xs):
                step_xs.append(xs[index + 1])
                step_ys.append(y)
        return step_xs, step_ys

    @staticmethod
    def held_value(xs: list[float], ys: list[float], x: float) -> Optional[float]:
        """Get the y a step line holds at `x`: the last point's at or before it, x in order.

        None before the first point; NaN in a gap.
        """
        held: Optional[float] = None
        for point_x, point_y in zip(xs, ys):
            if point_x > x:
                break
            held = point_y
        return held

    @staticmethod
    def drawn_lines(
        lines: list[ReferenceLine], *, x_log: bool, y_log: bool, y2_log: bool = False
    ) -> list[ReferenceLine]:
        """Get the reference lines their axes can show: a log axis can't show 0 or less."""
        return [
            line
            for line in lines
            if math.isfinite(line.value)
            and (
                line.value > 0 or not (x_log if line.vertical else y2_log if line.on_y2 else y_log)
            )
        ]

    @staticmethod
    def has_y2(series: list[Series], lines: list[ReferenceLine]) -> bool:
        """Tell whether the second y axis shows: a series or a reference line is on it."""
        return any(curve.on_y2 for curve in series) or any(line.is_on_y2 for line in lines)

    @staticmethod
    def bar_heights(series: Series, category_count: int, *, y_log: bool = False) -> list[float]:
        """Get the height of a series' bar in each category, NaN where it has none.

        A point whose x isn't a category's index has no bar; the last of a category wins.
        On a log y axis, a height of 0 or less is no bar either.
        """
        heights = [math.nan] * category_count
        for x, y in zip(series.x, series.y):
            if x.is_integer() and 0 <= x < category_count:
                heights[int(x)] = math.nan if y_log and not y > 0 else y
        return heights

    @staticmethod
    def is_whole(values: Sequence[float]) -> bool:
        """Tell whether `values` are whole numbers, e.g. counts, their gaps (NaN) aside.

        A series of them shows its hovered values as integers, e.g. "45280" rather than
        "4.528e+04"; another with 4 significant digits.
        """
        return all(
            math.isnan(value) or (value.is_integer() and abs(value) < _WHOLE_LIMIT)
            for value in values
        )

    @staticmethod
    def bars_of(
        series: Series, categories: list[str], *, y_log: bool = False
    ) -> tuple[list[float], list[float]]:
        """Get the bars of `series` that are drawn: the x of each, and its height.

        With `categories`, a bar per category that has one (see `bar_heights`). Without,
        a bar at each x. A NaN is no bar, nor is a height of 0 or less on a log y axis.
        """
        points: list[tuple[float, float]]
        if len(categories) > 0:
            heights = ChartView.bar_heights(series, len(categories), y_log=y_log)
            points = [(float(category), height) for category, height in enumerate(heights)]
        else:
            points = [(x, y) for x, y in zip(series.x, series.y) if math.isfinite(x)]
        drawn = [(x, y) for x, y in points if math.isfinite(y) and not (y_log and not y > 0)]
        return [x for x, _y in drawn], [y for _x, y in drawn]

    @staticmethod
    def bar_step(series: list[Series], categories: list[str]) -> float:
        """Get the room between two bars' x: 1 between categories, else the smallest step.

        The smallest difference between the x of the bar series, 1 with fewer than two x.
        """
        if len(categories) > 0:
            return 1.0
        xs = sorted(
            {
                x
                for curve in series
                if curve.kind is ChartKind.BAR
                for x in curve.x
                if math.isfinite(x)
            }
        )
        return min((high - low for low, high in zip(xs, xs[1:])), default=1.0)

    @staticmethod
    def bar_slots(
        series: list[Series], categories: list[str], mode: BarMode = BarMode.GROUPED
    ) -> dict[int, tuple[float, float]]:
        """Get each bar series' slot in a group of bars, by its index in `series`.

        A slot is the offset of the bar's middle from its x, and its width: the slots share
        `BAR_GROUP_WIDTH` of the room between two x, their group centered on the x. A bar
        series has a slot of its own; stacked, the bar series of a y axis share one.
        """
        bars = [index for index, curve in enumerate(series) if curve.kind is ChartKind.BAR]
        if len(bars) == 0:
            return {}
        if mode is BarMode.STACKED:
            # a slot by y axis, in the order of their first bars
            units = list(dict.fromkeys(series[index].on_y2 for index in bars))
            places = {index: units.index(series[index].on_y2) for index in bars}
        else:
            places = {index: position for position, index in enumerate(bars)}
        count = len(set(places.values()))
        width = BAR_GROUP_WIDTH * ChartView.bar_step(series, categories) / count
        return {
            index: ((place - (count - 1) / 2) * width, width) for index, place in places.items()
        }

    @staticmethod
    def stack_bases(series: list[Series], categories: list[str]) -> dict[int, list[float]]:
        """Get where each bar of a stack starts, by bar series, in the order `bars_of` gives.

        On the sum of the values before it at its x, on its y axis and on its side of 0: a
        value over 0 stacks up, one under 0 down. A gap adds nothing.
        """
        totals: dict[tuple[bool, float, bool], float] = {}
        bases: dict[int, list[float]] = {}
        for index, curve in enumerate(series):
            if curve.kind is not ChartKind.BAR:
                continue
            bases[index] = []
            for x, height in zip(*ChartView.bars_of(curve, categories)):
                key = (curve.on_y2, x, height >= 0)
                bases[index].append(totals.get(key, 0.0))
                totals[key] = totals.get(key, 0.0) + height
        return bases

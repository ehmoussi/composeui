"""The map and the drawing views, and the shapes a drawing holds."""

from __future__ import annotations

import enum
import math
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
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
from composeui.core._views.charts import LineStyle
from composeui.core._views.content import TextRole
from composeui.core.signal import Signal, SignalNoArgs

if TYPE_CHECKING:
    from collections.abc import Iterable


#: the latitude of a Web Mercator map's edges, north and south, in degrees
MAP_LATITUDE_LIMIT = 85.05112878


@attrs.frozen(kw_only=True)
class MapPoint:
    """A geographic position, given as latitude and longitude in degrees.

    Both arguments are keyword-only. Latitude is limited to the range of a Web Mercator map.
    """

    latitude: float = attrs.field(
        converter=float,
        validator=[
            attrs.validators.ge(-MAP_LATITUDE_LIMIT),
            attrs.validators.le(MAP_LATITUDE_LIMIT),
        ],
    )
    longitude: float = attrs.field(
        converter=float, validator=[attrs.validators.ge(-180), attrs.validators.le(180)]
    )


@define_view
class MapView(View):
    """An interactive street map with geographic points drawn over its tiles.

    Qt uses Qt Location, and the web uses deck.gl. Textual does not render this view.
    With ``center=None`` and ``zoom=None``, the map fits its points and follows new data
    and widget sizes. Each explicit value overrides its automatic value. A user pan or
    zoom sets both values; new points then keep that viewport. Reset both to None to fit
    again. The study saves these settings, but not the points or tile settings.
    """

    _renderer_key = "map"
    MAX_ZOOM: ClassVar[int] = 19

    title: str = attrs.field(default="", metadata={UI_TEXT: True})
    #: None fits the points; otherwise the center to keep
    center: Optional[MapPoint] = attrs.field(default=None)
    #: None fits the points; otherwise an OpenStreetMap zoom level from 0 to 19
    zoom: Optional[float] = attrs.field(
        default=None,
        converter=attrs.converters.optional(float),
        validator=attrs.validators.optional(
            attrs.validators.and_(attrs.validators.ge(0), attrs.validators.le(MAX_ZOOM))
        ),
    )
    points: list[MapPoint] = attrs.field(factory=list[MapPoint], metadata={OMIT: True})
    height: int = attrs.field(default=400, validator=attrs.validators.ge(1), metadata={OMIT: True})
    #: False draws only the points, without any network requests for tiles
    tiles: bool = attrs.field(default=True, metadata={OMIT: True})
    #: identifies the native app to the tile server; the web uses the browser's identity
    user_agent: str = attrs.field(
        default="ComposeUI (+https://github.com/ehmoussi/composeui)", metadata={OMIT: True}
    )
    clicked: Signal[float, float] = attrs.Factory(Signal[float, float])
    #: the user panned or zoomed; center and zoom already hold the new viewport
    viewport_changed: SignalNoArgs = attrs.Factory(SignalNoArgs)

    @staticmethod
    def point_bounds(
        points: list[MapPoint], center: Optional[MapPoint]
    ) -> tuple[MapPoint, float, float]:
        """Get the center and spans as fractions of the Web Mercator world.

        With no center override, use the shortest longitude arc across the date line.
        With an override, use spans symmetric around that center.
        """
        if not points:
            return center or MapPoint(latitude=0, longitude=0), 1.0, 1.0
        xs = sorted((point.longitude + 180) / 360 % 1 for point in points)
        ys = [
            0.5 - math.asinh(math.tan(math.radians(point.latitude))) / (2 * math.pi)
            for point in points
        ]
        if center is None:
            # Remove the largest longitude gap so points across the date line stay together.
            gaps = [right - left for left, right in zip(xs, [*xs[1:], xs[0] + 1])]
            gap_index = max(range(len(gaps)), key=gaps.__getitem__)
            span_x = 1 - gaps[gap_index]
            middle_x = (xs[(gap_index + 1) % len(xs)] + span_x / 2) % 1
            middle_y = (min(ys) + max(ys)) / 2
            center = (
                points[0]
                if span_x == 0 and min(ys) == max(ys)
                else MapPoint(
                    latitude=max(
                        -MAP_LATITUDE_LIMIT,
                        min(
                            MAP_LATITUDE_LIMIT,
                            math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * middle_y)))),
                        ),
                    ),
                    longitude=middle_x * 360 - 180,
                )
            )
            return center, span_x, max(ys) - min(ys)
        center_x = (center.longitude + 180) / 360
        center_y = 0.5 - math.asinh(math.tan(math.radians(center.latitude))) / (2 * math.pi)
        return (
            center,
            2 * max(abs((x - center_x + 0.5) % 1 - 0.5) for x in xs),
            2 * max(abs(y - center_y) for y in ys),
        )

    @staticmethod
    def fitted_zoom(span_x: float, span_y: float, width: int, height: int) -> float:
        """Fit Mercator spans in pixel dimensions with 32 pixels of padding on each side.

        Clamp the zoom to 0 through 19; use 12 for a single location.
        """
        if span_x == 0 and span_y == 0:
            return 12.0
        scales = [
            max(1, size - 64) / (256 * span)
            for span, size in ((span_x, width), (span_y, height))
            if span > 0
        ]
        return max(0.0, min(float(MapView.MAX_ZOOM), math.log2(min(scales))))


def _to_point(value: Iterable[float]) -> tuple[float, float]:
    x, y = value
    return float(x), float(y)


def _to_polyline_points(values: Iterable[Iterable[float]]) -> list[tuple[float, float]]:
    return ItemList((_to_point(value) for value in values), "PolylineShape.points")


def _to_polygon_points(values: Iterable[Iterable[float]]) -> list[tuple[float, float]]:
    return ItemList((_to_point(value) for value in values), "PolygonShape.points")


def _check_point(shape: Any, attribute: attrs.Attribute[Any], point: tuple[float, float]) -> None:
    if not all(math.isfinite(value) for value in point):
        msg = f"Cannot draw a {type(shape).__name__} with the {attribute.name} {point}."
        raise ValueError(msg)


def _check_points(
    shape: Any, attribute: attrs.Attribute[Any], points: list[tuple[float, float]]
) -> None:
    for point in points:
        _check_point(shape, attribute, point)


def _check_shape_color(shape: Any, _attribute: attrs.Attribute[Any], color: Optional[str]) -> None:
    if color is not None and _COLOR_PATTERN.fullmatch(color) is None:
        msg = f"Cannot color a {type(shape).__name__} {color!r}: give it as #rrggbb."
        raise ValueError(msg)


def _check_radius(shape: Any, _attribute: attrs.Attribute[Any], radius: float) -> None:
    if not (math.isfinite(radius) and radius > 0):
        msg = f"Cannot draw a {type(shape).__name__} of radius {radius}: it must be positive."
        raise ValueError(msg)


class TextAnchor(enum.Enum):
    """Which end of a `TextShape` stands at its position, across the text."""

    START = enum.auto()
    MIDDLE = enum.auto()
    END = enum.auto()


class LineWeight(enum.Enum):
    """How heavy a line of a `DrawingView` is, which each backend shows in its own way."""

    #: e.g. a dimension or a construction line
    LIGHT = enum.auto()
    NORMAL = enum.auto()
    #: e.g. what the diagram is about
    HEAVY = enum.auto()


@attrs.frozen
class LineShape:
    """A straight line of a `DrawingView`, from `start` to `end`."""

    start: tuple[float, float] = attrs.field(converter=_to_point, validator=[_check_point])
    end: tuple[float, float] = attrs.field(converter=_to_point, validator=[_check_point])
    #: as #rrggbb, the same in every theme; None: the theme's text color
    color: Optional[str] = attrs.field(default=None, validator=[_check_shape_color])
    #: a terminal draws each solid
    style: LineStyle = LineStyle.SOLID
    #: how heavy its line is
    weight: LineWeight = LineWeight.NORMAL


@attrs.frozen
class PolylineShape:
    """Lines of a `DrawingView` joining its points in order, at least 2."""

    points: list[tuple[float, float]] = attrs.field(
        converter=_to_polyline_points, validator=[attrs.validators.min_len(2), _check_points]
    )
    #: as #rrggbb, the same in every theme; None: the theme's text color
    color: Optional[str] = attrs.field(default=None, validator=[_check_shape_color])
    #: a terminal draws each solid
    style: LineStyle = LineStyle.SOLID
    #: how heavy its line is
    weight: LineWeight = LineWeight.NORMAL


@attrs.frozen
class PolygonShape:
    """A closed shape of a `DrawingView` through its points, at least 3."""

    points: list[tuple[float, float]] = attrs.field(
        converter=_to_polygon_points, validator=[attrs.validators.min_len(3), _check_points]
    )
    #: as #rrggbb, the same in every theme; None: the theme's text color
    color: Optional[str] = attrs.field(default=None, validator=[_check_shape_color])
    #: a terminal draws each solid
    style: LineStyle = LineStyle.SOLID
    #: whether its inside is filled
    fill: bool = False
    #: how heavy its line is
    weight: LineWeight = LineWeight.NORMAL
    #: with `fill`, its inside's color, as #rrggbb, e.g. a pale area in a dark outline; None:
    #: its `color`
    fill_color: Optional[str] = attrs.field(default=None, validator=[_check_shape_color])


@attrs.frozen
class CircleShape:
    """A circle of a `DrawingView`, its radius in the drawing's coordinates."""

    center: tuple[float, float] = attrs.field(converter=_to_point, validator=[_check_point])
    radius: float = attrs.field(converter=float, validator=[_check_radius])
    #: as #rrggbb, the same in every theme; None: the theme's text color
    color: Optional[str] = attrs.field(default=None, validator=[_check_shape_color])
    #: a terminal draws each solid
    style: LineStyle = LineStyle.SOLID
    #: whether its inside is filled
    fill: bool = False
    #: how heavy its line is
    weight: LineWeight = LineWeight.NORMAL
    #: with `fill`, its inside's color, as #rrggbb, e.g. a pale area in a dark outline; None:
    #: its `color`
    fill_color: Optional[str] = attrs.field(default=None, validator=[_check_shape_color])


@attrs.frozen
class ArrowShape:
    """A line of a `DrawingView` with a head at `end`, the same size at any scale."""

    start: tuple[float, float] = attrs.field(converter=_to_point, validator=[_check_point])
    end: tuple[float, float] = attrs.field(converter=_to_point, validator=[_check_point])
    #: as #rrggbb, the same in every theme; None: the theme's text color
    color: Optional[str] = attrs.field(default=None, validator=[_check_shape_color])
    #: a terminal draws each solid
    style: LineStyle = LineStyle.SOLID
    #: how heavy its line is
    weight: LineWeight = LineWeight.NORMAL


@attrs.frozen
class TextShape:
    """A text of a `DrawingView` at a position, the same size at any scale.

    It is the app's data, as a series' name: the app translates it before making the shape.
    """

    position: tuple[float, float] = attrs.field(converter=_to_point, validator=[_check_point])
    text: str
    #: as #rrggbb, the same in every theme; None: the theme's text color
    color: Optional[str] = attrs.field(default=None, validator=[_check_shape_color])
    #: which part of the text stands at `position`
    anchor: TextAnchor = TextAnchor.START
    #: what it is: each backend shows a title or a caption in its own way. `color` goes first
    role: TextRole = TextRole.BODY


#: past about 10 degrees from level (the sine of it), a centered label would cross its line
_DIMENSION_CENTERED_LEAN = 0.17


@attrs.frozen
class DimensionShape:
    """A measurement of a `DrawingView`: a line with a tick at each end and a label.

    The ticks and the label's distance from the line stay the same size at any scale. The
    label stands on the right of the line going from `start` to `end`: below it when `start`
    is on the left.
    """

    start: tuple[float, float] = attrs.field(converter=_to_point, validator=[_check_point])
    end: tuple[float, float] = attrs.field(converter=_to_point, validator=[_check_point])
    #: the measure shown, e.g. "6 m"
    text: str
    #: of its line, its ticks and its text, as #rrggbb, the same in every theme; None: the
    #: theme's text color
    color: Optional[str] = attrs.field(default=None, validator=[_check_shape_color])
    #: a terminal draws each solid
    style: LineStyle = LineStyle.SOLID
    #: how heavy its lines are
    weight: LineWeight = LineWeight.LIGHT
    #: what its text is: each backend shows a title or a caption in its own way
    role: TextRole = TextRole.BODY

    def across(self) -> tuple[float, float]:
        """Get the unit vector from the line toward its label, on a surface, y going down.

        A line without a direction has its label below.
        """
        # halved: between -1e308 and 1e308, the side overflows
        dx, dy = self.end[0] / 2 - self.start[0] / 2, self.end[1] / 2 - self.start[1] / 2
        distance = math.hypot(dx, dy)
        return (dy / distance, dx / distance) if distance > 0 else (0.0, 1.0)

    def label(self) -> TextShape:
        """Get its text at the line's middle, anchored so that it clears the line."""
        across_x, _across_y = self.across()
        anchor = TextAnchor.MIDDLE
        if abs(across_x) > _DIMENSION_CENTERED_LEAN:
            anchor = TextAnchor.START if across_x > 0 else TextAnchor.END
        return TextShape(
            (self.start[0] / 2 + self.end[0] / 2, self.start[1] / 2 + self.end[1] / 2),
            self.text,
            self.color,
            anchor,
            self.role,
        )


#: a shape of a `DrawingView`
Shape = Union[
    LineShape, PolylineShape, PolygonShape, CircleShape, ArrowShape, TextShape, DimensionShape
]

#: a drawing's area without shapes
_EMPTY_BOUNDS = (0.0, 0.0, 1.0, 1.0)
#: the room around shapes fitted to the view, as a share of their longer side
_FIT_MARGIN = 0.08
#: an arrow head's width on each side of its line, as a share of its length
_ARROW_HEAD_SIDE = 0.4


def _is_drawable(bounds: tuple[float, float, float, float]) -> bool:
    """Check that an area has a size a float holds: the renderers divide by its sides."""
    x_min, y_min, x_max, y_max = bounds
    return (
        x_min < x_max
        and y_min < y_max
        and math.isfinite(x_max - x_min)
        and math.isfinite(y_max - y_min)
    )


def _check_bounds(
    view: View,
    _attribute: attrs.Attribute[Any],
    bounds: Optional[tuple[float, float, float, float]],
) -> None:
    if bounds is None:
        return
    if not _is_drawable(bounds):
        msg = (
            f"Cannot set {type(view).__name__}.bounds to {bounds}:"
            " give finite x_min, y_min, x_max, y_max, each minimum below its maximum."
        )
        raise ValueError(msg)


def _extent_points(shape: Shape) -> list[tuple[float, float]]:
    """Get the points that a shape's extent reaches."""
    if isinstance(shape, (LineShape, ArrowShape, DimensionShape)):
        return [shape.start, shape.end]
    if isinstance(shape, (PolylineShape, PolygonShape)):
        return shape.points
    if isinstance(shape, CircleShape):
        (x, y), radius = shape.center, shape.radius
        return [(x - radius, y - radius), (x + radius, y + radius)]
    return [shape.position]


@attrs.frozen
class DrawingPlacement:
    """Where a drawing's area stands on a surface: one scale, centered, y flipped."""

    scale: float
    left: float
    top: float
    x_min: float
    y_max: float

    def point(self, point: tuple[float, float]) -> tuple[float, float]:
        """Get the surface's position of a point of the drawing, y going down."""
        return (
            self.left + (point[0] - self.x_min) * self.scale,
            self.top + (self.y_max - point[1]) * self.scale,
        )


@define_view
class DrawingView(View):
    """A diagram of lines, shapes and text that scales with the view.

    Assign a new `shapes` list to redraw it, e.g. when a slider moves. The shapes are in the
    drawing's own coordinates, y going up, with one scale for both axes: a circle stays
    round. A text, the lines' width, an arrow's head and a dimension's ticks keep their size
    on screen.

    Qt and the web draw it exactly. A terminal draws it with braille characters, the text
    readable over them, and its description below.
    """

    _renderer_key = "drawing"

    shapes: list[Shape] = attrs.field(factory=list[Shape])
    #: the only area shown: x_min, y_min, x_max, y_max, e.g. fixed so that a moving shape doesn't
    #: rescale the rest; None: fitted to the shapes
    bounds: Optional[tuple[float, float, float, float]] = attrs.field(
        default=None, validator=[_check_bounds]
    )
    #: what it shows, for a screen reader and a terminal; empty: the shapes' text
    description: str = attrs.field(default="", metadata={UI_TEXT: True})
    #: its height on screen, in pixels (a terminal's rows of about 16); None: the backend's
    #: own. The app's layout, not a study's
    height: Optional[int] = attrs.field(
        default=None, validator=[_check_height], metadata={OMIT: True}
    )

    @staticmethod
    def shown_bounds(
        shapes: list[Shape], bounds: Optional[tuple[float, float, float, float]]
    ) -> tuple[float, float, float, float]:
        """Get the area drawn: `bounds`, or the shapes' extent and a margin."""
        if bounds is not None:
            return bounds
        points = [point for shape in shapes for point in _extent_points(shape)]
        if len(points) == 0:
            return _EMPTY_BOUNDS
        xs, ys = [x for x, _y in points], [y for _x, y in points]
        # one lone point, or a single text, still gets an area
        margin = max(max(xs) - min(xs), max(ys) - min(ys)) * _FIT_MARGIN or 1.0
        fitted = (min(xs) - margin, min(ys) - margin, max(xs) + margin, max(ys) + margin)
        # at 1e20, a margin is lost to rounding; between -1e308 and 1e308, the side overflows
        return fitted if _is_drawable(fitted) else _EMPTY_BOUNDS

    @staticmethod
    def in_bounds(point: tuple[float, float], bounds: tuple[float, float, float, float]) -> bool:
        """Check that a point stands in the area: a text or an arrow's head is drawn only so."""
        return bounds[0] <= point[0] <= bounds[2] and bounds[1] <= point[1] <= bounds[3]

    @staticmethod
    def placement(
        bounds: tuple[float, float, float, float], width: float, height: float
    ) -> DrawingPlacement:
        """Fit an area in a surface of `width` by `height`, keeping its proportions."""
        x_min, y_min, x_max, y_max = bounds
        scale = min(width / (x_max - x_min), height / (y_max - y_min))
        return DrawingPlacement(
            scale=scale,
            left=(width - (x_max - x_min) * scale) / 2,
            top=(height - (y_max - y_min) * scale) / 2,
            x_min=x_min,
            y_max=y_max,
        )

    @staticmethod
    def arrow_head(
        tail: tuple[float, float], tip: tuple[float, float], length: float
    ) -> tuple[tuple[float, float], tuple[float, float]]:
        """Get the back corners of a head of `length` at `tip`, on a surface's coordinates.

        A line without a direction has its head pointing right.
        """
        dx, dy = tip[0] - tail[0], tip[1] - tail[1]
        distance = math.hypot(dx, dy)
        ux, uy = (dx / distance, dy / distance) if distance > 0 else (1.0, 0.0)
        back_x, back_y = tip[0] - ux * length, tip[1] - uy * length
        side = length * _ARROW_HEAD_SIDE
        return (back_x - uy * side, back_y + ux * side), (back_x + uy * side, back_y - ux * side)

    @staticmethod
    def shown_description(description: str, shapes: list[Shape]) -> str:
        """Get what describes the drawing: `description`, or the text of its shapes."""
        return description or ", ".join(
            shape.text
            for shape in shapes
            if isinstance(shape, (TextShape, DimensionShape)) and shape.text
        )

"""The web renderers of maps and drawings, which the page's scripts and SVG draw."""

from __future__ import annotations

import json
import math
from typing import TYPE_CHECKING, Final

from markupsafe import Markup
from typing_extensions import Protocol, override

from composeui.core.renderer import ViewLike
from composeui.core.view import (
    ArrowShape,
    CircleShape,
    DimensionShape,
    DrawingView,
    LineShape,
    LineStyle,
    LineWeight,
    MapPoint,
    MapView,
    PolygonShape,
    TextAnchor,
    TextShape,
)
from composeui.webcore._renderers.content import _ROLE_MARKUP
from composeui.webcore.webrenderer import UnsupportedEventError, WebRenderer

if TYPE_CHECKING:
    from collections.abc import Mapping

    from composeui.core.signal import Signal, SignalNoArgs
    from composeui.core.view import Shape


class MapViewLike(ViewLike, Protocol):
    title: str
    center: MapPoint | None
    zoom: float | None
    points: list[MapPoint]
    height: int
    tiles: bool
    user_agent: str
    clicked: Signal[float, float]
    viewport_changed: SignalNoArgs


class WebMapRenderer(WebRenderer[MapViewLike]):
    _role = "map"
    is_labelable = False

    def __init__(self, view: MapViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            dict.fromkeys(
                ("title", "center", "zoom", "points", "height", "tiles", "user_agent"),
                self._mark_dirty,
            )
        )

    @override
    def to_html(self, *, oob: bool = False) -> Markup:
        view = self._view
        center, span_x, span_y = MapView.point_bounds(view.points, view.center)
        spec = json.dumps(
            {
                "latitude": center.latitude,
                "longitude": center.longitude,
                "zoom": view.zoom,
                "span": [span_x, span_y],
                "points": [[p.longitude, p.latitude] for p in view.points],
                "tiles": view.tiles,
                "enabled": self.is_enabled,
            },
            allow_nan=False,
            separators=(",", ":"),
        )
        attribution = (
            Markup(
                '<a href="https://www.openstreetmap.org/copyright" rel="noreferrer">'
                "© OpenStreetMap contributors</a>"
            )
            if view.tiles
            else Markup()
        )
        return Markup(
            '<figure {root} class="flex w-full flex-col gap-2">'
            "<figcaption>{title}</figcaption>"
            '<div data-map="{spec}" data-widget="{widget}" role="region"'
            ' aria-label="{title}" tabindex="0" style="height:{height}px;position:relative;'
            'width:100%;background:#e5e7eb"></div><small>{attribution}</small></figure>'
        ).format(
            root=self._root_attributes(oob=oob),
            title=view.title,
            spec=spec,
            widget=self.widget_id,
            height=view.height,
            attribution=attribution,
        )

    @override
    def dispatch(self, event: str, form: Mapping[str, str]) -> None:
        if event not in ("click", "viewport") or not self.is_enabled:
            super().dispatch(event, form)
        try:
            point = MapPoint(
                latitude=float(form.get("latitude", "")),
                longitude=float(form.get("longitude", "")),
            )
            zoom = float(form.get("zoom", "")) if event == "viewport" else 0.0
        except ValueError:
            raise UnsupportedEventError(self, event) from None
        if not 0 <= zoom <= MapView.MAX_ZOOM:
            super().dispatch(event, form)
        if event == "click":
            self._view.clicked.emit(point.latitude, point.longitude)
        else:
            with self.stop_refresh():
                self._view.center = point
                self._view.zoom = zoom
            self._view.viewport_changed.emit()


class DrawingViewLike(ViewLike, Protocol):
    shapes: list[Shape]
    bounds: tuple[float, float, float, float] | None
    description: str
    height: int | None


#: a drawing's lines, an arrow head's length and a text's size, in pixels at any scale
_DRAWING_LINE_WIDTHS: Final = {LineWeight.LIGHT: 1, LineWeight.NORMAL: 2, LineWeight.HEAVY: 4}
_DRAWING_ARROW_HEAD: Final = 11.0
#: how far a dimension's ticks reach on each side of its line, and its label stands from it
_DRAWING_DIMENSION_TICK: Final = 6.0
_DRAWING_DIMENSION_LABEL_GAP: Final = 14.0
_DRAWING_FONT_SIZE: Final = 13
#: the height of a drawing whose view has none, in pixels
_DRAWING_HEIGHT: Final = 288
_DRAWING_DASHES: Final = {
    LineStyle.SOLID: None,
    LineStyle.DASHED: "8 5",
    LineStyle.DOTTED: "2 4",
    LineStyle.DASH_DOT: "8 4 2 4",
}
_DRAWING_ANCHORS: Final = {
    TextAnchor.START: "start",
    TextAnchor.MIDDLE: "middle",
    TextAnchor.END: "end",
}


def _svg_number(value: float) -> str:
    return format(value, ".7g")


class WebDrawingRenderer(WebRenderer[DrawingViewLike]):
    """A drawing as SVG made from the validated shapes, with no script.

    The element keeps the area's proportions, so that percentages of it place a point. The
    geometry scales in a nested `<svg>` with a `viewBox`, its strokes not scaling. A text, an
    arrow head and a dimension's ticks stand at a percentage, in pixels, so they keep their size.
    """

    _role = "drawing"
    is_labelable = False

    def __init__(self, view: DrawingViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            dict.fromkeys(("shapes", "bounds", "description", "height"), self._mark_dirty)
        )

    @override
    def to_html(self, *, oob: bool = False) -> Markup:
        view = self._view
        bounds = DrawingView.shown_bounds(view.shapes, view.bounds)
        width, height = bounds[2] - bounds[0], bounds[3] - bounds[1]
        shown_height = _DRAWING_HEIGHT if view.height is None else int(view.height)
        return Markup(
            '<div {root_attributes} style="width: min(100%, {width}px);'
            ' aspect-ratio: {ratio}; margin-inline: auto">'
            '<svg role="img" aria-label="{description}" width="100%" height="100%"'
            ' overflow="visible" style="display: block">{shapes}</svg></div>'
        ).format(
            root_attributes=self._root_attributes(oob=oob),
            width=_svg_number(shown_height * width / height),
            ratio=f"{_svg_number(width)} / {_svg_number(height)}",
            description=DrawingView.shown_description(view.description, view.shapes),
            shapes=Markup("").join(self._shape_html(shape, bounds) for shape in view.shapes),
        )

    def _shape_html(self, shape: Shape, bounds: tuple[float, float, float, float]) -> Markup:
        if isinstance(shape, TextShape):
            return (
                self._text_html(shape, bounds)
                if DrawingView.in_bounds(shape.position, bounds)
                else Markup()
            )
        if isinstance(shape, DimensionShape):
            return self._dimension_html(shape, bounds)
        if not isinstance(shape, ArrowShape):
            return self._geometry_html(shape, bounds)
        shaft = self._arrow_shaft(shape, bounds)
        line = (
            Markup()
            if shaft is None
            else self._geometry_html(
                LineShape(shape.start, shaft, shape.color, shape.style, shape.weight), bounds
            )
        )
        return line + (
            self._arrow_head_html(shape, bounds)
            if DrawingView.in_bounds(shape.end, bounds)
            else Markup()
        )

    def _geometry_html(self, shape: Shape, bounds: tuple[float, float, float, float]) -> Markup:
        element = self._element_html(shape, bounds)
        width, height = bounds[2] - bounds[0], bounds[3] - bounds[1]
        # one `viewBox` a shape: a later text or head is drawn over an earlier line, in order.
        # Its overflow stays hidden: what is out of the bounds doesn't cover the page
        return Markup(
            '<svg viewBox="0 0 {width} {height}" preserveAspectRatio="none">{element}</svg>'
        ).format(width=_svg_number(width), height=_svg_number(height), element=element)

    def _arrow_shaft(
        self, shape: ArrowShape, bounds: tuple[float, float, float, float]
    ) -> tuple[float, float] | None:
        """Get where an arrow's line stops, inside its head; None if the head covers it.

        As on Qt, its blunt end must not pass the tip. The scale on the page is known only
        to the browser: this is the largest it can be, the head's length at the view's height.
        """
        dx, dy = shape.end[0] - shape.start[0], shape.end[1] - shape.start[1]
        length = math.hypot(dx, dy)
        height = _DRAWING_HEIGHT if self._view.height is None else int(self._view.height)
        head = _DRAWING_ARROW_HEAD * (bounds[3] - bounds[1]) / height
        if length <= head:
            return None
        return shape.end[0] - dx / length * head / 2, shape.end[1] - dy / length * head / 2

    def _element_html(self, shape: Shape, bounds: tuple[float, float, float, float]) -> Markup:
        assert not isinstance(shape, (TextShape, ArrowShape, DimensionShape))  # drawn on their own
        fill = "none"
        if isinstance(shape, (PolygonShape, CircleShape)) and shape.fill:
            fill = shape.fill_color or shape.color or "currentColor"
        paint = self._stroke(shape, fill)

        def local(point: tuple[float, float]) -> tuple[str, str]:
            return _svg_number(point[0] - bounds[0]), _svg_number(bounds[3] - point[1])

        if isinstance(shape, LineShape):
            (x1, y1), (x2, y2) = local(shape.start), local(shape.end)
            return Markup('<line x1="{}" y1="{}" x2="{}" y2="{}" {}/>').format(
                x1, y1, x2, y2, paint
            )
        if isinstance(shape, CircleShape):
            x, y = local(shape.center)
            radius = _svg_number(shape.radius)
            return Markup('<circle cx="{}" cy="{}" r="{}" {}/>').format(x, y, radius, paint)
        points = " ".join(",".join(local(point)) for point in shape.points)
        tag = "polygon" if isinstance(shape, PolygonShape) else "polyline"
        return Markup('<{} points="{}" {}/>').format(tag, points, paint)

    @staticmethod
    def _stroke(shape: Shape, fill: str = "none") -> Markup:
        """Get the attributes that paint a shape's line."""
        assert not isinstance(shape, TextShape)  # has no line
        dashes = _DRAWING_DASHES[shape.style]
        return Markup(
            'stroke="{color}" fill="{fill}" stroke-width="{width}"'
            ' vector-effect="non-scaling-stroke"{dashes}'
        ).format(
            color=shape.color or "currentColor",
            fill=fill,
            width=_DRAWING_LINE_WIDTHS[shape.weight],
            dashes=Markup("")
            if dashes is None
            else Markup(' stroke-dasharray="{}"').format(dashes),
        )

    def _tick_html(
        self,
        shape: DimensionShape,
        end: tuple[float, float],
        tick: tuple[float, float],
        bounds: tuple[float, float, float, float],
    ) -> Markup:
        x, y = self._percent(end, bounds)
        return Markup(
            '<svg x="{x}" y="{y}" overflow="visible">'
            '<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" {paint}/></svg>'
        ).format(
            x=x,
            y=y,
            x1=_svg_number(-tick[0]),
            y1=_svg_number(-tick[1]),
            x2=_svg_number(tick[0]),
            y2=_svg_number(tick[1]),
            paint=self._stroke(shape),
        )

    def _dimension_html(
        self, shape: DimensionShape, bounds: tuple[float, float, float, float]
    ) -> Markup:
        line = self._geometry_html(
            LineShape(shape.start, shape.end, shape.color, shape.style, shape.weight), bounds
        )
        across_x, across_y = shape.across()
        tick_x, tick_y = across_x * _DRAWING_DIMENSION_TICK, across_y * _DRAWING_DIMENSION_TICK
        ticks = Markup("").join(
            self._tick_html(shape, end, (tick_x, tick_y), bounds)
            for end in (shape.start, shape.end)
            if DrawingView.in_bounds(end, bounds)
        )
        label = shape.label()
        if not DrawingView.in_bounds(label.position, bounds):
            return line + ticks
        offset = (across_x * _DRAWING_DIMENSION_LABEL_GAP, across_y * _DRAWING_DIMENSION_LABEL_GAP)
        return line + ticks + self._text_html(label, bounds, offset)

    @staticmethod
    def _percent(
        point: tuple[float, float], bounds: tuple[float, float, float, float]
    ) -> tuple[str, str]:
        return (
            f"{_svg_number((point[0] - bounds[0]) / (bounds[2] - bounds[0]) * 100)}%",
            f"{_svg_number((bounds[3] - point[1]) / (bounds[3] - bounds[1]) * 100)}%",
        )

    def _arrow_head_html(
        self, shape: ArrowShape, bounds: tuple[float, float, float, float]
    ) -> Markup:
        x, y = self._percent(shape.end, bounds)
        # the page's y goes down: only the direction counts, the scale being the same
        tail = (shape.start[0] - shape.end[0], shape.end[1] - shape.start[1])
        left, right = DrawingView.arrow_head(tail, (0.0, 0.0), _DRAWING_ARROW_HEAD)
        corners = f"0,0 {_svg_number(left[0])},{_svg_number(left[1])}"
        corners += f" {_svg_number(right[0])},{_svg_number(right[1])}"
        return Markup(
            '<svg x="{x}" y="{y}" overflow="visible"><polygon points="{corners}" fill="{color}"/>'
            "</svg>"
        ).format(x=x, y=y, corners=corners, color=shape.color or "currentColor")

    def _text_html(
        self,
        shape: TextShape,
        bounds: tuple[float, float, float, float],
        offset: tuple[float, float] = (0.0, 0.0),
    ) -> Markup:
        x, y = self._percent(shape.position, bounds)
        classes = _ROLE_MARKUP[shape.role][1]
        return Markup(
            '<text x="{x}" y="{y}" dx="{dx}" dy="{dy}" text-anchor="{anchor}"'
            ' dominant-baseline="central"'
            ' font-size="{size}" fill="{color}"{classes}>{text}</text>'
        ).format(
            x=x,
            y=y,
            dx=_svg_number(offset[0]),
            dy=_svg_number(offset[1]),
            anchor=_DRAWING_ANCHORS[shape.anchor],
            size=_DRAWING_FONT_SIZE,
            color=shape.color or "currentColor",
            # a label's of this role: its size, its weight, and the `currentColor` of `fill`
            classes=Markup(' class="{}"').format(classes) if classes else Markup(),
            text=shape.text,
        )

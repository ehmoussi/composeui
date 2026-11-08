from __future__ import annotations

import math
import unicodedata
from typing import TYPE_CHECKING, ClassVar, NamedTuple

from rich.cells import cell_len
from rich.segment import Segment
from rich.style import Style
from textual.strip import Strip
from textual.widget import Widget

from composeui.core.view import (
    ArrowShape,
    CircleShape,
    DrawingPlacement,
    DrawingView,
    LineShape,
    LineWeight,
    PolygonShape,
    PolylineShape,
    TextAnchor,
    TextRole,
    TextShape,
)

if TYPE_CHECKING:
    from composeui.core.view import Shape

#: a braille cell's dots, across and down: a terminal's cell is about twice as tall as wide,
#: so a dot is about square, and a circle stays round
_DOTS_ACROSS = 2
_DOTS_DOWN = 4
_BRAILLE_BLANK = 0x2800
#: the bit of each dot of a cell, by row, then column
_DOT_BITS = ((0x01, 0x08), (0x02, 0x10), (0x04, 0x20), (0x40, 0x80))
#: the corners of a circle at most: past it, a huge circle's arc in view is as straight
_MAX_CIRCLE_POINTS = 2048
#: an arrow head's length, in dots
_ARROW_HEAD_DOTS = 5.0


class _Ink(NamedTuple):
    """How dots are drawn. A cell has one color and one style: the last shape's."""

    color: str | None
    #: dimmed, a terminal having nothing thinner than a dot
    is_light: bool = False
    #: two dots wide
    is_heavy: bool = False


# Braille rather than textual-canvas: its half-blocks draw coarser diagonals, and it has no
# text or polygon fill, and a fixed size. textual-hires-canvas needs Python 3.10 and NumPy.
class _Grid:
    """Braille cells, drawn dot by dot, with labels over them."""

    def __init__(self, columns: int, rows: int, area: tuple[float, float, float, float]) -> None:
        self.columns = columns
        self.rows = rows
        #: the part of the grid that shows the drawing's bounds: left, top, right, bottom
        self.area = area
        self.dots: dict[tuple[int, int], tuple[int, _Ink]] = {}
        #: a wide character's second cell holds ""
        self.labels: dict[tuple[int, int], tuple[str, str | None, TextRole]] = {}

    def plot(self, x: float, y: float, ink: _Ink) -> None:
        dot_x, dot_y = math.floor(x), math.floor(y)
        left, top, right, bottom = self.area
        if not (
            max(0, math.floor(left)) <= dot_x < min(self.columns * _DOTS_ACROSS, math.ceil(right))
            and max(0, math.floor(top)) <= dot_y < min(self.rows * _DOTS_DOWN, math.ceil(bottom))
        ):
            return
        cell = (dot_x // _DOTS_ACROSS, dot_y // _DOTS_DOWN)
        bit = _DOT_BITS[dot_y % _DOTS_DOWN][dot_x % _DOTS_ACROSS]
        self.dots[cell] = (self.dots.get(cell, (0, ink))[0] | bit, ink)

    def line(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
        ink: _Ink,
    ) -> None:
        clipped = self._clipped(start, end)
        if clipped is None:
            return
        # on whole dots: a fraction of a float's steps can fall just under a dot and skip it
        x0, y0, x1, y1 = (math.floor(value) for value in clipped)
        steps = max(1, abs(x1 - x0), abs(y1 - y0))
        # the second dot, across the line
        across = (0, 1) if abs(x1 - x0) >= abs(y1 - y0) else (1, 0)
        for step in range(steps + 1):
            x = x0 + round((x1 - x0) * step / steps)
            y = y0 + round((y1 - y0) * step / steps)
            self.plot(x, y, ink)
            if ink.is_heavy:
                self.plot(x + across[0], y + across[1], ink)

    def _clipped(
        self, start: tuple[float, float], end: tuple[float, float]
    ) -> tuple[float, float, float, float] | None:
        """Cut a line to the area (Liang-Barsky): its steps stay few however far it reaches.

        None if it is outside, or too large for a float at this scale.
        """
        dx, dy = end[0] - start[0], end[1] - start[1]
        if not _all_finite(*start, *end, dx, dy):
            return None
        left, top, right, bottom = self.area
        first, last = 0.0, 1.0
        for delta, room in (
            (-dx, start[0] - left),
            (dx, right - start[0]),
            (-dy, start[1] - top),
            (dy, bottom - start[1]),
        ):
            if delta == 0:
                if room < 0:
                    return None
            elif delta < 0:
                first = max(first, room / delta)
            else:
                last = min(last, room / delta)
        if first > last:
            return None
        return (
            start[0] + first * dx,
            start[1] + first * dy,
            start[0] + last * dx,
            start[1] + last * dy,
        )

    def outline(self, points: list[tuple[float, float]], ink: _Ink) -> None:
        for start, end in zip(points, points[1:]):
            self.line(start, end, ink)

    def fill(self, points: list[tuple[float, float]], ink: _Ink) -> None:
        """Fill the polygon through `points`, row by row: the even-odd rule."""
        ys = [y for _x, y in points]
        if not _all_finite(*ys):
            return
        low = max(0, math.floor(min(ys)))
        high = min(self.rows * _DOTS_DOWN - 1, math.ceil(max(ys)))
        for dot_y in range(low, high + 1):
            y = dot_y + 0.5
            crossings = sorted(
                a[0] + (y - a[1]) / (b[1] - a[1]) * (b[0] - a[0])
                for a, b in zip(points, [*points[1:], points[0]])
                if (a[1] <= y) != (b[1] <= y)
            )
            for left, right in zip(crossings[::2], crossings[1::2]):
                self.line((left, y), (right, y), ink)

    def label(self, text: str, column: int, row: int, shape: TextShape) -> None:
        """Write `text` on the nearest row free of other labels, whole if it fits."""
        width = cell_len(text)
        column = max(0, min(column, self.columns - width))
        for candidate in _nearest_rows(row, self.rows):
            cells = range(column, min(self.columns, column + width))
            if all((cell, candidate) not in self.labels for cell in cells):
                self._write(text, column, candidate, shape)
                return
        self._write(text, column, max(0, min(row, self.rows - 1)), shape)

    def _write(self, text: str, column: int, row: int, shape: TextShape) -> None:
        for character in text:
            width = cell_len(character)
            if column + width > self.columns:
                return
            for cell in range(column, column + width):
                self._clear_wide_character(cell, row)
            self.labels[column, row] = (character, shape.color, shape.role)
            if width == 2:  # noqa: PLR2004 (a wide character's cells)
                self.labels[column + 1, row] = ("", shape.color, shape.role)
            column += width

    def _clear_wide_character(self, column: int, row: int) -> None:
        """Blank the other half of a wide character that a new label overwrites."""
        label = self.labels.get((column, row))
        if label is None:
            return
        if label[0] == "":
            self.labels[column - 1, row] = (" ", *label[1:])
        elif self.labels.get((column + 1, row), label)[0] == "":
            self.labels[column + 1, row] = (" ", *label[1:])

    def strip(self, row: int, base: Style, role_styles: dict[TextRole, Style]) -> Strip:
        segments: list[Segment] = []
        for column in range(self.columns):
            label = self.labels.get((column, row))
            if label is not None:
                text, color, role = label
                style = base + role_styles[role]
            else:
                mask, ink = self.dots.get((column, row), (0, _Ink(None)))
                text, color = chr(_BRAILLE_BLANK + mask) if mask else " ", ink.color
                style = base + Style(dim=True) if ink.is_light else base
            if text != "":
                segments.append(
                    Segment(text, style if color is None else style + Style(color=color))
                )
        return Strip(segments, self.columns).simplify()


def _one_line(text: str) -> str:
    """Get `text` for a row of cells: on one line, each character taking room.

    A strip goes to the terminal as it is: a control character would act on it, and a
    combining one, without a cell of its own, would replace the character before it.
    """
    return "".join(
        character
        for character in " ".join(unicodedata.normalize("NFC", text).split())
        if cell_len(character) > 0
    )


def _all_finite(*values: float) -> bool:
    return all(math.isfinite(value) for value in values)


def _nearest_rows(row: int, rows: int) -> list[int]:
    """Get the rows from `row` outward: down first, a label's text reading on."""
    row = max(0, min(row, rows - 1))
    return sorted(range(rows), key=lambda candidate: (abs(candidate - row), candidate < row))


def _draw_shape(
    grid: _Grid,
    placement: DrawingPlacement,
    bounds: tuple[float, float, float, float],
    shape: Shape,
) -> None:
    if isinstance(shape, TextShape):
        return  # over every shape, drawn after them
    ink = _Ink(
        shape.color,
        is_light=shape.weight is LineWeight.LIGHT,
        is_heavy=shape.weight is LineWeight.HEAVY,
    )
    # a head and an inside have no line to weigh
    solid = _Ink(shape.color)
    if isinstance(shape, (LineShape, ArrowShape)):
        tail, tip = placement.point(shape.start), placement.point(shape.end)
        grid.line(tail, tip, ink)
        if isinstance(shape, ArrowShape) and DrawingView.in_bounds(shape.end, bounds):
            left, right = DrawingView.arrow_head(tail, tip, _ARROW_HEAD_DOTS)
            grid.fill([tip, left, right], solid)
            grid.outline([left, tip, right], solid)
        return
    if isinstance(shape, PolylineShape):
        grid.outline([placement.point(point) for point in shape.points], ink)
        return
    points = _closed_points(placement, shape)
    if len(points) > 0 and shape.fill:
        grid.fill(points[:-1], solid)
    grid.outline(points, ink)


def _closed_points(
    placement: DrawingPlacement, shape: PolygonShape | CircleShape
) -> list[tuple[float, float]]:
    """Get the surface's points around a polygon or a circle, the last the first again."""
    if isinstance(shape, PolygonShape):
        points = [placement.point(point) for point in shape.points]
        return [*points, points[0]]
    x, y = placement.point(shape.center)
    radius = shape.radius * placement.scale
    if not _all_finite(x, y, radius):
        return []
    count = min(_MAX_CIRCLE_POINTS, max(12, math.ceil(2 * math.pi * radius)))
    return [
        (
            x + radius * math.cos(2 * math.pi * index / count),
            y + radius * math.sin(2 * math.pi * index / count),
        )
        for index in range(count + 1)
    ]


class ComposeDrawing(Widget):
    """A `DrawingView` in braille characters, its text over them, its description below."""

    DEFAULT_CSS = """
    ComposeDrawing {
        height: 16;
        min-height: 5;
        width: 1fr;
    }
    /* as a label of each role */
    ComposeDrawing > .drawing--title { text-style: bold; }
    ComposeDrawing > .drawing--subtitle { color: $text-muted; text-style: bold; }
    ComposeDrawing > .drawing--caption { color: $text-muted; text-style: italic; }
    ComposeDrawing > .drawing--muted { color: $text-muted; }
    ComposeDrawing > .drawing--error { color: $text-error; }
    ComposeDrawing > .drawing--warning { color: $text-warning; }
    ComposeDrawing > .drawing--success { color: $text-success; }
    """

    COMPONENT_CLASSES: ClassVar[set[str]] = {
        "drawing--body",
        "drawing--title",
        "drawing--subtitle",
        "drawing--caption",
        "drawing--muted",
        "drawing--error",
        "drawing--warning",
        "drawing--success",
    }

    def __init__(self) -> None:
        super().__init__()
        self.shapes: list[Shape] = []
        self.bounds: tuple[float, float, float, float] | None = None
        self.description = ""
        self._shown_description = ""
        self._grid: _Grid | None = None

    def set_drawing(self) -> None:
        """Draw the shapes again at the next paint."""
        self._shown_description = _one_line(
            DrawingView.shown_description(self.description, self.shapes)
        )
        self._grid = None
        self.refresh()

    def _drawn_grid(self, columns: int, rows: int) -> _Grid:
        if self._grid is not None and (self._grid.columns, self._grid.rows) == (columns, rows):
            return self._grid
        bounds = DrawingView.shown_bounds(self.shapes, self.bounds)
        placement = DrawingView.placement(bounds, columns * _DOTS_ACROSS, rows * _DOTS_DOWN)
        grid = _Grid(
            columns,
            rows,
            (
                *placement.point((bounds[0], bounds[3])),
                *placement.point((bounds[2], bounds[1])),
            ),
        )
        for shape in self.shapes:
            _draw_shape(grid, placement, bounds, shape)
        for shape in self.shapes:
            if isinstance(shape, TextShape):
                x, y = placement.point(shape.position)
                # outside, it stays out, as its line does
                if not (DrawingView.in_bounds(shape.position, bounds) and _all_finite(x, y)):
                    continue
                text = _one_line(shape.text)
                width = cell_len(text)
                shift = {TextAnchor.START: 0, TextAnchor.MIDDLE: width // 2, TextAnchor.END: width}
                grid.label(
                    text,
                    math.floor(x / _DOTS_ACROSS) - shift[shape.anchor],
                    math.floor(y / _DOTS_DOWN),
                    shape,
                )
        self._grid = grid
        return grid

    def render_line(self, y: int) -> Strip:
        columns, height = self.size
        base = self.rich_style
        description = self._shown_description
        rows = height - 1 if description else height
        if y < rows:
            role_styles = {
                role: self.get_component_rich_style(f"drawing--{role.name.lower()}", partial=True)
                for role in TextRole
            }
            return self._drawn_grid(columns, rows).strip(y, base, role_styles)
        return Strip([Segment(description, base + Style(dim=True))]).adjust_cell_length(
            columns, base
        )

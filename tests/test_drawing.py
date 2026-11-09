"""Tests of `DrawingView`: its shapes' rules, and what each backend draws."""

from __future__ import annotations

import contextlib
import json
import math
from html.parser import HTMLParser
from typing import TYPE_CHECKING, Any, Optional

import pytest
from attrs import Factory, evolve
from hypothesis import given
from hypothesis import strategies as st
from rich.cells import cell_len

from composeui.core.model import InvalidStateError
from composeui.core.registry import RendererType
from composeui.core.view import (
    ArrowShape,
    CircleShape,
    DimensionShape,
    DrawingView,
    LineShape,
    LineStyle,
    LineWeight,
    MainView,
    PolygonShape,
    PolylineShape,
    Shape,
    TextAnchor,
    TextRole,
    TextShape,
    define_view,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from pytestqt.qtbot import QtBot

    from composeui.qtcore.widgets.qdrawing import QDrawing
    from composeui.textualcore.widgets.composedrawing import ComposeDrawing

RED = "#ff0000"
BLUE = "#0000ff"
NAN = float("nan")
INF = float("inf")


@define_view
class _DrawingMainView(MainView):
    app_title = "Drawing"
    extension = ".drawing"

    drawing: DrawingView = Factory(DrawingView)


@pytest.mark.parametrize(
    ("make", "message"),
    [
        (lambda: LineShape((NAN, 0), (1, 1)), "start"),
        (lambda: ArrowShape((0, 0), (1, INF)), "end"),
        (lambda: DimensionShape((NAN, 0), (1, 1), "a"), "start"),
        (lambda: PolylineShape([(0, 0)]), "points"),
        (lambda: PolylineShape([(0, 0), (NAN, 1)]), "points"),
        (lambda: PolygonShape([(0, 0), (1, 1)]), "points"),
        (lambda: CircleShape((0, 0), 0), "radius"),
        (lambda: CircleShape((0, 0), NAN), "radius"),
        (lambda: CircleShape((NAN, 0), 1), "center"),
        (lambda: TextShape((0, INF), "a"), "position"),
        (lambda: LineShape((0, 0), (1, 1), color="red"), "#rrggbb"),
        (lambda: TextShape((0, 0), "a", color="#ff"), "#rrggbb"),
        (lambda: CircleShape((0, 0), 1, fill_color="red"), "#rrggbb"),
        (lambda: PolygonShape([(0, 0), (1, 0), (0, 1)], fill_color="red"), "#rrggbb"),
        (lambda: DrawingView(bounds=(1, 0, 1, 2)), "bounds"),
        (lambda: DrawingView(bounds=(0, 3, 1, 2)), "bounds"),
        (lambda: DrawingView(bounds=(0, 0, INF, 2)), "bounds"),
        (lambda: DrawingView(bounds=(-1e308, 0, 1e308, 1)), "bounds"),
        (lambda: DrawingView(height=0), "height"),
    ],
)
def test_what_can_t_be_drawn_is_refused_as_it_is_made(make: Any, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        make()


def test_a_study_keeps_each_shape_with_its_own_kind() -> None:
    """A line and an arrow have the same fields: the saved state must tell them apart."""
    shapes: list[Shape] = [
        LineShape((0, 0), (1, 1), color=RED, style=LineStyle.DOTTED, weight=LineWeight.HEAVY),
        ArrowShape((0, 0), (1, 1)),
        PolylineShape([(0, 0), (1, 1)]),
        PolygonShape([(0, 0), (1, 0), (0, 1)], fill=True, fill_color=BLUE),
        CircleShape((0, 0), 2.5),
        TextShape((1, 2), "F", anchor=TextAnchor.END, role=TextRole.TITLE),
        DimensionShape((0, 0), (1, 0), "1 m", color=RED, role=TextRole.TITLE),
    ]
    saved = _DrawingMainView()
    saved.drawing.shapes = shapes
    saved.drawing.bounds = (0, 0, 4, 2)

    loaded = _DrawingMainView()
    loaded.load_state_data(json.loads(json.dumps(saved.state_data())))

    assert loaded.drawing.shapes == shapes
    assert loaded.drawing.bounds == (0, 0, 4, 2)


def test_a_study_with_an_unknown_shape_is_refused() -> None:
    main_view = _DrawingMainView()
    main_view.drawing.shapes = [LineShape((0, 0), (1, 1))]
    data = json.loads(json.dumps(main_view.state_data()))
    main_view.check_state_data(data)  # valid until its shape's kind is unknown
    data["drawing"]["shapes"][0]["_type"] = "HexagonShape"

    with pytest.raises(InvalidStateError):
        main_view.check_state_data(data)


def test_a_study_with_bounds_that_can_t_be_drawn_is_refused() -> None:
    main_view = _DrawingMainView()
    data = json.loads(json.dumps(main_view.state_data()))
    main_view.check_state_data(data)
    data["drawing"]["bounds"] = [3, 0, 1, 1]

    with pytest.raises(InvalidStateError):
        main_view.check_state_data(data)


def test_bounds_that_can_t_be_drawn_are_refused_when_set() -> None:
    view = DrawingView()

    with pytest.raises(ValueError, match="bounds"):
        view.bounds = (1, 0, 1, 2)


@pytest.mark.parametrize(
    ("shapes", "expected"),
    [
        ([], (0, 0, 1, 1)),
        ([LineShape((0, 0), (10, 5))], (-0.8, -0.8, 10.8, 5.8)),
        ([ArrowShape((10, 5), (0, 0))], (-0.8, -0.8, 10.8, 5.8)),
        ([DimensionShape((10, 5), (0, 0), "L")], (-0.8, -0.8, 10.8, 5.8)),
        ([PolylineShape([(0, 0), (10, 5), (5, 1)])], (-0.8, -0.8, 10.8, 5.8)),
        ([PolygonShape([(0, 0), (10, 5), (5, 1)])], (-0.8, -0.8, 10.8, 5.8)),
        ([CircleShape((5, 5), 5)], (-0.8, -0.8, 10.8, 10.8)),
        ([TextShape((2, 3), "alone")], (1, 2, 3, 4)),
        # the margin lost to rounding, and a side too long for a float: an area all the same
        ([LineShape((0, 1e20), (10, 1e20))], (0, 0, 1, 1)),
        ([TextShape((1e17, 0), "far")], (0, 0, 1, 1)),
        ([LineShape((-1e308, 0), (1e308, 0))], (0, 0, 1, 1)),
    ],
)
def test_a_drawing_without_bounds_fits_its_shapes(
    shapes: list[Shape], expected: tuple[float, float, float, float]
) -> None:
    assert DrawingView.shown_bounds(shapes, None) == pytest.approx(expected)


_COORDINATES = st.sampled_from([-2.0, -1.0, 0.0, 0.5, 3.0, 10.0])
_POINTS = st.lists(st.tuples(_COORDINATES, _COORDINATES), min_size=2, max_size=6)


@given(_POINTS, st.sampled_from([1, 80, 333]), st.sampled_from([1, 64, 200]))
def test_fitted_shapes_land_on_the_surface_at_one_scale(
    points: list[tuple[float, float]], width: int, height: int
) -> None:
    shapes: list[Shape] = [PolylineShape(points)]
    placement = DrawingView.placement(DrawingView.shown_bounds(shapes, None), width, height)

    drawn = [placement.point(point) for point in points]

    assert all(0 <= x <= width and 0 <= y <= height for x, y in drawn)
    # distances keep their ratio: the same scale on both axes, none distorted
    assert all(
        math.dist(drawn[0], shown) == pytest.approx(math.dist(points[0], point) * placement.scale)
        for point, shown in zip(points, drawn)
    )


def test_an_area_keeps_its_proportions_centered_with_y_going_up() -> None:
    # 2 by 1 in a square of 100: a scale of 50, with 25 above and below
    placement = DrawingView.placement((0, 0, 2, 1), 100, 100)

    assert placement.point((0, 1)) == (0, 25)  # the top left corner
    assert placement.point((2, 0)) == (100, 75)  # the bottom right corner


def test_an_arrow_head_stands_back_from_its_tip_on_each_side_of_its_line() -> None:
    left, right = DrawingView.arrow_head((0, 0), (10, 0), 5)

    assert left == pytest.approx((5, 2))
    assert right == pytest.approx((5, -2))


def test_an_arrow_without_length_still_has_a_head() -> None:
    left, right = DrawingView.arrow_head((3, 3), (3, 3), 5)

    # pointing right, 5 back from the tip
    assert left == pytest.approx((-2, 5))
    assert right == pytest.approx((-2, 1))


def test_a_drawing_is_described_by_its_description_else_by_its_text() -> None:
    shapes: list[Shape] = [
        TextShape((0, 0), "F"),
        LineShape((0, 0), (1, 1)),
        TextShape((1, 0), "L"),
        DimensionShape((0, 0), (1, 0), "1 m"),
    ]

    assert DrawingView.shown_description("", shapes) == "F, L, 1 m"
    assert DrawingView.shown_description("A beam", shapes) == "A beam"


@pytest.mark.parametrize(
    ("start", "end", "across", "anchor"),
    [
        ((0, 0), (2, 0), (0, 1), TextAnchor.MIDDLE),  # left to right: below
        ((2, 0), (0, 0), (0, -1), TextAnchor.MIDDLE),
        ((0, 0), (0, 2), (1, 0), TextAnchor.START),  # upward: on the right, clear of the line
        ((0, 2), (0, 0), (-1, 0), TextAnchor.END),
        # sloped: a centered text would cross the line
        ((0, 0), (4, 3), (0.6, 0.8), TextAnchor.START),
        ((0, 3), (4, 0), (-0.6, 0.8), TextAnchor.END),
        ((0, 0), (20, 1), (0.04994, 0.99875), TextAnchor.MIDDLE),  # almost level: centered
        ((1, 1), (1, 1), (0, 1), TextAnchor.MIDDLE),  # no direction
        ((-1e308, 0), (1e308, 0), (0, 1), TextAnchor.MIDDLE),  # a side too long for a float
    ],
)
def test_a_dimension_s_label_stands_on_the_right_of_its_line(
    start: tuple[float, float],
    end: tuple[float, float],
    across: tuple[float, float],
    anchor: TextAnchor,
) -> None:
    shape = DimensionShape(start, end, "L", color=RED, role=TextRole.TITLE)

    assert shape.across() == pytest.approx(across, abs=1e-4)
    label = shape.label()
    assert label.position == pytest.approx(((start[0] + end[0]) / 2, (start[1] + end[1]) / 2))
    assert (label.text, label.color, label.anchor, label.role) == (
        "L",
        RED,
        anchor,
        TextRole.TITLE,
    )


# Qt -------------------------------------------------------------------------------------


@pytest.fixture
def qt_drawing(qtbot: QtBot) -> tuple[DrawingView, QDrawing]:
    """Get a drawing of 2 by 1 shown on 200 by 100 pixels: 100 pixels per unit."""
    pytest.importorskip("qtpy")
    from composeui.qtcore.qtrenderer import QtDrawingRenderer  # noqa: PLC0415 (Qt is optional)

    view = DrawingView(bounds=(0, 0, 2, 1))
    view.render(RendererType.QT)
    assert isinstance(view.renderer, QtDrawingRenderer)
    widget = view.renderer.qt_object
    assert widget is not None
    qtbot.addWidget(widget)
    widget.resize(200, 100)
    return view, widget


def _is_color(widget: QDrawing, x: int, y: int, color: str) -> bool:
    return bool(widget.grab().toImage().pixelColor(x, y).name() == color)


def _pixels_off_color(widget: QDrawing, y: int, start: int, end: int, color: str) -> int:
    image = widget.grab().toImage()
    return sum(image.pixelColor(x, y).name() != color for x in range(start, end))


def test_qt_draws_a_line_where_y_goes_up_and_again_when_the_shapes_change(
    qt_drawing: tuple[DrawingView, QDrawing],
) -> None:
    view, widget = qt_drawing

    view.shapes = [LineShape((0, 0.75), (2, 0.75), color=RED)]
    assert _is_color(widget, 100, 25, RED)
    assert not _is_color(widget, 100, 75, RED)

    view.shapes = [LineShape((0, 0.25), (2, 0.25), color=RED)]
    assert _is_color(widget, 100, 75, RED)
    assert not _is_color(widget, 100, 25, RED)


def test_qt_follows_the_bounds(qt_drawing: tuple[DrawingView, QDrawing]) -> None:
    view, widget = qt_drawing
    view.shapes = [LineShape((0, 0.75), (2, 0.75), color=RED)]

    view.bounds = (0, 0.5, 2, 1.5)

    assert _is_color(widget, 100, 75, RED)


@pytest.mark.parametrize(
    ("make", "x", "y"),
    [
        (
            lambda fill: PolygonShape([(0.5, 0.2), (1.5, 0.2), (1, 0.9)], color=RED, fill=fill),
            100,
            50,
        ),
        (lambda fill: CircleShape((1, 0.5), 0.3, color=RED, fill=fill), 100, 50),
    ],
)
def test_qt_fills_a_shape_only_when_asked(
    qt_drawing: tuple[DrawingView, QDrawing], make: Any, x: int, y: int
) -> None:
    view, widget = qt_drawing

    view.shapes = [make(fill=False)]
    assert not _is_color(widget, x, y, RED)

    view.shapes = [make(fill=True)]
    assert _is_color(widget, x, y, RED)


def test_qt_fills_a_shape_in_its_fill_color_inside_its_outline(
    qt_drawing: tuple[DrawingView, QDrawing],
) -> None:
    view, widget = qt_drawing

    view.shapes = [
        PolygonShape(
            [(0.5, 0.2), (1.5, 0.2), (1, 0.9)],
            color=RED,
            fill=True,
            fill_color=BLUE,
            weight=LineWeight.HEAVY,
        )
    ]

    assert _is_color(widget, 100, 50, BLUE)
    assert _is_color(widget, 100, 80, RED)


def test_qt_joins_a_polyline_s_points(qt_drawing: tuple[DrawingView, QDrawing]) -> None:
    view, widget = qt_drawing

    view.shapes = [PolylineShape([(0, 0.5), (1, 0.5), (1, 0)], color=RED)]

    assert _is_color(widget, 50, 50, RED)
    assert _is_color(widget, 100, 75, RED)
    assert not _is_color(widget, 150, 50, RED)


@pytest.mark.parametrize("style", [LineStyle.DASHED, LineStyle.DOTTED, LineStyle.DASH_DOT])
def test_qt_breaks_a_line_of_a_broken_style(
    qt_drawing: tuple[DrawingView, QDrawing], style: LineStyle
) -> None:
    view, widget = qt_drawing

    view.shapes = [LineShape((0, 0.5), (2, 0.5), color=RED)]
    assert _pixels_off_color(widget, 50, 10, 190, RED) == 0

    view.shapes = [LineShape((0, 0.5), (2, 0.5), color=RED, style=style)]
    assert _pixels_off_color(widget, 50, 10, 190, RED) > 0


def test_qt_gives_an_arrow_a_head_of_the_same_size_at_any_scale(
    qt_drawing: tuple[DrawingView, QDrawing],
) -> None:
    view, widget = qt_drawing

    view.shapes = [ArrowShape((0, 0.5), (2, 0.5), color=RED)]
    # the head, wider than the line, just before the tip
    assert _is_color(widget, 191, 47, RED)
    assert not _is_color(widget, 100, 47, RED)

    view.bounds = (0, 0, 20, 10)  # 10 times smaller: the head isn't
    view.shapes = [ArrowShape((0, 5), (20, 5), color=RED)]
    assert _is_color(widget, 191, 47, RED)


def test_qt_gives_a_dimension_ticks_and_a_label_of_the_same_size_at_any_scale(
    qt_drawing: tuple[DrawingView, QDrawing],
) -> None:
    view, widget = qt_drawing

    def check() -> None:
        # at x = 50, 6 pixels on each side of the line at y = 50, and half a pen more at each end
        assert _is_color(widget, 50, 46, RED)
        assert not _is_color(widget, 50, 40, RED)
        assert not _is_color(widget, 100, 46, RED)
        image = widget.grab().toImage()
        background = image.pixelColor(0, 0)
        rows = [
            y
            for y in range(100)
            if abs(y - 50) > 9 and any(image.pixelColor(x, y) != background for x in range(200))
        ]
        # the text, 14 pixels below the line
        assert rows != []
        assert min(rows) > 50

    shape = DimensionShape((0.5, 0.5), (1.5, 0.5), "MM", color=RED, weight=LineWeight.HEAVY)
    view.shapes = [shape]
    check()

    view.bounds = (0, 0, 20, 10)  # 10 times smaller: the ticks and the gap aren't
    view.shapes = [DimensionShape((5, 5), (15, 5), "MM", color=RED, weight=LineWeight.HEAVY)]
    check()


def test_qt_leaves_out_a_dimension_s_tick_past_the_bounds(
    qt_drawing: tuple[DrawingView, QDrawing],
) -> None:
    view, widget = qt_drawing
    view.bounds = (0, 0, 1, 1)  # 100 pixels a unit, from x = 50: the widget shows past them

    view.shapes = [DimensionShape((0.25, 0.5), (1.2, 0.5), "", RED, weight=LineWeight.HEAVY)]

    assert _is_color(widget, 75, 46, RED)
    assert not _is_color(widget, 170, 46, RED)


def test_qt_draws_only_the_head_of_an_arrow_shorter_than_it(
    qt_drawing: tuple[DrawingView, QDrawing],
) -> None:
    view, widget = qt_drawing

    view.shapes = [ArrowShape((1.0, 0.5), (1.08, 0.5), color=RED)]

    assert _is_color(widget, 103, 50, RED)
    assert not _is_color(widget, 96, 50, RED)  # the line would start behind the head


@pytest.mark.parametrize(
    ("anchor", "low", "high"),
    [
        (TextAnchor.START, 100, 200),
        (TextAnchor.MIDDLE, 50, 150),
        (TextAnchor.END, 0, 100),
    ],
)
def test_qt_aligns_a_text_on_its_position(
    qt_drawing: tuple[DrawingView, QDrawing], anchor: TextAnchor, low: int, high: int
) -> None:
    view, widget = qt_drawing

    view.shapes = [TextShape((1, 0.5), "MMMM", anchor=anchor)]

    image = widget.grab().toImage()
    background = image.pixelColor(0, 0)
    inked = [x for x in range(200) if any(image.pixelColor(x, y) != background for y in range(100))]
    assert len(inked) > 0
    assert low <= min(inked)
    assert max(inked) <= high
    if anchor is TextAnchor.MIDDLE:
        assert (min(inked) + max(inked)) / 2 == pytest.approx(100, abs=3)


def test_qt_draws_a_shape_without_color_in_the_theme_s_text_color(
    qt_drawing: tuple[DrawingView, QDrawing],
) -> None:
    from qtpy.QtGui import QPalette  # noqa: PLC0415 (Qt is optional)

    view, widget = qt_drawing
    text_color = widget.palette().color(QPalette.ColorRole.WindowText).name()

    view.shapes = [LineShape((0, 0.5), (2, 0.5))]

    assert _is_color(widget, 100, 50, text_color)


def test_qt_shows_only_the_bounds_in_a_wider_view(
    qt_drawing: tuple[DrawingView, QDrawing],
) -> None:
    view, widget = qt_drawing
    # a square area in 200 by 100 pixels: from 50 to 150 across
    view.bounds = (0, 0, 1, 1)

    view.shapes = [LineShape((-1, 0.5), (2, 0.5), color=RED)]
    assert _is_color(widget, 100, 50, RED)
    assert not _is_color(widget, 20, 50, RED)

    # its line is cut at the edge, and its head, past it, isn't drawn
    view.shapes = [ArrowShape((0, 0.5), (1.2, 0.5), color=RED)]
    assert _is_color(widget, 145, 50, RED)
    assert not _is_color(widget, 165, 50, RED)

    # a head whose tip is inside isn't cut at the edge
    view.shapes = [ArrowShape((1, 1), (1, 0.5), color=RED)]
    assert _is_color(widget, 151, 41, RED)


@pytest.mark.parametrize(
    ("x", "columns"),
    [
        (1.2, lambda inked: len(inked) == 0),  # outside: not drawn
        (0.9, lambda inked: max(inked) > 150),  # inside: runs past the edge
    ],
)
def test_qt_writes_a_text_only_from_inside_the_bounds(
    qt_drawing: tuple[DrawingView, QDrawing], x: float, columns: Any
) -> None:
    view, widget = qt_drawing
    view.bounds = (0, 0, 1, 1)

    view.shapes = [TextShape((x, 0.5), "MMMM")]

    image = widget.grab().toImage()
    background = image.pixelColor(0, 0)
    assert columns(
        [x for x in range(200) if any(image.pixelColor(x, y) != background for y in range(100))]
    )


@pytest.mark.parametrize(
    ("weight", "pixels"),
    [(LineWeight.LIGHT, 1), (LineWeight.NORMAL, 2), (LineWeight.HEAVY, 4)],
)
def test_qt_draws_a_line_as_wide_as_its_weight_in_pixels(
    qt_drawing: tuple[DrawingView, QDrawing], weight: LineWeight, pixels: int
) -> None:
    view, widget = qt_drawing

    view.shapes = [LineShape((0, 0.5), (2, 0.5), color=RED, weight=weight)]

    # a red line takes away the green of what is under it, a pixel's share at each row
    image = widget.grab().toImage()
    background = image.pixelColor(0, 0).greenF()
    covered = sum(1 - image.pixelColor(100, y).greenF() / background for y in range(100))
    assert covered == pytest.approx(pixels, abs=0.2)


def _ink(widget: QDrawing) -> tuple[int, int]:
    """Get how many pixels a text covers, and how tall it is."""
    image = widget.grab().toImage()
    background = image.pixelColor(0, 0)
    inked = [(x, y) for x in range(200) for y in range(100) if image.pixelColor(x, y) != background]
    return len(inked), max(y for _x, y in inked) - min(y for _x, y in inked)


def test_qt_writes_a_title_larger_than_a_body_text(
    qt_drawing: tuple[DrawingView, QDrawing],
) -> None:
    view, widget = qt_drawing

    view.shapes = [TextShape((0.2, 0.5), "Ag")]
    body = _ink(widget)
    view.shapes = [TextShape((0.2, 0.5), "Ag", role=TextRole.TITLE)]

    assert _ink(widget)[1] > body[1]


def _mean_ink(widget: QDrawing) -> tuple[float, float, float, float]:
    """Get a text's mean red, green and blue, and how far they are from the background.

    A font's smoothing can color each edge, so that no pixel has the text's own color. On
    average, its fringes cancel out.
    """
    image = widget.grab().toImage()
    background = image.pixelColor(0, 0)
    inked = [
        color
        for x in range(200)
        for y in range(100)
        for color in [image.pixelColor(x, y)]
        if color != background
    ]
    red = sum(color.redF() for color in inked) / len(inked)
    green = sum(color.greenF() for color in inked) / len(inked)
    blue = sum(color.blueF() for color in inked) / len(inked)
    distance = abs(green - background.greenF())
    return red, green, blue, distance


def test_qt_colors_a_text_by_its_role_unless_it_has_a_color(
    qt_drawing: tuple[DrawingView, QDrawing],
) -> None:
    view, widget = qt_drawing

    view.shapes = [TextShape((0.2, 0.5), "MMMM", role=TextRole.ERROR)]
    red, green, _blue, _distance = _mean_ink(widget)
    assert red - green > 0.1

    view.shapes = [TextShape((0.2, 0.5), "MMMM", role=TextRole.ERROR, color=BLUE)]
    red, _green, blue, _distance = _mean_ink(widget)
    assert blue - red > 0.1

    # a muted text's palette color is half transparent: nearer the background than a body text
    view.shapes = [TextShape((0.2, 0.5), "MMMM")]
    body = _mean_ink(widget)[3]
    view.shapes = [TextShape((0.2, 0.5), "MMMM", role=TextRole.MUTED)]
    assert _mean_ink(widget)[3] < body


def test_qt_describes_the_drawing_to_a_screen_reader(
    qt_drawing: tuple[DrawingView, QDrawing],
) -> None:
    view, widget = qt_drawing

    view.shapes = [TextShape((0, 0), "F = 25 kN")]
    assert widget.accessibleDescription() == "F = 25 kN"

    view.description = "A beam"
    assert widget.accessibleDescription() == "A beam"
    assert widget.toolTip() == "A beam"


def test_qt_shows_a_description_with_tags_as_it_is_in_its_tooltip(
    qt_drawing: tuple[DrawingView, QDrawing],
) -> None:
    from qtpy.QtGui import QTextDocument  # noqa: PLC0415 (Qt is optional)

    view, widget = qt_drawing

    view.description = "a <b>bold</b> value"

    document = QTextDocument()
    document.setHtml(widget.toolTip())
    assert document.toPlainText() == "a <b>bold</b> value"


def test_qt_sets_the_height_and_gives_it_back_to_the_layout(
    qt_drawing: tuple[DrawingView, QDrawing],
) -> None:
    view, widget = qt_drawing

    view.height = 150
    assert (widget.minimumHeight(), widget.maximumHeight()) == (150, 150)

    view.height = None
    assert widget.minimumHeight() == 0
    assert widget.maximumHeight() > 150


def test_qt_keeps_its_widget_when_rendered_again(
    qt_drawing: tuple[DrawingView, QDrawing],
) -> None:
    from composeui.qtcore.qtrenderer import QtDrawingRenderer  # noqa: PLC0415 (Qt is optional)

    view, widget = qt_drawing
    assert isinstance(view.renderer, QtDrawingRenderer)

    view.renderer.render()

    assert view.renderer.qt_object is widget


def test_qt_gives_a_drawing_room_in_a_window(qtbot: QtBot) -> None:
    from composeui.qtcore.qtrenderer import QtMainRenderer  # noqa: PLC0415 (Qt is optional)
    from composeui.qtcore.widgets.qdrawing import QDrawing  # noqa: PLC0415 (Qt is optional)

    main_view = _DrawingMainView()
    main_view.render(RendererType.QT)
    assert isinstance(main_view.renderer, QtMainRenderer)
    window = main_view.renderer.qt_object
    assert window is not None
    qtbot.addWidget(window)
    window.show()

    drawing = window.findChild(QDrawing)
    assert drawing is not None
    qtbot.waitUntil(lambda: drawing.height() > 100)


# Textual --------------------------------------------------------------------------------

#: 40 by 16 cells, so 80 by 64 dots: with these bounds, a unit is a dot
_DOTS_BOUNDS = (0.0, 0.0, 80.0, 64.0)
_SIZE = (40, 16 + 4)


@contextlib.asynccontextmanager
async def _running(
    main_view: _DrawingMainView, size: tuple[int, int] = _SIZE
) -> AsyncGenerator[tuple[Any, Any, ComposeDrawing], None]:
    """Run a main view on Textual, and give its app, its pilot and its drawing's widget."""
    pytest.importorskip("textual")
    from composeui.textualcore.textualrenderer import TextualMainRenderer  # noqa: PLC0415
    from composeui.textualcore.widgets.composedrawing import (  # noqa: PLC0415 (optional)
        ComposeDrawing,
    )

    main_view.render(RendererType.TEXTUAL)
    assert isinstance(main_view.renderer, TextualMainRenderer)
    app = main_view.renderer.app
    assert app is not None
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        yield app, pilot, app.query_one(ComposeDrawing)


async def _textual_rows(shapes: list[Shape], **fields: Any) -> tuple[list[str], list[Any]]:
    """Get a drawing's rows of text, and each row's strip, as a terminal shows them."""
    main_view = _DrawingMainView()
    main_view.drawing.bounds = _DOTS_BOUNDS
    main_view.drawing.shapes = shapes
    for name, value in fields.items():
        setattr(main_view.drawing, name, value)
    async with _running(main_view) as (_app, _pilot, widget):
        strips = [widget.render_line(y) for y in range(widget.size.height)]
    return [strip.text for strip in strips], strips


def _color_at(strip: Any, column: int) -> str | None:
    position = 0
    for segment in strip:
        if position <= column < position + len(segment.text):
            color = segment.style.color if segment.style else None
            return None if color is None else color.get_truecolor().hex
        position += len(segment.text)
    return None


@pytest.mark.asyncio
async def test_textual_draws_a_line_in_braille_with_y_going_up() -> None:
    rows, _ = await _textual_rows([LineShape((0, 61.5), (79, 61.5))])

    assert rows[0] == "⠤" * 40  # the dots of the third row of each cell of the top row
    assert rows[1].strip() == ""


@pytest.mark.asyncio
async def test_textual_draws_a_diagonal_dot_by_dot() -> None:
    rows, _ = await _textual_rows([LineShape((0, 64), (64, 0))])

    # one dot down for each dot across, two to a cell's width: finer than the cell
    assert rows[0][:2] == "⠑⢄"


@pytest.mark.asyncio
async def test_textual_keeps_a_circle_round() -> None:
    rows, _ = await _textual_rows([CircleShape((40, 32), 20)])

    drawn_rows = [index for index, row in enumerate(rows) if row.strip()]
    columns = [index for row in rows for index, char in enumerate(row) if char != " "]
    across = (max(columns) - min(columns) + 1) * 2
    down = (max(drawn_rows) - min(drawn_rows) + 1) * 4
    assert across == pytest.approx(down, abs=4)
    assert rows[8][20] == " "  # hollow


@pytest.mark.parametrize(
    "shape",
    [
        PolygonShape([(20, 16), (60, 16), (40, 56)], fill=True),
        CircleShape((40, 32), 16, fill=True),
    ],
)
@pytest.mark.asyncio
async def test_textual_fills_a_shape_when_asked(shape: Shape) -> None:
    rows, _ = await _textual_rows([shape])
    assert rows[8][20] == "⣿"

    assert isinstance(shape, (PolygonShape, CircleShape))
    rows, _ = await _textual_rows([evolve(shape, fill=False)])
    assert rows[8][20] == " "


@pytest.mark.asyncio
async def test_textual_fills_a_shape_in_its_fill_color_inside_its_outline() -> None:
    shape = PolygonShape([(20, 16), (60, 16), (40, 56)], color=RED, fill=True, fill_color=BLUE)

    rows, strips = await _textual_rows([shape])

    assert _color_at(strips[8], 20) == BLUE
    edge = next(column for column, cell in enumerate(rows[8]) if cell != " ")
    assert _color_at(strips[8], edge) == RED


@pytest.mark.asyncio
async def test_textual_joins_a_polyline_s_points() -> None:
    rows, _ = await _textual_rows([PolylineShape([(0, 61.5), (40.5, 61.5), (40.5, 0)])])

    assert rows[0][:20].count("⠤") == 20
    assert rows[8][20] != " "
    assert rows[8][30] == " "


@pytest.mark.asyncio
@pytest.mark.parametrize(("end_x", "ticks"), [(70, 2), (90, 1)])  # 90: past the bounds
async def test_textual_draws_a_dimension_s_ticks_and_its_label_below(
    end_x: float, ticks: int
) -> None:
    dimension, _ = await _textual_rows(
        [DimensionShape((10, 32), (end_x, 32), "6 m")], description="d"
    )
    line, _ = await _textual_rows([LineShape((10, 32), (end_x, 32))], description="d")

    label_row = next(row for row, text in enumerate(dimension) if "6 m" in text)
    line_row = next(row for row, text in enumerate(line) if text.strip("d ") != "")
    assert label_row > line_row
    changed = {
        column
        for column in range(40)
        for row in range(len(line))
        if row != label_row and dimension[row][column] != line[row][column]
    }
    assert len(changed) == ticks


@pytest.mark.asyncio
async def test_textual_draws_an_arrow_s_head_at_its_end_only() -> None:
    arrow, _ = await _textual_rows([ArrowShape((0, 32), (70, 32))])
    line, _ = await _textual_rows([LineShape((0, 32), (70, 32))])

    changed = [
        column
        for column in range(40)
        if any(arrow[row][column] != line[row][column] for row in range(16))
    ]
    assert len(changed) > 0
    assert min(changed) >= 31  # 5 dots back from the tip, at column 35


@pytest.mark.parametrize(
    "shape",
    [
        LineShape((-500, -500), (-400, -400)),  # no side of the view crossed
        LineShape((0, -400), (79, -400)),  # level with the view, under it
    ],
)
@pytest.mark.asyncio
async def test_textual_leaves_out_what_falls_outside_the_view(shape: Shape) -> None:
    rows, _ = await _textual_rows([shape])

    assert all(row.strip() == "" for row in rows)


@pytest.mark.asyncio
async def test_textual_draws_the_part_in_view_of_a_line_reaching_far_outside() -> None:
    rows, _ = await _textual_rows([LineShape((-1e12, 61.5), (1e12, 61.5))])

    assert rows[0] == "⠤" * 40


@pytest.mark.asyncio
async def test_textual_draws_a_huge_circle_without_counting_its_whole_outline() -> None:
    rows, _ = await _textual_rows([CircleShape((40, -1e12), 1e12 + 2.5)])

    # its top, 2.5 up from the bottom edge: the last of the 16 rows
    assert rows[-1].strip() != ""
    assert all(row.strip() == "" for row in rows[:-1])


@pytest.mark.parametrize(
    "shape",
    [
        LineShape((0, 0), (1e308, 0)),
        PolygonShape([(0, 0), (1e308, 0), (0, 1e308)], fill=True),
        CircleShape((0, 0), 1e308, fill=True),
        ArrowShape((0, 0), (1e308, 1e308)),
        TextShape((1e308, 0), "far"),
    ],
)
@pytest.mark.asyncio
async def test_textual_leaves_blank_what_is_too_large_for_a_float_at_its_scale(
    shape: Shape,
) -> None:
    rows, _ = await _textual_rows([shape], bounds=(0.0, 0.0, 1e-300, 1e-300), description="far")

    assert all(row.strip() == "" for row in rows[:-1])


@pytest.mark.asyncio
async def test_textual_draws_each_shape_in_its_color_and_the_rest_in_the_theme_s() -> None:
    rows, strips = await _textual_rows(
        [
            LineShape((0, 61.5), (79, 61.5), color=RED),
            LineShape((0, 45.5), (79, 45.5)),
            TextShape((40, 30), "F", color=BLUE),
        ]
    )

    assert _color_at(strips[0], 3) == RED
    assert _color_at(strips[4], 3) not in {RED, BLUE, None}
    column = next(row for row in rows if "F" in row).index("F")
    row_index = next(index for index, row in enumerate(rows) if "F" in row)
    assert _color_at(strips[row_index], column) == BLUE


@pytest.mark.parametrize(
    ("anchor", "column"), [(TextAnchor.START, 20), (TextAnchor.MIDDLE, 18), (TextAnchor.END, 16)]
)
@pytest.mark.asyncio
async def test_textual_writes_a_text_readable_over_the_shapes(
    anchor: TextAnchor, column: int
) -> None:
    rows, _ = await _textual_rows(
        [TextShape((40, 32), "abcd", anchor=anchor), LineShape((0, 30), (79, 30))]
    )

    row = next(row for row in rows if "abcd" in row)
    assert row.index("abcd") == column


@pytest.mark.asyncio
async def test_textual_moves_a_text_off_another_one_so_both_read() -> None:
    rows, _ = await _textual_rows([TextShape((40, 32), "first"), TextShape((40, 32), "other")])

    drawn = rows[:-1]  # the last row is the description, which names both
    assert sum("first" in row for row in drawn) == 1
    assert sum("other" in row for row in drawn) == 1


@pytest.mark.parametrize("position", [(200.0, 32.0), (-50.0, 32.0), (40.0, 200.0), (40.0, -50.0)])
@pytest.mark.asyncio
async def test_textual_leaves_out_a_text_outside_the_view(position: tuple[float, float]) -> None:
    rows, _ = await _textual_rows([TextShape(position, "away")], description="d")

    assert all("away" not in row for row in rows)


@pytest.mark.parametrize(
    "overwritten_at",
    [
        (2.0, 1.0),  # on a wide character's second cell
        (2.0, 3.0),  # on a wide character's first cell
    ],
)
@pytest.mark.asyncio
async def test_textual_keeps_the_row_s_width_when_a_label_overwrites_a_wide_character(
    overwritten_at: tuple[float, float],
) -> None:
    x, wide_x = overwritten_at
    shapes: list[Shape] = [TextShape((wide_x - 1, 32), "力力") for _ in range(15)]
    shapes.append(TextShape((x, 32), "x"))  # every row of the 15 is taken

    rows, _ = await _textual_rows(shapes, description="d")

    assert any("x" in row for row in rows[:-1])
    assert all(cell_len(row) == 40 for row in rows)


#: half of the width: 40 dots wide, from column 10 to 30
_NARROW_BOUNDS = (0.0, 0.0, 40.0, 64.0)


@pytest.mark.asyncio
async def test_textual_shows_only_the_bounds_in_a_wider_view() -> None:
    rows, _ = await _textual_rows([LineShape((-40, 61.5), (80, 61.5))], bounds=_NARROW_BOUNDS)

    assert rows[0] == " " * 10 + "⠤" * 20 + " " * 10


@pytest.mark.asyncio
async def test_textual_leaves_out_a_head_past_the_bounds() -> None:
    line, _ = await _textual_rows([LineShape((0, 32), (42, 32))], bounds=_NARROW_BOUNDS)
    arrow, _ = await _textual_rows([ArrowShape((0, 32), (42, 32))], bounds=_NARROW_BOUNDS)

    assert arrow == line


@pytest.mark.parametrize(("x", "shown"), [(45.0, False), (39.0, True)])
@pytest.mark.asyncio
async def test_textual_writes_a_text_only_from_inside_the_bounds(x: float, shown: bool) -> None:
    rows, _ = await _textual_rows(
        [TextShape((x, 32), "label")], bounds=_NARROW_BOUNDS, description="d"
    )

    assert any("label" in row for row in rows) is shown


@pytest.mark.asyncio
async def test_textual_leaves_blank_an_area_too_small_for_a_float_scale() -> None:
    rows, _ = await _textual_rows(
        [LineShape((0, 0), (1e-320, 1e-320)), TextShape((0, 0), "tiny")],
        bounds=(0.0, 0.0, 1e-320, 1e-320),
        description="d",
    )

    assert all(row.strip() == "" for row in rows[:-1])


@pytest.mark.asyncio
async def test_textual_draws_a_heavy_line_two_dots_wide() -> None:
    rows, _ = await _textual_rows([LineShape((0, 61.5), (79, 61.5), weight=LineWeight.HEAVY)])
    assert rows[0] == "⣤" * 40  # the third and fourth rows of dots of each cell

    tall, _ = await _textual_rows([LineShape((40.5, 64), (40.5, 0), weight=LineWeight.HEAVY)])
    assert tall[8][20] == "⣿"


@pytest.mark.asyncio
async def test_textual_dims_a_light_line_and_leaves_the_others() -> None:
    _, strips = await _textual_rows(
        [
            LineShape((0, 61.5), (79, 61.5), weight=LineWeight.LIGHT),
            LineShape((0, 45.5), (79, 45.5)),
        ]
    )

    assert next(iter(strips[0])).style.dim is True
    assert not next(iter(strips[4])).style.dim


@pytest.mark.parametrize(
    "shape",
    [
        CircleShape((40, 32), 16, fill=True, weight=LineWeight.LIGHT),
        ArrowShape((0, 32), (70, 32), weight=LineWeight.LIGHT),
    ],
)
@pytest.mark.asyncio
async def test_textual_dims_a_light_line_but_not_a_shape_s_inside_or_an_arrow_s_head(
    shape: Shape,
) -> None:
    _, strips = await _textual_rows([shape])

    assert any(segment.text.strip() and not segment.style.dim for segment in strips[8])


@pytest.mark.parametrize(
    ("role", "attribute"),
    [
        (TextRole.TITLE, "bold"),
        (TextRole.SUBTITLE, "bold"),
        (TextRole.CAPTION, "italic"),
    ],
)
@pytest.mark.asyncio
async def test_textual_shows_a_text_s_role_in_its_style(role: TextRole, attribute: str) -> None:
    rows, strips = await _textual_rows([TextShape((0, 32), "note", role=role)], description="d")

    index = next(i for i, row in enumerate(rows) if "note" in row)
    segment = next(s for s in strips[index] if "note" in s.text)
    assert getattr(segment.style, attribute) is True


@pytest.mark.asyncio
async def test_textual_colors_a_text_by_its_role_unless_it_has_a_color() -> None:
    def color_of(rows: list[str], strips: list[Any]) -> str | None:
        index = next(i for i, row in enumerate(rows) if "note" in row)
        return _color_at(strips[index], rows[index].index("note"))

    body = color_of(*await _textual_rows([TextShape((0, 32), "note")], description="d"))
    error = color_of(
        *await _textual_rows([TextShape((0, 32), "note", role=TextRole.ERROR)], description="d")
    )
    own = color_of(
        *await _textual_rows(
            [TextShape((0, 32), "note", role=TextRole.ERROR, color=BLUE)], description="d"
        )
    )

    assert error != body
    assert own == BLUE


@pytest.mark.asyncio
async def test_textual_keeps_a_text_inside_at_the_right_edge() -> None:
    rows, _ = await _textual_rows([TextShape((79, 32), "edge")])

    assert any(row.endswith("edge") for row in rows)


@pytest.mark.asyncio
async def test_textual_cuts_a_text_wider_than_the_view() -> None:
    rows, _ = await _textual_rows([TextShape((0, 32), "x" * 50)])

    assert ("x" * 40) in rows


@pytest.mark.asyncio
async def test_textual_aligns_the_columns_after_a_wide_character() -> None:
    rows, strips = await _textual_rows([TextShape((0, 32), "力 = 1")])

    row_index = next(index for index, row in enumerate(rows[:-1]) if "力" in row)
    assert rows[row_index].strip() == "力 = 1"
    assert strips[row_index].cell_length == 40


@pytest.mark.parametrize(
    ("text", "shown"),
    [
        ("two\nlines", "two lines"),  # a new line would break the row
        ("a\x1b[31mb", "a[31mb"),  # an escape would reach the terminal
        ("cafe\u0301", "caf\u00e9"),  # a combining accent would replace its letter
    ],
)
@pytest.mark.asyncio
async def test_textual_writes_a_text_as_cells_of_one_row(text: str, shown: str) -> None:
    rows, _ = await _textual_rows([TextShape((0, 32), text)])

    assert any(row.strip() == shown for row in rows[:-1])
    assert rows[-1].strip() == shown  # the description, made of the text


@pytest.mark.asyncio
async def test_textual_overwrites_a_row_only_when_every_row_is_taken() -> None:
    shapes: list[Shape] = [TextShape((0, 32), f"label{index:02}") for index in range(17)]

    rows, _ = await _textual_rows(shapes)

    drawn = rows[:-1]  # the last row is the description
    assert all("label" in row for row in drawn)
    assert any("label16" in row for row in drawn)


@pytest.mark.asyncio
async def test_textual_describes_the_drawing_on_its_last_row() -> None:
    rows, _ = await _textual_rows(
        [LineShape((0, 0), (79, 0))], description="A beam\non two supports"
    )

    assert rows[-1].rstrip() == "A beam on two supports"
    assert len(rows[-1]) == 40


@pytest.mark.asyncio
async def test_textual_draws_again_for_each_change_that_moves_its_dots() -> None:
    main_view = _DrawingMainView()
    main_view.drawing.bounds = _DOTS_BOUNDS
    main_view.drawing.shapes = [LineShape((0, 61.5), (79, 61.5))]
    async with _running(main_view) as (_app, pilot, widget):
        assert widget.render_line(0).text == "⠤" * 40

        main_view.drawing.shapes = [LineShape((0, 45.5), (79, 45.5))]
        await pilot.pause()
        assert widget.render_line(0).text.strip() == ""
        assert widget.render_line(4).text == "⠤" * 40

        # a description takes a row from the shapes, which rescale
        main_view.drawing.description = "A beam"
        await pilot.pause()
        assert widget.render_line(15).text.strip() == "A beam"
        assert "⠤" * 40 not in widget.render_line(4).text

        main_view.drawing.description = ""
        main_view.drawing.bounds = (0.0, 0.0, 80.0, 128.0)
        await pilot.pause()
        assert widget.render_line(4).text.strip() == ""

        await pilot.resize_terminal(60, 20)
        await pilot.pause()
        assert len(widget.render_line(0).text) == 60


@pytest.mark.asyncio
async def test_textual_follows_the_theme_without_a_change_of_the_shapes() -> None:
    main_view = _DrawingMainView()
    main_view.drawing.bounds = _DOTS_BOUNDS
    main_view.drawing.shapes = [LineShape((0, 61.5), (79, 61.5))]
    async with _running(main_view) as (app, pilot, widget):
        app.theme = "textual-dark"
        await pilot.pause()
        dark = _color_at(widget.render_line(0), 3)

        app.theme = "textual-light"
        await pilot.pause()

        assert _color_at(widget.render_line(0), 3) != dark


def test_textual_keeps_its_widget_when_rendered_again() -> None:
    from composeui.textualcore.textualrenderer import TextualDrawingRenderer  # noqa: PLC0415

    view = DrawingView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualDrawingRenderer)
    widget = view.renderer.widget

    view.renderer.render()

    assert view.renderer.widget is widget


@pytest.mark.parametrize(("height", "rows"), [(320, 20), (16, 5)])
@pytest.mark.asyncio
async def test_textual_turns_a_height_in_pixels_into_rows(height: int, rows: int) -> None:
    drawn, _ = await _textual_rows([], height=height)

    assert len(drawn) == rows


@pytest.mark.asyncio
async def test_textual_gives_the_height_back_to_its_style() -> None:
    main_view = _DrawingMainView()
    main_view.drawing.height = 320
    async with _running(main_view, size=(40, 30)) as (_app, pilot, widget):
        main_view.drawing.height = None
        await pilot.pause()
        assert widget.size.height == 16


# The web --------------------------------------------------------------------------------


class _Elements(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.elements: list[tuple[str, dict[str, str]]] = []
        self.texts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.elements.append((tag, {name: value or "" for name, value in attrs}))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_data(self, data: str) -> None:
        self.texts.append(data)


def _web(view: DrawingView) -> _Elements:
    pytest.importorskip("starlette")
    from composeui.webcore.webrenderer import WebDrawingRenderer  # noqa: PLC0415 (optional)

    view.render(RendererType.WEB)
    assert isinstance(view.renderer, WebDrawingRenderer)
    parser = _Elements()
    parser.feed(str(view.renderer.to_html()))
    return parser


def _element(parser: _Elements, tag: str) -> dict[str, str]:
    return next(attributes for name, attributes in parser.elements if name == tag)


@pytest.mark.parametrize(
    ("shape", "tag", "expected"),
    [
        (LineShape((1, 1), (3, 2)), "line", {"x1": "1", "y1": "3", "x2": "3", "y2": "2"}),
        (PolylineShape([(0, 0), (1, 4)]), "polyline", {"points": "0,4 1,0"}),
        (PolygonShape([(0, 0), (1, 4), (2, 0)]), "polygon", {"points": "0,4 1,0 2,4"}),
        (CircleShape((1, 1), 0.5), "circle", {"cx": "1", "cy": "3", "r": "0.5"}),
    ],
)
def test_the_web_places_each_shape_with_y_going_up(
    shape: Shape, tag: str, expected: dict[str, str]
) -> None:
    element = _element(_web(DrawingView(shapes=[shape], bounds=(0, 0, 8, 4))), tag)

    assert expected.items() <= element.items()
    assert element["vector-effect"] == "non-scaling-stroke"


def test_the_web_stops_an_arrow_s_line_inside_its_head() -> None:
    # 72 pixels a unit at the most: the head is 0.15 long, and the line stops at half of it
    shape = ArrowShape((1, 1), (3, 1))

    line = _element(_web(DrawingView(shapes=[shape], bounds=(0, 0, 8, 4))), "line")

    assert float(line["x2"]) == pytest.approx(3 - 11 / 72 / 2, abs=1e-3)
    assert line["y2"] == "3"


def test_the_web_places_a_dimension_s_ticks_and_label_in_pixels_around_its_line() -> None:
    shape = DimensionShape((2, 1), (6, 1), "<4 m>", color=RED)

    parser = _web(DrawingView(shapes=[shape], bounds=(0, 0, 8, 4)))

    lines = [attributes for tag, attributes in parser.elements if tag == "line"]
    assert len(lines) == 3
    line, *ticks = lines
    assert (line["x1"], line["y1"], line["x2"], line["y2"]) == ("2", "3", "6", "3")
    for tick in ticks:
        assert (float(tick["x1"]), float(tick["y1"])) == (0, -6)
        assert (float(tick["x2"]), float(tick["y2"])) == (0, 6)
        assert tick["stroke"] == RED
    tick_svgs = [a for tag, a in parser.elements if tag == "svg" and "x" in a]
    assert [(a["x"], a["y"]) for a in tick_svgs] == [("25%", "75%"), ("75%", "75%")]
    text = _element(parser, "text")
    assert (text["x"], text["y"], text["dx"], text["dy"]) == ("50%", "75%", "0", "14")
    assert text["text-anchor"] == "middle"
    assert "<4 m>" in parser.texts


@pytest.mark.parametrize(
    ("start", "end", "ticks", "has_label"),
    [
        ((2, 1), (9, 1), 1, True),  # one end out
        ((9, 1), (11, 1), 0, False),  # all out, its middle too
    ],
)
def test_the_web_leaves_out_a_dimension_s_marks_past_the_bounds(
    start: tuple[float, float], end: tuple[float, float], ticks: int, has_label: bool
) -> None:
    shape = DimensionShape(start, end, "L")

    parser = _web(DrawingView(shapes=[shape], bounds=(0, 0, 8, 4)))

    assert len([1 for tag, _a in parser.elements if tag == "line"]) == 1 + ticks
    assert ("text" in [tag for tag, _a in parser.elements]) is has_label


def test_the_web_draws_only_the_head_of_an_arrow_shorter_than_it() -> None:
    shape = ArrowShape((1, 1), (1.1, 1))

    parser = _web(DrawingView(shapes=[shape], bounds=(0, 0, 8, 4)))

    assert "line" not in [tag for tag, _attributes in parser.elements]
    assert "polygon" in [tag for tag, _attributes in parser.elements]


def test_the_web_keeps_inside_the_bounds_what_they_leave_out() -> None:
    shapes: list[Shape] = [
        TextShape((9, 1), "out"),
        ArrowShape((1, 1), (9, 1)),
        CircleShape((9, 1), 1),
    ]

    parser = _web(DrawingView(shapes=shapes, bounds=(0, 0, 8, 4), description="d"))

    assert parser.texts == []
    assert "polygon" not in [tag for tag, _attributes in parser.elements]
    # a nested `<svg>` hides its overflow unless told otherwise; only the root shows it
    nested = [attributes for tag, attributes in parser.elements if tag == "svg"][1:]
    assert len(nested) == 2
    assert all("overflow" not in attributes for attributes in nested)


def test_the_web_keeps_the_area_s_proportions_at_the_view_s_height() -> None:
    root = _element(_web(DrawingView(bounds=(0, 0, 8, 4), height=100)), "div")

    assert "aspect-ratio: 8 / 4" in root["style"]
    assert "min(100%, 200px)" in root["style"]


@pytest.mark.parametrize(
    ("style", "dashes"),
    [
        (LineStyle.SOLID, None),
        (LineStyle.DASHED, "8 5"),
        (LineStyle.DOTTED, "2 4"),
        (LineStyle.DASH_DOT, "8 4 2 4"),
    ],
)
def test_the_web_draws_a_line_in_its_style(style: LineStyle, dashes: Optional[str]) -> None:
    line = _element(_web(DrawingView(shapes=[LineShape((0, 0), (1, 1), style=style)])), "line")

    assert line.get("stroke-dasharray") == dashes
    assert line["stroke"] == "currentColor"


@pytest.mark.parametrize(
    ("weight", "width"),
    [(LineWeight.LIGHT, "1"), (LineWeight.NORMAL, "2"), (LineWeight.HEAVY, "4")],
)
@pytest.mark.parametrize(
    "shape",
    [LineShape((0, 0), (8, 4)), ArrowShape((0, 0), (8, 4))],
)
def test_the_web_draws_a_line_as_wide_as_its_weight(
    shape: Any, weight: LineWeight, width: str
) -> None:
    view = DrawingView(shapes=[evolve(shape, weight=weight)], bounds=(0, 0, 8, 4))

    assert _element(_web(view), "line")["stroke-width"] == width


@pytest.mark.parametrize(
    ("role", "classes"),
    [
        (TextRole.TITLE, "text-xl font-bold"),
        (TextRole.ERROR, "text-error"),
    ],
)
def test_the_web_shows_a_text_s_role_with_the_classes_of_a_label(
    role: TextRole, classes: str
) -> None:
    text = _element(_web(DrawingView(shapes=[TextShape((0, 0), "F", role=role)])), "text")

    assert text["class"] == classes
    assert text["fill"] == "currentColor"


def test_the_web_writes_a_body_text_without_a_class() -> None:
    assert "class" not in _element(_web(DrawingView(shapes=[TextShape((0, 0), "F")])), "text")


def test_the_web_fills_a_shape_only_when_asked() -> None:
    shapes: list[Shape] = [
        CircleShape((0, 0), 1, color=RED, fill=True),
        CircleShape((5, 5), 1, color=RED),
        CircleShape((9, 9), 1, color=RED, fill=True, fill_color=BLUE),
        CircleShape((12, 12), 1, color=RED, fill_color=BLUE),
    ]

    circles = [a for tag, a in _web(DrawingView(shapes=shapes)).elements if tag == "circle"]

    assert [a["fill"] for a in circles] == [RED, "none", BLUE, "none"]
    assert [a["stroke"] for a in circles] == [RED] * 4


def test_the_web_points_an_arrow_s_head_along_its_line_at_its_end() -> None:
    # straight down, in a drawing whose y goes up: the head's back is above its tip
    shape = ArrowShape((1, 3), (1, 1), color=RED)

    parser = _web(DrawingView(shapes=[shape], bounds=(0, 0, 2, 4)))

    head = _element(parser, "polygon")
    corners = [tuple(map(float, point.split(","))) for point in head["points"].split()]
    assert corners[0] == (0, 0)
    assert all(y < 0 for _x, y in corners[1:])
    assert corners[1][0] == pytest.approx(-corners[2][0])
    assert head["fill"] == RED
    positioned = [a for tag, a in parser.elements if tag == "svg" and "x" in a]
    assert (positioned[0]["x"], positioned[0]["y"]) == ("50%", "75%")


@pytest.mark.parametrize(
    ("anchor", "expected"),
    [(TextAnchor.START, "start"), (TextAnchor.MIDDLE, "middle"), (TextAnchor.END, "end")],
)
def test_the_web_writes_a_text_at_a_share_of_the_area(anchor: TextAnchor, expected: str) -> None:
    parser = _web(DrawingView(shapes=[TextShape((1, 1), "F", anchor=anchor)], bounds=(0, 0, 4, 2)))

    text = _element(parser, "text")
    assert (text["x"], text["y"], text["text-anchor"]) == ("25%", "50%", expected)


def test_the_web_shows_a_shape_s_text_and_the_description_as_text_not_markup() -> None:
    hostile = '<script>alert("x")</script>'

    parser = _web(DrawingView(shapes=[TextShape((0, 0), hostile)], description=hostile))

    assert "script" not in [tag for tag, _attributes in parser.elements]
    assert parser.texts == [hostile]
    assert _element(parser, "svg")["aria-label"] == hostile

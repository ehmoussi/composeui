"""Click the bat: `python -m examples.batman --backend qt` (or `web`).

The Batman logo: a yellow oval, its upper and lower halves filled down to 0, under the
bat's upper and lower edges filled in black; each series has the logo's color, whatever
the theme. Clicking the chart inside the bat says so: the chart's `clicked` emits the
point, which the view checks against the bat's edges. Textual draws the logo too, but a
terminal has no pointer to click it with.
"""

import math
from collections.abc import Callable

from composeui.core import application
from composeui.core.registry import RendererType
from composeui.core.view import (
    ChartView,
    LabelView,
    MainView,
    Series,
    child,
    define_view,
)


def _wing(x: float) -> float:
    return 3 * math.sqrt(max(0.0, 1 - (x / 7) ** 2))


def _shoulder(x: float) -> float:
    return 1.5 - 0.5 * abs(x) - 6 * math.sqrt(10) / 14 * (math.sqrt(3 - x**2 + 2 * abs(x)) - 2)


def _tail(x: float) -> float:
    return (
        abs(x / 2)
        - (3 * math.sqrt(33) - 7) / 112 * x**2
        + math.sqrt(max(0.0, 1 - (abs(abs(x) - 2) - 1) ** 2))
        - 3
    )


#: the pieces of the bat's upper edge, from left to right: each a range of x and its curve
UPPER: tuple[tuple[float, float, Callable[[float], float]], ...] = (
    (-7, -3, _wing),
    (-3, -1, _shoulder),
    (-1, -0.75, lambda x: 9 - 8 * abs(x)),  # an ear
    (-0.75, -0.5, lambda x: 3 * abs(x) + 0.75),
    (-0.5, 0.5, lambda _x: 2.25),  # the head
    (0.5, 0.75, lambda x: 3 * abs(x) + 0.75),
    (0.75, 1, lambda x: 9 - 8 * abs(x)),
    (1, 3, _shoulder),
    (3, 7, _wing),
)
#: the pieces of its lower edge
LOWER: tuple[tuple[float, float, Callable[[float], float]], ...] = (
    (-7, -4, lambda x: -_wing(x)),
    (-4, 4, _tail),
    (4, 7, lambda x: -_wing(x)),
)
#: the points each piece is drawn with
POINTS_PER_PIECE = 200
#: the oval's half width and half height, around the bat
OVAL = (8.0, 4.0)
#: the logo's colors
YELLOW = "#ffd700"
BLACK = "#000000"


def _edge(pieces: tuple[tuple[float, float, Callable[[float], float]], ...], x: float) -> float:
    """Get the edge's height at `x`, NaN past the bat."""
    for x_min, x_max, curve in pieces:
        if x_min <= x <= x_max:
            return curve(x)
    return math.nan


def is_in_bat(x: float, y: float) -> bool:
    """Check whether the point is inside the bat, between its edges."""
    return _edge(LOWER, x) <= y <= _edge(UPPER, x)


def _oval(x: float) -> float:
    width, height = OVAL
    return height * math.sqrt(max(0.0, 1 - (x / width) ** 2))


def _outline(
    name: str,
    pieces: tuple[tuple[float, float, Callable[[float], float]], ...],
    color: str,
) -> Series:
    """Get the edge drawn by `pieces`, filled down to 0 in `color`."""
    xs: list[float] = []
    for x_min, x_max, _curve in pieces:
        step = (x_max - x_min) / POINTS_PER_PIECE
        xs.extend(x_min + index * step for index in range(POINTS_PER_PIECE))
    xs.append(pieces[-1][1])
    return Series(name=name, x=xs, y=[_edge(pieces, x) for x in xs], color=color, fill=True)


@define_view
class BatmanMainView(MainView):
    app_title = "Batman"
    extension = ".batman"

    message: LabelView = child(LabelView, text="Click the bat")
    chart: ChartView = child(
        ChartView,
        title="Batman",
        # tall enough for the logo's proportions, twice as wide as it is high
        height=420,
        # the oval first: the bat is drawn over it
        series=[
            _outline("Upper Oval", ((-OVAL[0], OVAL[0], _oval),), YELLOW),
            _outline("Lower Oval", ((-OVAL[0], OVAL[0], lambda x: -_oval(x)),), YELLOW),
            _outline("Upper Edge", UPPER, BLACK),
            _outline("Lower Edge", LOWER, BLACK),
        ],
    )

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.chart.clicked.connect(self.show_click)

    def show_click(self, x: float, y: float) -> None:
        """Say whether the click was on the bat."""
        self.message.text = "I'm Batman" if is_in_bat(x, y) else "Click the bat"


def main() -> None:
    application.run(BatmanMainView, default_backend=RendererType.QT)


if __name__ == "__main__":
    main()

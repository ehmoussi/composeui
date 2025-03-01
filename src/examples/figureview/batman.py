from composeui import figure
from composeui.core.views.iview import IView
from composeui.figure.ifigureview import IFigureView

from matplotlib.axes import Axes

from dataclasses import dataclass, field
from math import sqrt
from typing import Callable, List, Tuple

_CURVES: List[Tuple[float, float, Callable[[float], float]]] = [
    (-7.0, -3.0, lambda x: 3.0 * sqrt(1 - (x / 7.0) ** 2)),
    (3.0, 7.0, lambda x: 3.0 * sqrt(1 - (x / 7.0) ** 2)),
    (-7.0, -4.0, lambda x: -3.0 * sqrt(1 - (x / 7.0) ** 2)),
    (4.0, 7.0, lambda x: -3.0 * sqrt(1 - (x / 7.0) ** 2)),
    (
        -4.0,
        4.0,
        lambda x: abs(x / 2.0)
        - (3.0 * sqrt(33) - 7) / 112 * x**2
        + sqrt(1 - (abs(abs(x) - 2) - 1) ** 2)
        - 3,
    ),
    (
        -3.0,
        -1.0,
        lambda x: 1.5 - 0.5 * abs(x) - 6 * sqrt(10) / 14 * (sqrt(3 - x**2 + 2 * abs(x)) - 2),
    ),
    (
        1.0,
        3.0,
        lambda x: 1.5 - 0.5 * abs(x) - 6 * sqrt(10) / 14 * (sqrt(3 - x**2 + 2 * abs(x)) - 2),
    ),
    (-1.0, -0.75, lambda x: 9 - 8 * abs(x)),
    (0.75, 1.0, lambda x: 9 - 8 * abs(x)),
    (-0.75, -0.5, lambda x: 3 * abs(x) + 0.75),
    (0.5, 0.75, lambda x: 3 * abs(x) + 0.75),
    (-0.5, 0.5, lambda _: 2.25),
]


@dataclass(eq=False)
class IBatmanView(IView):
    message: str = field(init=False, default="")
    figure: IFigureView = field(init=False)


def connect_batman(view: IBatmanView) -> None:
    view.figure.clicked = [display_message]


def display_message(*, parent_view: IBatmanView) -> None:
    x, y = parent_view.figure.x_last_clicked, parent_view.figure.y_last_clicked
    parent_view.message = ""
    if x is not None and y is not None:
        y_min = None
        y_max = None
        for x_min, x_max, f in _CURVES:
            if x_min <= x <= x_max:
                if f(x_min) <= 0 and f(x_max) <= 0:
                    y_min = f(x)
                elif f(x_min) >= 0 and f(x_max) >= 0:
                    y_max = f(x)
        if y_min is not None and y_max is not None and y_min <= y <= y_max:
            parent_view.message = "I'm Batman"


def initialize_batman(view: IBatmanView) -> None:
    axes = figure.initialize_figure_axes(view.figure)
    if axes is not None:
        axes.grid(False)
        nb_points = 1000
        axes.set_facecolor("black")
        _create_yellow_background(axes, nb_points)
        _create_batman_curve(axes, nb_points)


def _create_yellow_background(axes: Axes, nb_points: int) -> None:
    _create_curve(
        axes,
        -8.0,
        8.0,
        nb_points,
        lambda x: 4 / 8 * sqrt(8**2 - x**2),
        color="yellow",
        fill_color="yellow",
    )
    _create_curve(
        axes,
        -8.0,
        8.0,
        nb_points,
        lambda x: -4 / 8 * sqrt(8**2 - x**2),
        color="yellow",
        fill_color="yellow",
    )


def _create_batman_curve(axes: Axes, nb_points: int) -> None:
    for x_min, x_max, f in _CURVES:
        _create_curve(axes, x_min, x_max, nb_points, f)


def _create_curve(
    axes: Axes,
    x_min: float,
    x_max: float,
    nb_points: int,
    f: Callable[[float], float],
    color: str = "black",
    fill_color: str = "black",
    fill_alpha: float = 1.0,
) -> None:
    step = (x_max - x_min) / nb_points
    x = [x_min + i * step for i in range(nb_points)]
    if x[-1] != x_max:
        x.append(x_max)
    y = [f(x_i) for x_i in x]
    axes.plot(x, y, color=color)
    axes.fill_between(
        x,
        y,
        0,
        color=fill_color,
        facecolor=fill_color,
        alpha=fill_alpha,
    )

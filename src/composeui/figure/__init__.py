from composeui.figure.figureview import FigureView

import typing
from typing import Optional

if typing.TYPE_CHECKING:
    from matplotlib.axes import Axes


def initialize_figure_view(view: FigureView) -> bool:
    """Initialize the figure view."""
    from matplotlib.figure import Figure

    view.has_toolbar = False
    view.figure = Figure(figsize=(3.0, 10), tight_layout=True)
    view.x_last_clicked = None
    view.y_last_clicked = None
    view.last_clicked_axes = None
    return False


def initialize_figure_axes(view: FigureView) -> Optional["Axes"]:
    """Initialize the axes for a figure view."""
    if view.figure is not None:
        axes = view.figure.add_subplot(111)
        axes.grid()
        return axes
    return None


def initialize_figure_twin_axes(view: FigureView, axes: "Axes") -> None:
    """Initialize a twin axes for a figure view."""
    if view.figure is not None:
        axes_2 = axes.twinx()
        axes_2.set_label("")
        axes.set_zorder(axes_2.get_zorder() + 1)
        axes.set_frame_on(False)


def initialize_figure_3d_axes(view: FigureView) -> Optional["Axes"]:
    """Initialize a 3d axes for a figure view."""
    if view.figure is not None:
        return view.figure.add_subplot(111, projection="3d")
    return None

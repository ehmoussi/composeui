"""The series colors of the backends drawing charts without a palette of their own."""

#: categorical hues, in order, told apart with color blindness too, for a light and for a
#: dark background (each stepped for its background); past them, around again dashed
from __future__ import annotations

SERIES_COLORS = {
    False: ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"),
    True: ("#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"),
}


def series_color(index: int, *, is_dark: bool) -> str:
    """Get the color of the chart's series at `index`, as ``#rrggbb``."""
    colors = SERIES_COLORS[is_dark]
    return colors[index % len(colors)]


def is_dashed(index: int) -> bool:
    """Tell whether the series at `index` is dashed: the colors went around once already."""
    return index >= len(SERIES_COLORS[False])

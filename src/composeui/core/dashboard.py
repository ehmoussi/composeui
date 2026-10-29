"""Shorter dashboard code: a main view for a dashboard, and presets of ordinary views."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from composeui.core.view import ChartKind, ChartView, MainView, PageWidth, child, define_view

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = ["DashboardView", "bar_chart"]


@define_view
class DashboardView(MainView):
    """A main view for a dashboard: wide, without the File menu of studies.

    A subclass that saves studies sets ``has_file_menu = True`` and its `extension`.
    """

    width = PageWidth.WIDE
    has_file_menu = False


def bar_chart(
    title: str,
    categories: Iterable[str],
    *,
    x_title: str = "",
    y_title: str = "",
    height: Optional[int] = None,
) -> ChartView:
    """Get a view field's default: a bar chart with a group of bars per category.

    E.g. ``by_hour: ChartView = bar_chart("Pickups by hour", HOURS)``.
    """
    return child(
        ChartView,
        kind=ChartKind.BAR,
        title=title,
        categories=list(categories),
        x_title=x_title,
        y_title=y_title,
        height=height,
    )

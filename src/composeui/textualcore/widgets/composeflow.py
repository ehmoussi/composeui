"""A row of widgets that wraps onto the next line when the row is full."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from textual.geometry import Region
from textual.layouts.horizontal import HorizontalLayout
from textual.widget import Widget
from typing_extensions import override

if TYPE_CHECKING:
    from textual.geometry import Size
    from textual.layout import ArrangeResult, Layout, WidgetPlacement


class FlowLayout(HorizontalLayout):
    """A layout of widgets side by side, each as wide as its content, wrapping at the edge.

    Textual has none built in. The horizontal layout sizes each widget; this one then
    breaks its row into lines no wider than the container. With `align_end`, each line ends
    at the container's right edge.
    """

    name = "flow"

    def __init__(self, *, align_end: bool = False) -> None:
        super().__init__()
        self._align_end = align_end

    @override
    def arrange(
        self, parent: Widget, children: list[Widget], size: Size, greedy: bool = True
    ) -> ArrangeResult:
        lines: list[list[WidgetPlacement]] = []
        x = 0
        for placement in super().arrange(parent, children, size, greedy):
            width = _outer_width(placement)
            if not lines or (lines[-1] and x + width > size.width):
                lines.append([])
                x = 0
            lines[-1].append(placement)
            x += width
        placements: ArrangeResult = []
        y = 0
        for line in lines:
            x = size.width - sum(map(_outer_width, line)) if self._align_end else 0
            height = 0
            for placement in line:
                margin, region = placement.margin, placement.region
                moved = Region(x + margin.left, y + margin.top, region.width, region.height)
                placements.append(placement._replace(region=moved))
                x += _outer_width(placement)
                height = max(height, region.height + margin.top + margin.bottom)
            y += height
        return placements

    @override
    def get_content_width(self, widget: Widget, container: Size, viewport: Size) -> int:
        # as wide as its widgets on one line, as a row, up to the room it has: Textual's
        # own measure lays them out in no width, a widget a line
        one_line = super().arrange(widget, list(widget.displayed_children), container)
        width = max(
            (_outer_width(placement) + placement.region.x for placement in one_line), default=0
        )
        return min(width, container.width)


def _outer_width(placement: WidgetPlacement) -> int:
    return placement.region.width + placement.margin.left + placement.margin.right


class ComposeFlow(Widget):
    """A container laying its widgets out with a `FlowLayout`, as tall as its lines."""

    DEFAULT_CSS: ClassVar[str] = """
    ComposeFlow {
        width: 1fr;
        height: auto;
        overflow: hidden hidden;
    }
    """

    def __init__(self, *children: Widget, align_end: bool = False) -> None:
        super().__init__(*children)
        self._flow = FlowLayout(align_end=align_end)

    @property
    @override
    def layout(self) -> Layout:
        # Textual finds a layout set in the styles by name, among its own
        return self._flow

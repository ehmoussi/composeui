"""A `GridView`'s cells, checked as it's built, whatever renders it."""

from __future__ import annotations

from typing import Any, cast

import attrs
import pytest

from composeui.core.view import (
    GRID_POSITION,
    ButtonView,
    GridPosition,
    GridPositionError,
    GridView,
    define_view,
    grid_cell,
)


@define_view
class CellButtons(GridView):
    wide: ButtonView = grid_cell(GridPosition(1, 0, column_span=2), ButtonView, text="Wide")
    first: ButtonView = grid_cell((0, 0), ButtonView, text="First")


def test_grid_cell_puts_a_view_built_with_its_fields_in_the_cell() -> None:
    assert [(view.text, position) for view, position in _button_cells(CellButtons())] == [
        ("First", GridPosition(0, 0)),
        ("Wide", GridPosition(1, 0, column_span=2)),
    ]


def test_grid_cell_builds_a_view_for_each_grid() -> None:
    assert CellButtons().first is not CellButtons().first


def _button_cells(grid: GridView) -> list[tuple[ButtonView, GridPosition]]:
    return [(cast("ButtonView", view), position) for view, position in grid.positioned_views]


@pytest.mark.parametrize(
    ("metadata", "error"),
    [
        ({}, "GRID_POSITION"),
        ({GRID_POSITION: (0, -1)}, "row or column 0"),
        ({GRID_POSITION: GridPosition(1, 0, column_span=0)}, "span"),
        # covering the first button's cell from the row above
        ({GRID_POSITION: GridPosition(0, 1, row_span=2)}, r"cell \(1, 1\) is first's"),
    ],
)
def test_a_grid_view_refuses_a_view_field_without_a_cell_of_its_own(
    metadata: dict[str, Any], error: str
) -> None:
    @define_view
    class Buttons(GridView):
        first: ButtonView = attrs.field(factory=ButtonView, metadata={GRID_POSITION: (1, 1)})
        second: ButtonView = attrs.field(factory=ButtonView, metadata=metadata)

    with pytest.raises(GridPositionError, match=error):
        Buttons()

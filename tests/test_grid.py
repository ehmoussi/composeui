"""A `GridView`'s cells, checked as it's built, whatever renders it."""

from typing import Any

import attrs
import pytest

from composeui.core.view import (
    GRID_POSITION,
    ButtonView,
    GridPosition,
    GridPositionError,
    GridView,
    define_view,
)


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

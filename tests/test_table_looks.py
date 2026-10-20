"""How a table's cells and headers look, in core: what every backend shows."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from composeui.core.view import CellStyle, HeaderGroup, TableView
from tests.tables import StyledTablesMainView

if TYPE_CHECKING:
    from collections.abc import Callable


def test_a_cell_spans_only_the_rows_shown_right_under_it() -> None:
    table = TableView(headers=["Group", "Point"], sortable_columns=[1], filterable_columns=[1])
    table.rows = [["A", "P3"], ["", "P1"], ["", "P2"], ["B", "P4"]]
    table.cell_styles = {(0, 0): CellStyle(row_span=3), (3, 1): CellStyle(background="#ff0000")}
    assert table.shown_cell_styles() == {
        (0, 0): CellStyle(row_span=3),
        (3, 1): CellStyle(background="#ff0000"),
    }
    # P1 and P2 sort before P3: the rows the group covers no longer follow it
    table.sort_column = 1
    assert table.shown_rows == [1, 2, 0, 3]
    assert table.shown_cell_styles() == {
        (2, 0): CellStyle(row_span=1),
        (3, 1): CellStyle(background="#ff0000"),
    }
    # hiding P2 cuts the span short, P1 still right under the group
    table.sort_column = None
    table.filters = {1: "!P2"}
    assert table.shown_rows == [0, 1, 3]
    assert table.shown_cell_styles()[0, 0] == CellStyle(row_span=2)


def test_checking_every_row_leaves_a_disabled_cell_as_it_is() -> None:
    table = StyledTablesMainView().points
    # the disabled unchecked cell doesn't count: every other one is checked
    assert table.column_checked(4) is True
    table.check_all(4, is_checked=False)
    assert [row[4] for row in table.rows] == ["False", "False", "False"]
    table.check_all(4, is_checked=True)
    assert [row[4] for row in table.rows] == ["True", "False", "True"]
    assert table.is_cell_editable(0, 4)
    assert not table.is_cell_editable(1, 4)


def test_a_cell_s_text_is_black_or_white_whichever_reads_on_its_background() -> None:
    assert CellStyle(background="#fde68a").text_color == "#000000"
    assert CellStyle(background="#1e3a8a").text_color == "#ffffff"
    assert CellStyle().text_color is None


@pytest.mark.parametrize(
    ("build", "message"),
    [
        (lambda: CellStyle(background="red"), "give it as #rrggbb"),
        (lambda: CellStyle(row_span=0), "spans 1 at least"),
        (
            lambda: TableView(
                headers=["a", "b", "c"],
                header_groups=[HeaderGroup("A", 0, 2), HeaderGroup("B", 1, 2)],
            ),
            "a column is in two groups",
        ),
        (
            lambda: TableView(headers=["a"], header_groups=[HeaderGroup("A", 0, 0)]),
            "it covers no column",
        ),
    ],
)
def test_a_look_the_table_can_t_show_is_refused_saying_why(
    build: Callable[[], object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        build()

"""Test the pagination of the table."""

from examples.tableview.app import TableViewApp
from examples.tableview.points import IPointsView

import pytest


@pytest.fixture()
def table(app: TableViewApp) -> IPointsView:
    return app.main_view.points_view


def test_default(table: IPointsView) -> None:
    assert table.pagination_view.page_size_values == []
    assert table.pagination_view.row_summary == "0 to 0 of 0"
    assert table.pagination_view.is_first_enabled is False
    assert table.pagination_view.is_previous_enabled is False
    assert table.pagination_view.page_navigation_description == "Page 0 of 0"
    assert table.pagination_view.is_next_enabled is False
    assert table.pagination_view.is_last_enabled is False


def test_add_one_row(table: IPointsView) -> None:
    assert table.items is not None
    table.add_clicked()
    table.pagination_view.size_changed()
    table.pagination_view.current_page_changed()
    assert table.items.get_nb_rows() == 1
    assert table.pagination_view.page_size_values == [5]
    assert table.pagination_view.row_summary == "1 to 1 of 1"
    assert table.pagination_view.is_first_enabled is False
    assert table.pagination_view.is_previous_enabled is False
    assert table.pagination_view.page_navigation_description == "Page 1 of 1"
    assert table.pagination_view.is_next_enabled is False
    assert table.pagination_view.is_last_enabled is False


def test_add_six_rows(table: IPointsView) -> None:
    assert table.items is not None
    # add 6 rows
    for _ in range(6):
        table.add_clicked()
        table.pagination_view.size_changed()
        table.pagination_view.current_page_changed()
    # check
    assert table.items.get_nb_rows() == 6
    assert all(table.items.is_filtered(i) for i in range(5)) is True
    assert table.items.is_filtered(5) is False
    assert table.pagination_view.page_size_values == [5, 6]
    assert table.pagination_view.row_summary == "6 to 6 of 6"
    assert table.pagination_view.is_first_enabled is True
    assert table.pagination_view.is_previous_enabled is True
    assert table.pagination_view.page_navigation_description == "Page 2 of 2"
    assert table.pagination_view.is_next_enabled is False
    assert table.pagination_view.is_last_enabled is False


def test_update_page_size_after_adding_six_rows(table: IPointsView) -> None:
    assert table.items is not None
    # add 6 rows
    for _ in range(6):
        table.add_clicked()
        table.pagination_view.size_changed()
        table.pagination_view.current_page_changed()
    # change page size
    table.pagination_view.current_page_size_index = 1
    table.pagination_view.current_page_size_changed(1)  # --> update the table
    table.pagination_view.size_changed()  # emitted when the table is updated
    # check
    assert table.items.get_nb_rows() == 6
    assert all(table.items.is_filtered(i) for i in range(6)) is False
    assert table.pagination_view.page_size_values == [5, 6]
    assert table.pagination_view.row_summary == "1 to 6 of 6"
    assert table.pagination_view.is_first_enabled is False
    assert table.pagination_view.is_previous_enabled is False
    assert table.pagination_view.page_navigation_description == "Page 1 of 1"
    assert table.pagination_view.is_next_enabled is False
    assert table.pagination_view.is_last_enabled is False


def test_add_six_rows_and_remove_them_all(table: IPointsView) -> None:
    assert table.items is not None
    # add 6 rows
    for _ in range(6):
        table.add_clicked()
        table.pagination_view.size_changed()
        table.pagination_view.current_page_changed()
    # remove 6 rows
    for _ in range(6):
        table.remove_clicked()
        table.pagination_view.size_changed()
        table.pagination_view.current_page_changed()
    # check
    assert table.items.get_nb_rows() == 0
    assert table.pagination_view.page_size_values == []
    assert table.pagination_view.row_summary == "0 to 0 of 0"
    assert table.pagination_view.is_first_enabled is False
    assert table.pagination_view.is_previous_enabled is False
    assert table.pagination_view.page_navigation_description == "Page 0 of 0"
    assert table.pagination_view.is_next_enabled is False
    assert table.pagination_view.is_last_enabled is False

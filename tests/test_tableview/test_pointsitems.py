from examples.tableview.app import TableViewApp
from examples.tableview.points import PointsItems

import pytest


@pytest.fixture()
def items(app: TableViewApp) -> PointsItems:
    assert app.main_view.points_view.items is not None
    return app.main_view.points_view.items


def test_row_count(items: PointsItems) -> None:
    assert items.get_nb_rows() == 0
    items.insert(0)
    assert items.get_nb_rows() == 1


def test_column_count(items: PointsItems) -> None:
    assert items.get_nb_columns() == 4
    items._model.is_debug = True  # noqa: SLF001
    assert items.get_nb_columns() == 5


def test_data(items: PointsItems) -> None:
    items.insert(0)
    assert items.get_data(0, 0) == "point 1"
    assert items.get_data(0, 1) == "0.00"
    assert items.get_data(0, 2) == "0.00"
    assert items.get_data(0, 3) == "0.00"
    assert items.get_data(0, 4) == "1"
    assert items.get_edit_data(0, 0) == "point 1"
    assert items.get_edit_data(0, 1) == 0.0
    assert items.get_edit_data(0, 2) == 0.0
    assert items.get_edit_data(0, 3) == 0.0
    # set data
    items.set_data(0, 1, "1.0")
    items.set_data(0, 2, "2.0")
    items.set_data(0, 3, "3.0")
    assert items.get_data(0, 1) == "1.00"
    assert items.get_data(0, 2) == "2.00"
    assert items.get_data(0, 3) == "3.00"


def test_can_edit(items: PointsItems) -> None:
    for j in range(4):
        assert items.is_editable(0, j) is True
    assert items.is_editable(0, 4) is False


def test_convert_dataframe(items: PointsItems) -> None:
    for j in range(10):
        items.insert(j)
    points_df = items.converter().to_dataframe()
    assert points_df.shape == (10, 4)
    assert points_df["Name"].to_list() == [f"point {j}" for j in range(1, 11)]
    assert points_df["Name"].to_list() == [f"point {j}" for j in range(1, 11)]

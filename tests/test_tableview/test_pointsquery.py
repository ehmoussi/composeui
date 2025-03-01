from examples.tableview.app import Model
from examples.tableview.points import PointsQuery

import pytest


@pytest.fixture()
def query() -> PointsQuery:
    """Get the points query class with some points."""
    model = Model()
    model.points_query.insert(0)
    return model.points_query


def test_count(query: PointsQuery) -> None:
    assert query.count() == 1


def test_remove(query: PointsQuery) -> None:
    query.remove(0)
    assert query.count() == 0


def test_insert(query: PointsQuery) -> None:
    query.insert(0, "point 0")
    assert query.get_name(0) == "point 0"


def test_name(query: PointsQuery) -> None:
    query.set_name(0, "point 0")
    assert query.get_name(0) == "point 0"


def test_x(query: PointsQuery) -> None:
    assert query.get_x(0) == 0.0
    query.set_x(0, 1.0)
    assert query.get_x(0) == 1.0


def test_y(query: PointsQuery) -> None:
    assert query.get_y(0) == 0.0
    query.set_y(0, 2.0)
    assert query.get_y(0) == 2.0


def test_z(query: PointsQuery) -> None:
    assert query.get_z(0) == 0.0
    query.set_z(0, 3.0)
    assert query.get_z(0) == 3.0

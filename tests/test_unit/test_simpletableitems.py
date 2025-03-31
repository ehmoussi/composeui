"""Test the SimpleTableItems class without an order column."""

from pathlib import Path
from typing import Any
import pytest

from composeui.items.simpletable.simpletableitems import SimpleTableItems
from composeui.items.table.tableview import TableView
from composeui.model.sqlitemodel import SqliteModel


@pytest.fixture()
def items(tmpdir: Path) -> SimpleTableItems[Any]:
    sqlite_path = Path(tmpdir, "test.sqlite")
    model = SqliteModel("test", "0.1.0", False, sqlite_path)
    with model.sqlite_store.get_connection() as db_conn:
        db_conn.execute(
            """--sql
            CREATE TABLE test(
                name TEXT DEFAULT "",
                age INTEGER DEFAULT 30
            )
            """
        )
        db_conn.commit()
    return SimpleTableItems(TableView(), model, model.sqlite_store, "test")


def test_convert_row_id(items: SimpleTableItems[Any]) -> None:
    # no rows
    with pytest.raises(IndexError):
        items.get_id_from_row(0)
    with pytest.raises(IndexError):
        items.get_row_from_id(1)
    # insert a row
    items.insert(0)
    assert items.get_id_from_row(0) == 1
    assert items.get_row_from_id(1) == 0
    # insert another row
    # the index here has no importance because the table doesn't have order
    items.insert(0)
    assert items.get_id_from_row(0) == 1
    assert items.get_row_from_id(1) == 0
    assert items.get_id_from_row(1) == 2
    assert items.get_row_from_id(2) == 1
    # insert another row
    items.insert(0)
    assert items.get_id_from_row(0) == 1
    assert items.get_row_from_id(1) == 0
    assert items.get_id_from_row(1) == 2
    assert items.get_row_from_id(2) == 1
    assert items.get_id_from_row(2) == 3
    assert items.get_row_from_id(3) == 2
    # remove the second row
    items.remove(1)
    assert items.get_id_from_row(0) == 1
    assert items.get_row_from_id(1) == 0
    assert items.get_id_from_row(1) == 3
    assert items.get_row_from_id(3) == 1
    with pytest.raises(IndexError):
        assert items.get_row_from_id(2)

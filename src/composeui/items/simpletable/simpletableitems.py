from composeui.commontypes import AnyModel
from composeui.items.core.itemsutils import DelegateProps, FloatDelegateProps
from composeui.items.table.abstracttableitems import AbstractTableItems
from composeui.store.sqlitestore import SqliteStore

from typing_extensions import OrderedDict, Self, TypedDict

import itertools as it
import sqlite3
import typing
from typing import Any, Dict, List, Optional

if typing.TYPE_CHECKING:
    from composeui.items.table.itableview import ITableView


class _TableInfo(TypedDict):
    cid: str
    name: str
    type: str
    notnull: str
    dflt_value: str
    pk: str


class SimpleTableItems(AbstractTableItems[AnyModel]):
    def __init__(
        self,
        view: "ITableView[Self]",
        model: AnyModel,
        store: SqliteStore,
        table_name: str,
        columns: Optional[OrderedDict[str, str]] = None,
        order_column: Optional[str] = None,
        increment_columns: Optional[List[str]] = None,
        is_read_only: bool = True,
    ) -> None:
        super().__init__(view, model, title=table_name.capitalize())
        self._store = store
        self._increment_columns: List[str] = increment_columns or []
        self._is_read_only = is_read_only
        self._db_table_name: str = table_name
        self._db_table_infos = self._get_column_infos()
        self._column_names = list(self._db_table_infos)
        if order_column is not None and order_column not in self._column_names:
            msg = f"Order column is not a column of the table '{table_name}'"
            raise ValueError(msg)
        self._order_column = order_column
        if columns is not None:
            for column_name in columns:
                if column_name not in self._column_names:
                    msg = (
                        f"Column name '{column_name}' is not a column "
                        f"of the table '{table_name}'"
                    )
                    raise ValueError(msg)
            self._column_names = list(columns)
        self._column_titles = columns

    def get_column_names(self) -> List[str]:
        if self._model.is_debug:
            return [*self._column_names, "Id"]
        else:
            return self._column_names

    def get_nb_columns(self) -> int:
        if self._column_titles is not None:
            nb_columns = len(self._column_titles)
        else:
            nb_columns = len(self._column_names)
        if self._model.is_debug:
            nb_columns += 1
        return nb_columns

    def get_column_title(self, column: int) -> str:
        if self._column_titles is not None and column < len(self._column_titles):
            return next(it.islice(self._column_titles.values(), column, column + 1))
        elif column < len(self._column_names):
            return self._column_names[column].replace("_", " ").capitalize()
        elif self._model.is_debug:
            return "Id"
        else:
            msg = f"The table don't have {column + 1} columns"
            raise IndexError(msg)

    def get_nb_rows(self) -> int:
        with self._store.get_connection() as db_conn:
            result = db_conn.execute(
                f"SELECT COUNT(*) FROM {self._db_table_name}",
            ).fetchone()
            if result is not None:
                return int(result[0])
        return 0

    def insert(self, row: int) -> Optional[int]:
        with self._store.get_connection() as db_conn:
            if self._order_column is not None:
                # Update the order of all rows after the new row.
                db_conn.execute(
                    f"""
                    UPDATE {self._db_table_name}
                    SET {self._order_column}={self._order_column}+1
                    WHERE {self._order_column} >= :row
                    """,
                    {"row": row},
                )
            try:
                cursor = db_conn.execute(f"INSERT INTO {self._db_table_name} DEFAULT VALUES")
            except sqlite3.IntegrityError as e:
                if "NOT NULL constraint failed" in e.args[0]:
                    raise ValueError(
                        "Having default values for all the columns are mandatory "
                        "to use a SimpleTable"
                    ) from None
                else:
                    raise
            if self._order_column is not None and cursor.lastrowid is not None:
                # Update the order of all rows after the new row.
                db_conn.execute(
                    f"""
                    UPDATE {self._db_table_name}
                    SET {self._order_column}=:row
                    WHERE ROWID=:rowid
                    """,
                    {"rowid": cursor.lastrowid, "row": row},
                )
            elif cursor.lastrowid is None:
                db_conn.rollback()
                msg = f"The insert into {self._db_table_name} failed"
                raise ValueError(msg) from None
            for increment_column in self._increment_columns:
                db_conn.execute(
                    f"""
                    UPDATE {self._db_table_name}
                    SET {increment_column}=(
                        SELECT {increment_column}
                        FROM {self._db_table_name}
                        WHERE ROWID=:rowid
                    ) || ' ' || :rowid WHERE ROWID=:rowid
                    """,
                    {"rowid": cursor.lastrowid},
                )
            db_conn.commit()
        return row

    def remove(self, row: int) -> Optional[int]:
        with self._store.get_connection() as db_conn:
            if self._order_column is not None:
                db_conn.execute(
                    f"DELETE FROM {self._db_table_name} WHERE {self._order_column}=:row",
                    {"row": row},
                )
                # Update the order of all rows after the "about to be deleted" row
                db_conn.execute(
                    f"""
                    UPDATE {self._db_table_name}
                    SET {self._order_column}={self._order_column}-1
                    WHERE {self._order_column} > :row
                    """,
                    {"row": row},
                )
                db_conn.commit()
            else:
                result = db_conn.execute(
                    "SELECT ROWID FROM {self._db_table_name} LIMIT 1 OFFSET :offset",
                    {"offset": row},
                ).fetchone()
                if result is not None:
                    row_id = int(result[0])
                    db_conn.execute(
                        "DELETE FROM {self._db_table_name} WHERE ROWID=:row_id",
                        {"row_id": row_id},
                    )
                    db_conn.commit()
                else:
                    db_conn.rollback()
                    msg = f"No row with index {row} in table {self._db_table_name}"
                    raise IndexError(msg)
        return super().remove(row)

    def get_data(self, row: int, column: int) -> str:
        value = self.get_edit_data(row, column)
        if value is not None and (
            (self._model.is_debug and column < (self.get_nb_columns() - 1))
            or (not self._model.is_debug and column < self.get_nb_columns())
        ):
            column_type = self._db_table_infos[self._column_names[column]]["type"]
            if column_type == "REAL":
                return self.display_float(value, 2)
        if value is not None:
            return str(value)
        return super().get_data(row, column)

    def get_edit_data(self, row: int, column: int) -> Any:
        if self._model.is_debug and column == self.get_nb_columns() - 1:
            column_name = "ROWID"
            column_type = "INTEGER"
            default_value = None
        else:
            column_name = self._column_names[column]
            column_type = self._db_table_infos[column_name]["type"]
            default_value = self._db_table_infos[column_name]["dflt_value"]
        if self._order_column is not None:
            order_column = self._order_column
        else:
            order_column = "ROWID"
        statement = f"""
                SELECT {column_name}
                FROM {self._db_table_name}
                ORDER BY {order_column} LIMIT 1 OFFSET :offset
                """
        with self._store.get_connection() as db_conn:
            result = db_conn.execute(statement, {"offset": row}).fetchone()
        if result is not None:
            value = result[0]
            if column_type == "INTEGER":
                value = self.to_int_value(value, default=self.to_int_value(default_value))
                if value is None:
                    return ""
            elif column_type == "REAL":
                value = self.to_float_value(value, default=self.to_float_value(default_value))
                if value is None:
                    return ""
            elif column_type != "TEXT":
                # msg = f"Unknown column type {column_type}"
                # raise ValueError(msg)
                value = str(value)
            return value
        return None

    def move(self, from_row: int, to_row: int) -> bool:
        if self._order_column is not None:
            with self._store.get_connection() as db_conn:
                # put the item at the beginning of the table
                db_conn.execute(
                    f"""
                    UPDATE  {self._db_table_name}
                    SET {self._order_column} = -1000
                    WHERE {self._order_column}=:row
                    """,
                    {"row": from_row},
                )
                # decrement all items with row > from_row
                db_conn.execute(
                    f"""
                    UPDATE  {self._db_table_name}
                    SET {self._order_column} = {self._order_column} - 1
                    WHERE {self._order_column}>:row
                    """,
                    {"row": from_row},
                )
                # increment all items with row >= to_row to let the insertion of the moved item
                db_conn.execute(
                    f"""
                    UPDATE  {self._db_table_name}
                    SET {self._order_column} = {self._order_column} + 1
                    WHERE {self._order_column}>=:row
                    """,
                    {"row": to_row},
                )
                # Change the row of the item move to the 'to_row'
                db_conn.execute(
                    f"""
                    UPDATE  {self._db_table_name}
                    SET {self._order_column} = :row
                    WHERE {self._order_column}= -1000
                    """,
                    {"row": to_row},
                )
                db_conn.commit()
            return True
        return super().move(from_row, to_row)

    def set_data(self, row: int, column: int, value: str) -> bool:
        column_name = self._column_names[column]
        column_type = self._db_table_infos[column_name]["type"]
        default_value = self._db_table_infos[column_name]["dflt_value"]
        if column_type == "INTEGER":
            if (
                self.to_int_value(
                    value,
                    default=self.to_int_value(default_value),
                )
                is None
            ):
                return False
        elif column_type == "REAL":
            if (
                self.to_float_value(
                    value,
                    default=self.to_float_value(default_value),
                )
                is None
            ):
                return False
        elif column_type == "TEXT":
            value = str(value)
        else:
            # msg = f"Unknown column type {column_type}"
            # raise ValueError(msg)
            value = str(value)
        if self._order_column is not None:
            order_column = self._order_column
        else:
            order_column = "ROWID"
        statement = f"""
            UPDATE {self._db_table_name}
            SET {column_name} = :value
            WHERE {order_column}=:row
            """
        with self._store.get_connection() as db_conn:
            db_conn.execute(
                statement,
                {
                    "value": value,
                    "order_column": order_column,
                    "row": row,
                },
            )
            db_conn.commit()
        return True

    def is_editable(self, row: int, column: int) -> bool:
        if self._model.is_debug and column == len(self._column_names):
            return False
        return not self._is_read_only

    def get_delegate_props(self, row: int, column: int) -> Optional[DelegateProps]:
        r"""Get the delegate type for the given column."""
        if column < len(self._column_names):
            column_type = self._db_table_infos[self._column_names[column]]["type"]
            if column_type == "REAL":
                return FloatDelegateProps()
        return super().get_delegate_props(row, column)

    def _get_column_infos(self) -> Dict[str, _TableInfo]:
        with self._store.get_connection() as db_conn:
            result = db_conn.execute(
                f"PRAGMA table_info({self._db_table_name})",
            ).fetchall()
        return {
            row["name"]: _TableInfo(
                cid=str(row["cid"]),
                name=str(row["name"]),
                type=str(row["type"]),
                notnull=str(row["notnull"]),
                dflt_value=str(row["dflt_value"]),
                pk=str(row["pk"]),
            )
            for row in result
        }

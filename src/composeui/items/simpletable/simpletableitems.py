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
    from composeui.items.table.tableview import TableView


class _TableInfo(TypedDict):
    cid: str
    name: str
    type: str
    notnull: str
    dflt_value: str
    pk: str


class SimpleTableItems(AbstractTableItems[AnyModel]):
    """Implement an AbstractTableItems for an sqlite table.

    - By default all the columns are displayed, otherwise provide the `columns` argument
    - By default the order used is by sorting by the column ROWID, otherwise provide
        the `order_column` argument
    - By default when an insert is done the default values are used. If there is columns that
        need to have there default values incremented they can be provided by
        the `increment_columns` argument. For example a default name `point` can be incremented
        automatically like `point 1`, `point 2`, ... at each insertion
    - By default the table can't be modified, to activate the insertion/removing/modification
        the argument `is_read_only` can be set to false.
    """

    def __init__(
        self,
        view: "TableView[Self]",
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
        self._cached_data = self.get_all_datas()

    def get_cached_data(self) -> Optional[List[List[str]]]:
        return self._cached_data

    def update_cache(self) -> None:
        self._cached_data = self.get_all_datas()

    def get_id_from_row(self, row: int) -> Any:
        if self._order_column is None:
            with self._store.get_connection() as db_conn:
                result = db_conn.execute(
                    f"""--sql
                    SELECT ROWID
                    FROM {self._db_table_name}
                    ORDER BY ROWID LIMIT 1 OFFSET :row
                    """,
                    {"row": row},
                ).fetchone()
            if result is not None:
                return int(result[0])
        else:
            with self._store.get_connection() as db_conn:
                result = db_conn.execute(
                    f"""--sql
                    SELECT ROWID
                    FROM {self._db_table_name}
                    WHERE {self._order_column} = :row
                    """,
                    {"row": row},
                ).fetchone()
            if result is not None:
                return int(result[0])
        raise IndexError("index out of range")

    def get_row_from_id(self, rid: Any) -> int:
        if self._order_column is None:
            with self._store.get_connection() as db_conn:
                result = db_conn.execute(
                    f"""--sql
                    SELECT
                        CASE
                            -- Check if the rowid exists
                            WHEN EXISTS(
                                SELECT 1 FROM {self._db_table_name}
                                WHERE ROWID = :row_id
                            )
                            THEN(
                                -- if the rowid exists the count the number of rows that
                                -- have a rowid less than the given rowid since the ROWID
                                -- column is used to order the column
                                SELECT COUNT(*)
                                FROM {self._db_table_name}
                                WHERE ROWID < :row_id
                            )
                        ELSE
                            -- if the rowid is missing then return NULL to raise an IndexError 
                            NULL
                        END
                    """,
                    {"row_id": rid},
                ).fetchone()
            if result is not None and result[0] is not None:
                return int(result[0])
        else:
            with self._store.get_connection() as db_conn:
                result = db_conn.execute(
                    f"""--sql
                    SELECT {self._order_column}
                    FROM {self._db_table_name}
                    WHERE ROWID=:row_id
                    """,
                    {"row_id": rid},
                ).fetchone()
            if result is not None:
                return int(result[0])
        raise IndexError("index out of range")

    def get_column_names(self) -> List[str]:
        """Get the names of the column and add the ROWID column in debug mode."""
        if self._model.is_debug:
            return [*self._column_names, "Id"]
        else:
            return self._column_names

    def get_nb_columns(self) -> int:
        """Get the number of columns of the table."""
        if self._column_titles is not None:
            nb_columns = len(self._column_titles)
        else:
            nb_columns = len(self._column_names)
        if self._model.is_debug:
            nb_columns += 1
        return nb_columns

    def get_column_title(self, column: int) -> str:
        """Get the title of the column that is used to display in the UI."""
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
        """Get the number of rows of the table."""
        with self._store.get_connection() as db_conn:
            result = db_conn.execute(
                f"SELECT COUNT(*) FROM {self._db_table_name}",
            ).fetchone()
            if result is not None:
                return int(result[0])
        return 0

    def insert(self, row: int) -> Optional[int]:
        """Insert a row in the table and returns eventually the next selected row.

        The sql table should have default values for all the columns otherwise the insertion
        will fail.

        If `order_column` has been provided then the rows after the given row will
        be incremented to keep the order of the table.
        """
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
                msg = f"The insert into {self._db_table_name} failed unexpectedly"
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
        self.update_cache()
        return row

    def _remove_by_id(self, rid: Any) -> None:
        """Remove the row with the give id."""
        with self._store.get_connection() as db_conn:
            row = None
            if self._order_column is not None:
                row = self.get_row_from_id(rid)
            db_conn.execute(
                f"DELETE FROM {self._db_table_name} WHERE ROWID=:row_id",
                {"row_id": rid},
            )
            if self._order_column is not None and row is not None:
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
        self.update_cache()

    def get_data_by_id(self, rid: Any, column: int) -> str:
        """Get the data to be displayed by the UI at the given row id and column."""
        value = self.get_edit_data_by_id(rid, column)
        return self._get_display_value(value, column)

    def get_all_datas(self) -> List[List[str]]:
        """Get all the data of the table."""
        with self._store.get_connection() as db_conn:
            columns = self.get_column_names()
            order_column = "ROWID"
            if self._order_column is not None:
                order_column = self._order_column
            result = db_conn.execute(
                f"""--sql
                SELECT {','.join(columns)}, ROWID
                FROM {self._db_table_name}
                ORDER BY {order_column}
                """
            ).fetchall()
        return [
            [self._get_display_value(row[column], column) for row in result]
            for column, _ in enumerate(columns)
        ]

    def _get_display_value(self, value: Any, column: int) -> str:
        """Get the value displayed as a string."""
        if value is not None and (
            (self._model.is_debug and column < (self.get_nb_columns() - 1))
            or (not self._model.is_debug and column < self.get_nb_columns())
        ):
            column_type = self._db_table_infos[self._column_names[column]]["type"]
            if column_type == "REAL":
                return self.display_float(value, 2)
        if value is not None:
            return str(value)
        return ""

    def get_edit_data_by_id(self, rid: Any, column: int) -> Any:
        """Get the data as stored in the sqlite table for the given row id and column."""
        if self._model.is_debug and column == self.get_nb_columns() - 1:
            column_name = "ROWID"
            column_type = "INTEGER"
            default_value = None
        else:
            column_name = self._column_names[column]
            column_type = self._db_table_infos[column_name]["type"]
            default_value = self._db_table_infos[column_name]["dflt_value"]
        statement = f"""
                SELECT {column_name}
                FROM {self._db_table_name}
                WHERE ROWID=:rid
                """
        with self._store.get_connection() as db_conn:
            result = db_conn.execute(statement, {"rid": rid}).fetchone()
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
        """Move the id from the given from_row to the given to_row.

        It returns True if the move is a success.

        If the `order_column` is provided then the column is updated to respect the new order
        after the move.
        Otherwise the move doesn't have any meaning so the function does nothing and returns
        False.
        """
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
            self.update_cache()
            return True
        return super().move(from_row, to_row)

    def set_data_by_id(self, rid: Any, column: int, value: str) -> bool:
        """Set the given value at the given row id and column.

        The value is casted as an int or a float according to the type of the sqlite table.
        If the given value can't be casted to the correct type the value is not set and the
        function returns False.

        """
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
            WHERE ROWID=:row_id
            """
        with self._store.get_connection() as db_conn:
            db_conn.execute(
                statement,
                {
                    "value": value,
                    "order_column": order_column,
                    "row_id": rid,
                },
            )
            db_conn.commit()
        self._cached_data[column][self.get_row_from_id(rid)] = value
        return True

    def is_editable(self, row: int, column: int) -> bool:
        return self._is_editable(column)

    def is_editable_by_id(self, rid: Any, column: int) -> bool:
        return self._is_editable(column)

    def _is_editable(self, column: int) -> bool:
        """Check if the column is editable.

        The id column is not editable.
        The other columns are only editable only if the `is_read_only` is set to False.
        """
        if self._model.is_debug and column == len(self._column_names):
            return False
        return not self._is_read_only

    def get_delegate_props(
        self, column: int, *, row: Optional[int] = None
    ) -> Optional[DelegateProps]:
        """Get the delegate type for the given column.

        If the column of the sqlite table is of type REAL then the FloatDelegateProps is used.
        """
        if column < len(self._column_names):
            column_type = self._db_table_infos[self._column_names[column]]["type"]
            if column_type == "REAL":
                return FloatDelegateProps()
        return super().get_delegate_props(column, row=row)

    def _get_column_infos(self) -> Dict[str, _TableInfo]:
        """Extract column informations from the sqlite table needed to implement the items."""
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

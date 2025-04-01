from composeui.store.djangoormstore import DjangoORMStore

from typing import Any, List, Tuple


class VariablesQuery:
    def __init__(self, store: DjangoORMStore) -> None:
        self._store = store

    def get_row_index(self, v_id: int) -> int:
        """Get the index of the row for the given v_id.

        The table is ordered using the id column.
        """
        with self._store.get_connection() as db_conn:
            result = db_conn.execute(
                """--sql
                SELECT
                    CASE
                        -- Check if the rowid exists
                        WHEN EXISTS(
                            SELECT 1 FROM variables_variable
                            WHERE v_id = :v_id
                        )
                        THEN(
                            -- if the rowid exists count the number of rows that
                            -- have a v_id less than the given v_id
                            SELECT COUNT(*)
                            FROM variables_variable
                            WHERE v_id < :v_id
                        )
                    ELSE
                        -- if the rowid is missing then return NULL to raise an IndexError
                        NULL
                    END
                """,
                {"v_id": v_id},
            ).fetchone()
            if result is not None and result[0] is not None:
                return int(result[0])
            raise IndexError("index out of range")

    def get_v_id(self, index: int) -> int:
        """Get the v_id from the given index.

        Get the v_id of the row at the given index when the table is ordered with v_id column.
        """
        with self._store.get_connection() as db_conn:
            result = db_conn.execute(
                """--sql
                SELECT v_id
                FROM variables_variable
                ORDER BY v_id LIMIT 1 OFFSET :row_index
                """,
                {"row_index": index},
            ).fetchone()
        if result is not None:
            return int(result[0])
        raise IndexError("index out of range")

    def count(self) -> int:
        with self._store.get_connection() as db_conn:
            result = db_conn.execute("SELECT COUNT(*) FROM variables_variable").fetchone()
        if result is not None:
            return int(result[0])
        return 0

    def add(self, name: str, distribution: str) -> None:
        with self._store.get_connection() as db_conn:
            db_conn.execute(
                """--sql
                INSERT INTO variables_variable(name, distribution)
                VALUES(:name, :distribution)
                """,
                {"name": name, "distribution": distribution},
            )

    def remove(self, v_id: int) -> None:
        with self._store.get_connection() as db_conn:
            db_conn.execute(
                """--sql
                DELETE FROM variables_variable
                WHERE v_id = :v_id
                """,
                {"v_id": v_id},
            )

    def get_name(self, v_id: int) -> str:
        return str(self._get_value("name", v_id))

    def set_name(self, v_id: int, name: str) -> None:
        self._set_value("name", v_id, name)

    def get_distribution(self, v_id: int) -> str:
        return str(self._get_value("distribution", v_id))

    def set_distribution(self, v_id: int, distribution: str) -> None:
        self._set_value("distribution", v_id, distribution)

    def get_id(self, v_id: int) -> int:
        return int(self._get_value("v_id", v_id))

    def get_row_data_by_id(self, v_id: int) -> Tuple[str, str, int]:
        with self._store.get_connection() as db_conn:
            result = db_conn.execute(
                """--sql
                SELECT name, distribution, v_id
                FROM variables_variable
                WHERE v_id = :v_id
                """,
                {"v_id": v_id},
            ).fetchone()
        if result is not None:
            return (str(result[0]), str(result[1]), int(result[2]))
        else:
            raise IndexError("index out of range")

    def get_data(self) -> List[Tuple[str, str, int]]:
        with self._store.get_connection() as db_conn:
            result = db_conn.execute(
                """--sql
                SELECT name, distribution, v_id
                FROM variables_variable
                """
            ).fetchall()
        return [(str(row[0]), str(row[1]), int(row[2])) for row in result]

    def _set_value(self, column_name: str, v_id: int, value: Any) -> None:
        with self._store.get_connection() as db_conn:
            db_conn.execute(
                f"""--sql
                UPDATE variables_variable
                SET {column_name} = :value
                WHERE v_id = :v_id
                """,
                {"v_id": v_id, "value": value},
            )

    def _get_value(self, column_name: str, v_id: int) -> Any:
        with self._store.get_connection() as db_conn:
            result = db_conn.execute(
                f"""--sql
                SELECT {column_name}
                FROM variables_variable
                WHERE v_id = :v_id
                """,
                {"v_id": v_id},
            ).fetchone()
        if result is not None:
            return result[0]
        else:
            raise IndexError("index out of range")

from composeui.store.djangoormstore import DjangoORMStore

from typing import Any, List, Tuple


class VariablesQuery:
    def __init__(self, store: DjangoORMStore) -> None:
        self._store = store

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

    def remove(self, row: int) -> None:
        with self._store.get_connection() as db_conn:
            db_conn.execute(
                """--sql
                DELETE FROM variables_variable
                WHERE v_id=(
                    SELECT v_id FROM variables_variable LIMIT 1 OFFSET :row
                )
                """,
                {"row": row},
            )

    def get_name(self, row: int) -> str:
        return str(self._get_value("name", row))

    def set_name(self, row: int, name: str) -> None:
        self._set_value("name", row, name)

    def get_distribution(self, row: int) -> str:
        return str(self._get_value("distribution", row))

    def set_distribution(self, row: int, distribution: str) -> None:
        self._set_value("distribution", row, distribution)

    def get_id(self, row: int) -> int:
        return int(self._get_value("v_id", row))

    def get_row(self, row: int) -> Tuple[str, str, int]:
        with self._store.get_connection() as db_conn:
            result = db_conn.execute(
                """--sql
                SELECT name, distribution, v_id
                FROM variables_variable
                WHERE v_id=(
                    SELECT v_id FROM variables_variable LIMIT 1 OFFSET :row
                )
                """,
                {"row": row},
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

    def _set_value(self, column_name: str, row: int, value: Any) -> None:
        with self._store.get_connection() as db_conn:
            db_conn.execute(
                f"""--sql
                UPDATE variables_variable
                SET {column_name} = :value
                WHERE v_id=(
                    SELECT v_id FROM variables_variable LIMIT 1 OFFSET :row
                )
                """,
                {"row": row, "value": value},
            )

    def _get_value(self, column_name: str, row: int) -> Any:
        with self._store.get_connection() as db_conn:
            result = db_conn.execute(
                f"""--sql
                SELECT {column_name}
                FROM variables_variable
                WHERE v_id=(
                    SELECT v_id FROM variables_variable LIMIT 1 OFFSET :row
                )
                """,
                {"row": row},
            ).fetchone()
        if result is not None:
            return result[0]
        else:
            raise IndexError("index out of range")

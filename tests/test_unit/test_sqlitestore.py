"""Test the pool of sqlite connection of the SqliteStore whit multiple threads."""

from composeui.store.sqlitestore import SqliteStore

import concurrent
import concurrent.futures
import time
from pathlib import Path


def test_read_multiple_threads() -> None:
    store = SqliteStore()
    store.add_tables([Path("src/examples/tableview/db/points.sql")])
    store.create_tables()
    nb_points = 10
    with store.get_connection() as db_conn:
        db_conn.executemany(
            """--sql
            INSERT INTO points(p_name, p_index)
            VALUES(:p_name, :p_index)
            """,
            [{"p_name": f"point {i}", "p_index": i} for i in range(nb_points)],
        )
        db_conn.commit()

    def read_point_name(index: int) -> str:
        with store.get_connection() as db_conn:
            db_conn.create_function("sleep", 1, time.sleep)
            # use sleep to highlight the usefulness of a connection pool
            # using this with one connection will freeze
            result = db_conn.execute(
                """--sql
                SELECT p_name, sleep(1)
                FROM points
                WHERE p_index=:p_index
                """,
                {"p_index": index},
            ).fetchone()
            if result is not None:
                return str(result["p_name"])
            raise IndexError("index out of range")

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as thread_pool:
        results = list(thread_pool.map(read_point_name, range(nb_points)))
        assert results == [f"point {i}" for i in range(nb_points)]

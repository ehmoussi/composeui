"""Data managing state using sqlite."""

from composeui.store.abstractstore import AbstractStore

import contextlib
import itertools as it
import queue
import sqlite3
import sys
import tempfile
import warnings
from pathlib import Path
from typing import Generator, List, Optional, Sequence, Tuple


class SqliteStore(AbstractStore):
    """Managing state using sqlite3 python db api interface."""

    def __init__(self, filepath: Optional[Path] = None, capacity: int = 20) -> None:
        self._capacity = capacity
        self._is_debug = False
        self._pool: queue.Queue[sqlite3.Connection] = queue.Queue(capacity)
        self._sql_table_files: List[Path] = []
        self._sql_trigger_files: List[Path] = []
        self._filepath: Optional[Path] = None
        if filepath is not None:
            self._filepath = Path(filepath).resolve()
        self._tmp_sqlite_filepath: Optional[Path] = None
        self.history = SqliteHistory(self)
        self.new_study()

    @contextlib.contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        if self._pool.empty():
            self._pool.put(self.create_connection())
        db_conn = self._pool.get()
        try:
            yield db_conn
        finally:
            self._pool.put(db_conn)

    def get_extension(self) -> str:
        return ".sqlite"

    def set_debug_mode(self, is_debug: bool) -> None:
        """Set the status of the debug mode."""
        self._is_debug = is_debug
        # TODO: Add the log of the sqlite commands

    def clear_study(self) -> None:
        r"""Clear all the datas."""
        self.close_pool()

    def new_study(self) -> None:
        self.create_pool()
        self.create_tables()

    def save_study(self, filepath: Path) -> None:
        """Save the current study using the specific format."""
        r"""Save the database to the given filepath."""
        with contextlib.closing(
            sqlite3.connect(str(filepath), check_same_thread=False)
        ) as filepath_con:
            self.commit_pool()  # ensure all the transactions are commited before backup
            with self.get_connection() as db_conn:
                if sys.version_info >= (3, 7, 0):  # noqa: UP036
                    db_conn.backup(filepath_con)
                else:
                    filepath_con.executescript("".join(db_conn.iterdump()))
                    filepath_con.commit()

    def open_study(self, filepath: Path) -> None:
        r"""Read the database from the given filepath."""
        if sys.version_info < (3, 7, 0):  # noqa: UP036
            with contextlib.closing(sqlite3.connect(str(filepath))) as filepath_con:
                sql_dump = "".join(filepath_con.iterdump())
            self.create_pool()
            with self.get_connection() as db_conn:
                db_conn.executescript(sql_dump)
                db_conn.commit()
        else:
            with contextlib.closing(sqlite3.connect(str(filepath))) as filepath_con:
                self.create_pool()
                with self.get_connection() as db_conn:
                    filepath_con.backup(db_conn)
        try:
            self.create_tables()
        except Exception as e:  # noqa: BLE001
            warnings.warn(
                (
                    f"Failed to execute the sql files because of '{e.args[0]}'. "
                    "Hint: The definition of tables and triggers "
                    "should always have 'IF NOT EXISTS'."
                ),
                stacklevel=2,
            )

    def create_pool(self) -> None:
        self.close_pool()
        # don't need to create a temporary file if the filepath is available
        if self._filepath is None:
            with tempfile.NamedTemporaryFile(
                prefix="sqlite_store_", suffix=".sqlite", delete=False
            ) as tmp_sqlite_file:
                ...
            self._tmp_sqlite_filepath = Path(tmp_sqlite_file.name).resolve()
        self._pool.put(self.create_connection())

    def close_pool(self) -> None:
        while not self._pool.empty():
            db_conn = self._pool.get()
            db_conn.close()
        # remove the current temporary file
        if self._tmp_sqlite_filepath is not None and self._tmp_sqlite_filepath.exists():
            self._tmp_sqlite_filepath.unlink()

    def commit_pool(self) -> None:
        """Commit all the connections currently in the pool."""
        tmp_pool: queue.Queue[sqlite3.Connection] = queue.Queue(self._capacity)
        while not self._pool.empty():
            db_conn = self._pool.get()
            db_conn.commit()
            tmp_pool.put(db_conn)
        while not tmp_pool.empty():
            db_conn = tmp_pool.get()
            self._pool.put(db_conn)

    def add_tables(self, sql_files: Sequence[Path]) -> None:
        """Add the given files to the definition of the tables of the current study."""
        self._sql_table_files.extend(sql_files)

    def add_triggers(self, sql_files: Sequence[Path]) -> None:
        """Add the given files to the definition of the triggers of the current study."""
        self._sql_trigger_files.extend(sql_files)

    def create_tables(self) -> None:
        """Create the tables and the triggers."""
        self.execute_sql_files(self._sql_table_files)
        self.execute_sql_files(self._sql_trigger_files)
        self.history.install_history()

    def create_only_tables(self) -> None:
        """Create only the tables without the triggers"""
        self.execute_sql_files(self._sql_table_files)

    def create_triggers(self) -> None:
        """Create only the triggers."""
        self.execute_sql_files(self._sql_trigger_files)

    def create_connection(self) -> sqlite3.Connection:
        print(self._filepath)
        if self._filepath is not None:
            db_conn = sqlite3.connect(str(self._filepath), check_same_thread=False)
            print("ok")
        else:
            db_conn = sqlite3.connect(str(self._tmp_sqlite_filepath), check_same_thread=False)
        db_conn.row_factory = sqlite3.Row
        current_dir = Path(__file__).parent
        db_conn.executescript(Path(current_dir, "settings.sql").read_text())
        db_conn.commit()
        return db_conn

    def execute_sql_files(self, sql_files: Sequence[Path]) -> None:
        with self.get_connection() as db_conn:
            for filepath in sql_files:
                db_conn.executescript(filepath.read_text())
            db_conn.commit()

    def undo(self) -> None:
        self.history.undo()

    def redo(self) -> None:
        self.history.redo()

    def activate_history(self) -> None:
        """Activate the history."""
        self.history.activate()

    def deactivate_history(self) -> None:
        """Deactivate the history."""
        self.history.deactivate()


class SqliteHistory:
    def __init__(self, store: SqliteStore) -> None:
        self._store = store

    def install_history(self) -> None:
        self._create_tables()
        # self._add_all_triggers("undo")

    def undo(self) -> None:
        """Undo the last index of the history."""
        self._add_all_triggers("redo")
        current_idx = self._get_current_idx()
        try:
            with self._store.get_connection() as db_conn:
                commands = self._get_commands(current_idx, "undo", db_conn)
                if len(commands) > 0:
                    # decrement the index of the history
                    self._decrement_current_idx(db_conn)
                for c_id, cmd in commands:
                    # apply the command
                    db_conn.execute(cmd)
                    # remove the command from the undo log
                    db_conn.execute(
                        """--sql
                        DELETE FROM _CUI_UNDO_LOG WHERE c_id=:c_id
                        """,
                        {"c_id": c_id},
                    )
                db_conn.commit()
        finally:
            self._drop_all_triggers("redo")

    def redo(self) -> None:
        """Redo the last index of the history."""
        self._add_all_triggers("undo")
        current_idx = self._get_current_idx()
        try:
            with self._store.get_connection() as db_conn:
                commands = self._get_commands(current_idx, "redo", db_conn)
                if len(commands) > 0:
                    self._increment_current_idx(db_conn)
                for c_id, cmd in commands:
                    # apply the command
                    db_conn.execute(cmd)
                    # remove the command from the undo log
                    db_conn.execute(
                        """--sql
                        DELETE FROM _CUI_REDO_LOG WHERE c_id=:c_id
                        """,
                        {"c_id": c_id},
                    )
                db_conn.commit()
        finally:
            self._drop_all_triggers("undo")

    def activate(self) -> None:
        """Activate the history."""
        self._add_all_triggers("undo")
        with self._store.get_connection() as db_conn:
            self._increment_current_idx(db_conn)
            db_conn.commit()

    def deactivate(self) -> None:
        self._drop_all_triggers("undo")
        with self._store.get_connection() as db_conn:
            db_conn.execute(
                """--sql
                DELETE FROM _CUI_REDO_LOG
                """
            )
            db_conn.commit()

    def _increment_current_idx(self, db_conn: sqlite3.Connection) -> None:
        db_conn.execute(
            """--sql
            UPDATE _CUI_INDEX
            SET current_idx = current_idx + 1
            WHERE h_id=1
            """
        )

    def _decrement_current_idx(self, db_conn: sqlite3.Connection) -> None:
        db_conn.execute(
            """--sql
            UPDATE _CUI_INDEX
            SET current_idx = current_idx - 1
            WHERE h_id=1
            """
        )

    def _get_current_idx(self) -> int:
        with self._store.get_connection() as db_conn:
            result = db_conn.execute(
                """--sql
                SELECT current_idx
                FROM _CUI_INDEX
                WHERE h_id=1
                """
            ).fetchone()
        if result is not None:
            return int(result[0])
        raise ValueError("Unexpected error: can't find the current index of the history")

    def _get_commands(
        self, current_idx: int, log_name: str, db_conn: sqlite3.Connection
    ) -> List[Tuple[int, str]]:
        """Get the commands of the last index of the history."""
        result = db_conn.execute(
            f"""--sql
            SELECT c_id, cmd FROM _CUI_{log_name.upper()}_LOG
            WHERE idx = :current_idx
            ORDER BY ord
            """,
            {"current_idx": current_idx},
        ).fetchall()
        return [(int(row[0]), str(row[1])) for row in result]

    def _create_tables(self) -> None:
        with self._store.get_connection() as db_conn:
            db_conn.execute(
                "CREATE TABLE IF NOT EXISTS _CUI_INDEX(h_id PRIMARY KEY, current_idx)"
            )
            db_conn.execute("INSERT OR IGNORE INTO _CUI_INDEX VALUES(1, 0)")
            db_conn.execute(
                """--sql
                CREATE TABLE IF NOT EXISTS _CUI_UNDO_LOG(
                    c_id INTEGER PRIMARY KEY NOT NULL,
                    idx INTEGER, -- index of an action
                    ord INTEGER, -- order of the action for a given index
                    cmd TEXT
                )
                """
            )
            db_conn.execute(
                """--sql
                CREATE TABLE IF NOT EXISTS _CUI_REDO_LOG(
                    c_id INTEGER PRIMARY KEY NOT NULL,
                    idx INTEGER,
                    ord INTEGER,
                    cmd TEXT
                )
                """
            )
            db_conn.commit()

    def _add_all_triggers(self, log_name: str) -> None:
        for table in self._get_all_tables():
            if not table.startswith("_CUI_"):  # ignore the internal tables of the undo/redo
                self._add_triggers(table, log_name)

    def _drop_all_triggers(self, log_name: str) -> None:
        for table in self._get_all_tables():
            if not table.startswith("_CUI_"):  # ignore the internal tables of the undo/redo
                self._drop_triggers(table, log_name)

    def _add_triggers(self, table: str, log_name: str) -> None:
        self._add_after_insert_trigger(table, log_name)
        self._add_after_update_trigger(table, log_name)
        self._add_after_delete_trigger(table, log_name)

    def _drop_triggers(self, table: str, log_name: str) -> None:
        with self._store.get_connection() as db_conn:
            db_conn.executescript(
                f"""--sql
                DROP TRIGGER IF EXISTS _{table}_after_insert_{log_name.lower()}_log;
                DROP TRIGGER IF EXISTS _{table}_after_update_{log_name.lower()}_log;
                DROP TRIGGER IF EXISTS _{table}_after_delete_{log_name.lower()}_log;
                """
            )
            db_conn.commit()

    def _add_after_insert_trigger(self, table: str, log_name: str) -> None:
        with self._store.get_connection() as db_conn:
            cmd = f"'DELETE FROM {table} WHERE ROWID='||NEW.ROWID"
            db_conn.execute(
                f"""--sql
                CREATE TEMP TRIGGER IF NOT EXISTS _{table}_after_insert_{log_name.lower()}_log
                AFTER INSERT ON {table}
                BEGIN
                    INSERT INTO _CUI_{log_name.upper()}_LOG(idx,  ord, cmd)
                    VALUES(
                        (SELECT current_idx FROM _CUI_INDEX WHERE h_id=1),
                        COALESCE((
                            SELECT MAX(ord) + 1 FROM _CUI_{log_name.upper()}_LOG
                            WHERE idx=(SELECT current_idx FROM _CUI_INDEX WHERE h_id=1)
                        ), 0),
                        {cmd}
                    );
                END;
                """
            )
            db_conn.commit()

    def _add_after_update_trigger(self, table: str, log_name: str) -> None:
        columns = self._get_columns(table)
        with self._store.get_connection() as db_conn:
            cmd = f"'UPDATE {table} SET "
            cmd += ", ".join(f"{column}='||QUOTE(OLD.{column})||'" for column in columns)
            cmd += " WHERE ROWID='||OLD.ROWID"
            db_conn.execute(
                f"""--sql
                CREATE TEMP TRIGGER IF NOT EXISTS _{table}_after_update_{log_name.lower()}_log
                AFTER UPDATE ON {table}
                BEGIN
                    INSERT INTO _CUI_{log_name.upper()}_LOG(idx, ord, cmd)
                    VALUES(
                        (SELECT current_idx FROM _CUI_INDEX WHERE h_id=1),
                        COALESCE((
                            SELECT MAX(ord) + 1 FROM _CUI_{log_name.upper()}_LOG
                            WHERE idx=(SELECT current_idx FROM _CUI_INDEX WHERE h_id=1)
                        ), 0),
                        {cmd}
                    );
                END;
                """
            )
            db_conn.commit()

    def _add_after_delete_trigger(self, table: str, log_name: str) -> None:
        columns = self._get_columns(table)
        with self._store.get_connection() as db_conn:
            cmd = f"'INSERT INTO {table}("
            cmd += ", ".join(columns)
            cmd += ") VALUES("
            cmd += ",".join(f"'||quote(OLD.{column})||'" for column in columns)
            cmd += ")'"
            db_conn.execute(
                f"""--sql
                CREATE TEMP TRIGGER IF NOT EXISTS _{table}_after_delete_{log_name.lower()}_log
                BEFORE DELETE ON {table}
                BEGIN
                    INSERT INTO _CUI_{log_name.upper()}_LOG(idx, ord, cmd)
                    VALUES(
                        (SELECT current_idx FROM _CUI_INDEX WHERE h_id=1),
                        COALESCE((
                            SELECT MAX(ord) + 1 FROM _CUI_{log_name.upper()}_LOG
                            WHERE idx=(SELECT current_idx FROM _CUI_INDEX WHERE h_id=1)
                        ), 0),
                        {cmd}
                    );
                END;
                """
            )
            db_conn.commit()

    def _get_columns(self, table: str) -> List[str]:
        with self._store.get_connection() as db_conn:
            result = db_conn.execute(
                f"PRAGMA table_info({table})",
            ).fetchall()
        return [row["name"] for row in result]

    def _get_all_tables(self) -> List[str]:
        with self._store.get_connection() as db_conn:
            result = db_conn.execute(
                """--sql
                SELECT name
                FROM sqlite_schema
                WHERE type='table'
                    AND name NOT LIKE 'sqlite_%'
                """
            ).fetchall()
        return [str(row[0]) for row in result]


def rotating_debug_file(max_concurrent_files: int = 10) -> Path:
    """Get a path to a debug file.

    Each time it is called:
        - check if there is more than `max_concurrent_files` files called debug_{i}.db
        - remove the oldest to have at most `max_concurrent_files - 1` files
        - return a path to a new file with a valid name (i.e not already taken)
    """
    # find all the files with the name debug_{i}.db
    current_files = [
        f for f in Path().iterdir() if f.stem[:6] == "debug_" and f.suffix == ".db"
    ]
    # remove the most old files to let at least "max_concurrent_files"
    if len(current_files) > max_concurrent_files:
        current_files = sorted(current_files, key=lambda f: f.stat().st_mtime)
        for f in it.islice(current_files, max_concurrent_files - 1, None):
            with contextlib.suppress(PermissionError):
                f.unlink()
    # find an available name
    for i in it.count():
        f = Path(f"debug_{i}.db")
        if not f.exists():
            return f
    raise ValueError("Can't find an available filename.")

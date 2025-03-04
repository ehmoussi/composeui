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
from typing import Generator, List, Optional, Sequence


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

    def create_only_tables(self) -> None:
        """Create only the tables without the triggers"""
        self.execute_sql_files(self._sql_table_files)

    def create_triggers(self) -> None:
        """Create only the triggers."""
        self.execute_sql_files(self._sql_trigger_files)

    def create_connection(self) -> sqlite3.Connection:
        if self._filepath is not None:
            db_conn = sqlite3.connect(str(self._filepath), check_same_thread=False)
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

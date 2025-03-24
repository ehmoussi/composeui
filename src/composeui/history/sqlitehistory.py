from composeui.history.abstracthistory import AbstractHistory

from typing_extensions import Literal, TypeAlias

import sqlite3
import typing
from pathlib import Path
from typing import List, Optional, Tuple

if typing.TYPE_CHECKING:
    from composeui.store.sqlitestore import SqliteStore


LogName: TypeAlias = Literal["undo", "redo"]


class SqliteHistory(AbstractHistory):
    def __init__(self, store: "SqliteStore") -> None:
        self._store = store

    def open_history(self, filepath: Optional[Path]) -> None:
        self.create_tables()

    def save_history(self, filepath: Path) -> None:
        # the triggers are removed before saving the database
        with self._store.get_connection() as db_conn:
            self._drop_all_triggers("undo", db_conn)
            self._drop_all_triggers("redo", db_conn)

    def create_tables(self) -> None:
        with self._store.get_connection() as db_conn:
            db_conn.execute(
                """--sql
                CREATE TABLE IF NOT EXISTS _CUI_INDEX(
                    h_id INTEGER PRIMARY KEY NOT NULL,
                    current_idx INTEGER,
                    triggers TEXT DEFAULT ""
                )
                """
            )
            db_conn.execute("INSERT OR IGNORE INTO _CUI_INDEX VALUES(1, 0, 1)")
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
            self._add_all_triggers("undo", db_conn)
            self._add_all_triggers("redo", db_conn)
            db_conn.commit()

    def undo(self) -> None:
        """Undo the last index of the history."""
        with self._store.get_connection() as db_conn:
            self._active_triggers("redo", True, db_conn)
            current_idx = self._get_current_idx(db_conn)
            try:
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
                self._active_triggers("redo", False, db_conn)

    def redo(self) -> None:
        """Redo the last index of the history."""
        with self._store.get_connection() as db_conn:
            self._active_triggers("undo", True, db_conn)
            current_idx = self._get_current_idx(db_conn)
            try:
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
                self._active_triggers("undo", False, db_conn)

    def start_recording(self) -> None:
        """Start recording the history."""
        with self._store.get_connection() as db_conn:
            self._active_triggers("undo", True, db_conn)
            self._increment_current_idx(db_conn)
            db_conn.commit()

    def stop_recording(self) -> None:
        """Stop recording the history."""
        with self._store.get_connection() as db_conn:
            self._active_triggers("undo", False, db_conn)
            if self._has_commands("undo", db_conn):
                # The log of the redo need to be deleted because the future have been modified
                # so the redo log contains an outdated timeline
                db_conn.execute(
                    """--sql
                    DELETE FROM _CUI_REDO_LOG
                    """
                )
                # Remove the old actions to not exceed the capacity of the history
                db_conn.execute(
                    f"""--sql
                    DELETE FROM _CUI_UNDO_LOG
                    WHERE idx<={self._get_current_idx(db_conn) - self.get_capacity()}
                    """
                )
            else:
                # no commands have been recorded the index doesn't need to be incremented
                self._decrement_current_idx(db_conn)
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

    def _get_current_idx(self, db_conn: sqlite3.Connection) -> int:
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
        self, current_idx: int, log_name: LogName, db_conn: sqlite3.Connection
    ) -> List[Tuple[int, str]]:
        """Get the commands of the last index of the history."""
        result = db_conn.execute(
            f"""--sql
            SELECT c_id, cmd
            FROM _CUI_{log_name.upper()}_LOG
            WHERE idx = :current_idx
            ORDER BY ord DESC
            """,
            {"current_idx": current_idx},
        ).fetchall()
        return [(int(row[0]), str(row[1])) for row in result]

    def _has_commands(self, log_name: LogName, db_conn: sqlite3.Connection) -> bool:
        """Get the commands of the last index of the history."""
        result = db_conn.execute(
            f"""--sql
            SELECT EXISTS(
                SELECT 1
                FROM _CUI_{log_name.upper()}_LOG
                WHERE idx = :current_idx
                ORDER BY ord
                LIMIT 1
            )
            """,
            {"current_idx": self._get_current_idx(db_conn)},
        ).fetchone()
        if result is not None:
            return bool(result[0])
        return False

    def _active_triggers(
        self, log_name: LogName, is_active: bool, db_conn: sqlite3.Connection
    ) -> None:
        triggers = ""
        if is_active:
            triggers = log_name
        db_conn.execute(
            """--sql
            UPDATE _CUI_INDEX
            SET triggers=:triggers
            WHERE h_id=1
            """,
            {"triggers": triggers},
        )

    def _add_all_triggers(self, log_name: LogName, db_conn: sqlite3.Connection) -> None:
        for table in self._get_all_tables(db_conn):
            self._add_triggers(table, log_name, db_conn)

    def _drop_all_triggers(self, log_name: LogName, db_conn: sqlite3.Connection) -> None:
        for table in self._get_all_tables(db_conn):
            self._drop_triggers(table, log_name, db_conn)

    def _add_triggers(
        self, table: str, log_name: LogName, db_conn: sqlite3.Connection
    ) -> None:
        self._add_after_insert_trigger(table, log_name, db_conn)
        self._add_after_update_trigger(table, log_name, db_conn)
        self._add_after_delete_trigger(table, log_name, db_conn)

    def _drop_triggers(
        self, table: str, log_name: LogName, db_conn: sqlite3.Connection
    ) -> None:
        db_conn.executescript(
            f"""--sql
            DROP TRIGGER IF EXISTS _{table}_after_insert_{log_name.lower()}_log;
            DROP TRIGGER IF EXISTS _{table}_after_update_{log_name.lower()}_log;
            DROP TRIGGER IF EXISTS _{table}_after_delete_{log_name.lower()}_log;
            """
        )
        db_conn.commit()

    def _add_after_insert_trigger(
        self, table: str, log_name: LogName, db_conn: sqlite3.Connection
    ) -> None:
        cmd = f"'DELETE FROM {table} WHERE ROWID='||NEW.ROWID"
        db_conn.execute(
            f"""--sql
            CREATE TRIGGER IF NOT EXISTS _{table}_after_insert_{log_name.lower()}_log
            AFTER INSERT ON {table}
            WHEN (SELECT 1 FROM _CUI_INDEX WHERE h_id=1 AND triggers='{log_name}')
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

    def _add_after_update_trigger(
        self, table: str, log_name: LogName, db_conn: sqlite3.Connection
    ) -> None:
        columns = self._get_columns(table, db_conn)
        cmd = f"'UPDATE {table} SET "
        cmd += ", ".join(f"{column}='||QUOTE(OLD.{column})||'" for column in columns)
        cmd += " WHERE ROWID='||OLD.ROWID"
        db_conn.execute(
            f"""--sql
            CREATE TRIGGER IF NOT EXISTS _{table}_after_update_{log_name.lower()}_log
            AFTER UPDATE ON {table}
            WHEN (SELECT 1 FROM _CUI_INDEX WHERE h_id=1 AND triggers='{log_name}')
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

    def _add_after_delete_trigger(
        self, table: str, log_name: LogName, db_conn: sqlite3.Connection
    ) -> None:
        columns = self._get_columns(table, db_conn)
        cmd = f"'INSERT INTO {table}("
        cmd += ", ".join(columns)
        cmd += ") VALUES("
        cmd += ",".join(f"'||quote(OLD.{column})||'" for column in columns)
        cmd += ")'"
        db_conn.execute(
            f"""--sql
            CREATE TRIGGER IF NOT EXISTS _{table}_after_delete_{log_name.lower()}_log
            BEFORE DELETE ON {table}
            WHEN (SELECT 1 FROM _CUI_INDEX WHERE h_id=1 AND triggers='{log_name}')
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

    def _get_columns(self, table: str, db_conn: sqlite3.Connection) -> List[str]:
        result = db_conn.execute(
            f"PRAGMA table_info({table})",
        ).fetchall()
        return [row["name"] for row in result]

    def _get_all_tables(self, db_conn: sqlite3.Connection) -> List[str]:
        try:
            result = db_conn.execute(
                """--sql
                SELECT name
                FROM sqlite_schema
                WHERE type='table'
                    AND name NOT LIKE 'sqlite_%'
                    AND name NOT LIKE '_CUI_%' -- ignore the internal tables of the undo/redo
                """
            ).fetchall()
        except sqlite3.OperationalError:
            result = db_conn.execute(
                """--sql
                SELECT name
                FROM sqlite_master
                WHERE type='table'
                    AND name NOT LIKE 'sqlite_%'
                    AND name NOT LIKE '_CUI_%' -- ignore the internal tables of the undo/redo
                """
            ).fetchall()
        return [str(row[0]) for row in result]

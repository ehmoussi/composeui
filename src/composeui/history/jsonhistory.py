from composeui.history.abstracthistory import AbstractHistory
from composeui.store.sqlitestore import SqliteStore

from typing_extensions import Literal, TypeAlias

import sqlite3
import typing
from pathlib import Path
from typing import Any, Optional, TypeVar

if typing.TYPE_CHECKING:
    from composeui.store.jsonstore import JsonStore

LogName: TypeAlias = Literal["undo", "redo"]

T = TypeVar("T")


class JsonHistory(AbstractHistory):

    def __init__(self, store: "JsonStore[T]") -> None:
        self._store = store
        self._history_store = SqliteStore(with_history=False)
        self.create_tables()

    def create_tables(self) -> None:
        with self._history_store.get_connection() as db_conn:
            db_conn.execute(
                "CREATE TABLE IF NOT EXISTS _CUI_INDEX(h_id PRIMARY KEY, current_idx)"
            )
            db_conn.execute("INSERT OR IGNORE INTO _CUI_INDEX VALUES(1, 0)")
            db_conn.execute(
                """--sql
                CREATE TABLE IF NOT EXISTS _CUI_UNDO_LOG(
                    c_id INTEGER PRIMARY KEY NOT NULL,
                    idx INTEGER, -- index of an action
                    state_json TEXT
                )
                """
            )
            db_conn.execute(
                """--sql
                CREATE TABLE IF NOT EXISTS _CUI_REDO_LOG(
                    c_id INTEGER PRIMARY KEY NOT NULL,
                    idx INTEGER,
                    state_json TEXT
                )
                """
            )
            db_conn.commit()

    def open_history(self, filepath: Optional[Path]) -> None:
        assert filepath is not None
        self._history_store.open_study(filepath)

    def save_history(self, filepath: Path) -> None:
        self._history_store.save_study(filepath)

    def get_extension(self) -> Optional[str]:
        return self._history_store.get_extension()

    def clear_history(self) -> None:
        self._history_store.clear_study()
        self.create_tables()

    def undo(self) -> None:
        """Undo the last modification on the store."""
        with self._history_store.get_connection() as db_conn:
            current_idx = self._get_current_idx(db_conn)
            state_json = self._get_state_json(current_idx, "undo", db_conn)
            if state_json is not None:
                # remove the state from the undo log
                db_conn.execute(
                    """--sql
                    DELETE FROM _CUI_UNDO_LOG WHERE idx=:current_idx
                    """,
                    {"current_idx": current_idx},
                )
                # decrement the index of the history
                self._decrement_current_idx(db_conn)
                # set the current state to the redo log
                self._set_state_json(self._get_current_idx(db_conn), "redo", db_conn)
                # apply the state
                self._store.root = self._store.from_json(state_json)
                db_conn.commit()

    def redo(self) -> None:
        """Redo the last undo modification on the store."""
        with self._history_store.get_connection() as db_conn:
            current_idx = self._get_current_idx(db_conn)
            state_json = self._get_state_json(current_idx, "redo", db_conn)
            if state_json is not None:
                # remove the state from the redo log
                db_conn.execute(
                    """--sql
                    DELETE FROM _CUI_REDO_LOG WHERE idx=:current_idx
                    """,
                    {"current_idx": current_idx},
                )
                # increment the index
                self._increment_current_idx(db_conn)
                # set the current state to the undo log
                self._set_state_json(self._get_current_idx(db_conn), "undo", db_conn)
                # apply the state
                self._store.root = self._store.from_json(state_json)
                db_conn.commit()

    def start_recording(self) -> None:
        """Start recording the history."""
        with self._history_store.get_connection() as db_conn:
            self._increment_current_idx(db_conn)
            self._set_state_json(self._get_current_idx(db_conn), "undo", db_conn)
            db_conn.commit()

    def stop_recording(self) -> None:
        """Stop recording the history."""
        with self._history_store.get_connection() as db_conn:
            current_idx = self._get_current_idx(db_conn)
            if self._has_state_changed(current_idx, db_conn):
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
                # the state don't changed so it doesn't need to be saved
                db_conn.execute(
                    """--sql
                    DELETE FROM _CUI_UNDO_LOG WHERE idx = :current_idx
                    """,
                    {"current_idx": current_idx},
                )
                self._decrement_current_idx(db_conn)
            db_conn.commit()

    def _get_state_json(
        self, current_idx: int, log_name: LogName, db_conn: sqlite3.Connection
    ) -> Optional[Any]:
        result = db_conn.execute(
            f"""--sql
            SELECT state_json
            FROM _CUI_{log_name.upper()}_LOG
            WHERE idx = :current_idx
            """,
            {"current_idx": current_idx},
        ).fetchone()
        if result is not None:
            return result[0]
        return None

    def _set_state_json(
        self, current_idx: int, log_name: LogName, db_conn: sqlite3.Connection
    ) -> None:
        db_conn.execute(
            f"""--sql
            INSERT INTO _CUI_{log_name.upper()}_LOG(idx, state_json)
            VALUES(:current_idx, :state_json)
            """,
            {"current_idx": current_idx, "state_json": self._store.to_json()},
        )

    def _has_state_changed(self, current_idx: int, db_conn: sqlite3.Connection) -> bool:
        current_state = self._store.to_json()
        old_state = self._get_state_json(current_idx, "undo", db_conn)
        return old_state != current_state

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

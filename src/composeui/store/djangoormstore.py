from composeui.store.abstractstore import AbstractStore

from django.apps import apps
from django.db import connection

import contextlib
import sqlite3
import sys
import typing
from pathlib import Path
from typing import Optional

if typing.TYPE_CHECKING:
    from composeui.history.abstracthistory import AbstractHistory


class DjangoORMStore(AbstractStore):
    def __init__(self, engine: Optional[str] = None, filepath: Optional[Path] = None) -> None:
        super().__init__()
        self._is_debug = False
        self.databases = {
            "default": {
                "ENGINE": engine if engine is not None else "django.db.backends.sqlite3",
                "NAME": filepath if filepath is not None else ":memory",
            }
        }

    def get_history(self) -> Optional["AbstractHistory"]:
        """Get the manager of the undo/redo of the history of the store."""
        return None

    @property
    def is_sqlite(self) -> bool:
        return "sqlite" in str(self.databases["default"]["ENGINE"])

    def get_extension(self) -> str:
        if self.is_sqlite:
            return ".sqlite"
        else:
            raise ValueError("Cannot get an extension for a database that is not sqlite.")

    def set_debug_mode(self, is_debug: bool) -> None:
        self._is_debug = is_debug
        # TODO: Manage the sqlite case

    def clear_study(self) -> None:
        if not self.is_sqlite:
            raise ValueError("Cannot clear a study for a database that is not sqlite.")
        else:
            for model in apps.get_models():
                model.objects.all().delete()

    def new_study(self) -> None:
        self.clear_study()

    def save_study(self, filepath: Path) -> None:
        if not self.is_sqlite:
            raise ValueError("Cannot save a study for a database that is not sqlite.")
        with contextlib.closing(
            sqlite3.connect(str(filepath), check_same_thread=False)
        ) as filepath_con:
            connection.commit()  # ensure all the transactions are commited before backup
            with contextlib.closing(connection) as current_con:
                if sys.version_info >= (3, 7, 0):  # noqa: UP036
                    current_con.connection.backup(filepath_con)
                else:
                    filepath_con.executescript("".join(current_con.connection.iterdump()))
                    filepath_con.commit()

    def open_study(self, filepath: Path) -> None:
        if not self.is_sqlite:
            raise ValueError("Cannot close a study for a database that is not sqlite.")
        self.clear_study()
        with contextlib.closing(sqlite3.connect(str(filepath))) as filepath_con:
            if sys.version_info < (3, 7, 0):  # noqa: UP036
                with connection.cursor() as cursor:
                    for line in filepath_con.iterdump():
                        if "CREATE TABLE" not in line.upper():
                            cursor.execute(line)
            else:
                filepath_con.backup(connection.connection)

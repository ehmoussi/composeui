"""SqlAlchemy store."""

from composeui.history.abstracthistory import AbstractHistory
from composeui.store.abstractstore import AbstractStore

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

import contextlib
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Tuple

if TYPE_CHECKING:
    from sqlalchemy import Engine

if sys.version_info >= (3, 8):

    from sqlalchemy.orm import DeclarativeBase

    class SqlAlchemyDataBase(DeclarativeBase):
        pass

else:
    from sqlalchemy.ext.declarative import declarative_base

    SqlAlchemyDataBase = declarative_base()


class SqlAlchemyStore(AbstractStore):
    def __init__(self, url: Optional[str] = None) -> None:
        self._is_debug = False
        self._tmp_sqlite_filepath: Optional[Path] = None
        self.engine, self._url, self.session_maker = self.create_engine(url)

    @property
    def is_sqlite(self) -> bool:
        return self._is_sqlite(self._url)

    def get_extension(self) -> str:
        if self.is_sqlite:
            return ".sqlite"
        else:
            raise ValueError("Cannot get an extension for a database that is not sqlite.")

    def get_history(self) -> Optional[AbstractHistory]:
        return None

    def set_debug_mode(self, is_debug: bool) -> None:
        self._is_debug = is_debug
        self.engine.echo = is_debug

    def clear_study(self) -> None:
        """Clear all the data."""
        if not self.is_sqlite:
            raise ValueError("Cannot clear a study for a database that is not sqlite.")
        else:
            self.close_db()

    def new_study(self) -> None:
        """Create a new study."""
        if self.is_sqlite:
            self.close_db()
            self.engine, self._url, self.session_maker = self.create_engine()
        else:
            raise ValueError("Cannot create a new study for a database that is not sqlite.")

    def save_study(self, filepath: Path) -> None:
        r"""Save the database to the given filepath."""
        if not self.is_sqlite:
            raise ValueError("Cannot save a study for a database that is not sqlite.")
        with contextlib.closing(
            sqlite3.connect(str(filepath), check_same_thread=False)
        ) as filepath_con:
            if sys.version_info >= (3, 7, 0):  # noqa: UP036
                with contextlib.closing(self.engine.raw_connection()) as current_con:
                    current_con.backup(filepath_con)  # type: ignore[attr-defined]
            else:
                with contextlib.closing(self.engine.raw_connection()) as current_con:
                    filepath_con.executescript(
                        "".join(current_con.iterdump())  # type: ignore[attr-defined]
                    )
                    filepath_con.commit()

    def open_study(self, filepath: Path) -> None:
        r"""Read the database from the given filepath."""
        self.close_db()
        if sys.version_info < (3, 7, 0):  # noqa: UP036
            self.engine, self._url, self.session_maker = self.create_engine()
            with self.session_maker() as session, contextlib.closing(
                sqlite3.connect(str(filepath))
            ) as filepath_con:
                for line in filepath_con.iterdump():
                    if "CREATE TABLE" not in line.upper():
                        session.execute(text(line))
        else:
            with contextlib.closing(sqlite3.connect(str(filepath))) as filepath_con:
                self.engine, self._url, self.session_maker = self.create_engine()
                with contextlib.closing(self.engine.raw_connection()) as current_con:
                    if current_con.dbapi_connection is not None:
                        filepath_con.backup(current_con.dbapi_connection)  # type: ignore[arg-type]
                    else:
                        raise ValueError("The current connection can't do a backup.")

    def get_session(self) -> Session:
        # SqlAlchemyDataBase.metadata.create_all(self.engine)
        return self.session_maker()

    def get_engine(self) -> "Engine":
        return self.engine

    def create_engine(
        self, url: Optional[str] = None
    ) -> Tuple["Engine", str, "sessionmaker[Session]"]:
        """Create an engine and the connection to the database."""
        if url is None:
            with tempfile.NamedTemporaryFile(
                prefix="sqlalchemy_store_", suffix=".sqlite", delete=False
            ) as tmp_sqlite_file:
                ...
            self._tmp_sqlite_filepath = Path(tmp_sqlite_file.name).resolve()
            url = (
                f"sqlite+pysqlite:///{self._tmp_sqlite_filepath}"  # ?check_same_thread=False"
            )
        engine = create_engine(url, echo=self._is_debug)
        session_maker = sessionmaker(engine)
        with session_maker() as session:
            if self._is_sqlite(url):
                current_dir = Path(__file__).parent
                for line in Path(current_dir, "settings.sql").read_text().split("\n"):
                    session.execute(text(line))
                session.commit()
        SqlAlchemyDataBase.metadata.create_all(engine)
        return engine, url, session_maker

    def close_db(self) -> None:
        self.engine.dispose()
        # remove the current temporary file
        if self._tmp_sqlite_filepath is not None and self._tmp_sqlite_filepath.exists():
            self._tmp_sqlite_filepath.unlink()

    def _is_sqlite(self, url: str) -> bool:
        return "sqlite" in url

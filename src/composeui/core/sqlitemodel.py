"""A model keeping the app's data in a SQLite database of its own.

The app writes its schema and its queries, in `SqliteTable` classes; the model gives
them a connection, runs each block of work as one transaction, and saves and opens the
database with the study. It works on a scratch copy in a temporary file: the user's
study only changes when it's saved.
"""

from __future__ import annotations

import contextlib
import os
import re
import sqlite3
import tempfile
import threading
import time
import weakref
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Callable, ClassVar, Generic, TypeVar, Union, cast

from composeui.core.jobs import current_job
from composeui.core.model import InvalidStateError, Model, RefusedError
from composeui.core.signal import Signal, SignalNoArgs
from composeui.core.view import CONVERTER

if TYPE_CHECKING:
    from collections.abc import Generator, Mapping, Sequence

    from typing_extensions import TypeAlias, Unpack

    #: a query's parameters: by position, or by name
    Parameters: TypeAlias = Union[Sequence[Any], Mapping[str, Any]]

T = TypeVar("T")
SqliteTableT = TypeVar("SqliteTableT", bound="SqliteTable")


def as_parameters(row: object) -> dict[str, Any]:
    """Get an `attrs` instance's fields by name, as named parameters of a query."""
    parameters: dict[str, Any] = CONVERTER.unstructure(row)
    return parameters


def _identifier(name: str) -> str:
    """Quote a table's or a column's name for SQL, which can't take it as a parameter."""
    return '"' + name.replace('"', '""') + '"'


def unique_name(db: sqlite3.Connection, table: str, column: str, base: str) -> str:
    """Get `base`, or else "`base` 2", "`base` 3"..., the first no row of `table` has.

    Names differing only by case are the same name (a ``COLLATE NOCASE`` column's), e.g. to
    add a "Room" whatever rooms there are already.
    """
    sql = f"SELECT {_identifier(column)} FROM {_identifier(table)}"  # noqa: S608 (quoted)
    taken = {str(name).casefold() for (name,) in db.execute(sql) if name is not None}
    name, number = base, 1
    while name.casefold() in taken:
        number += 1
        name = f"{base} {number}"
    return name


class SqliteTable:
    """A table of a `SqliteModel` (or a few related ones), with the queries the app needs.

    `create` is the SQL script that creates it, run in every new study. Its methods read
    and write through `connection()`. `changed` is emitted once a transaction that changed
    rows through the table has committed, so the views that show them can refresh.

    A constraint that fails in a transaction refuses it: `connection()` raises a
    `RefusedError`. Its message is the one of the first key of `refusals` found in
    SQLite's message: a constraint's name, or e.g. "UNIQUE constraint failed: room.name".
    Else it is SQLite's message.
    """

    create: ClassVar[str] = ""
    #: by a part of SQLite's message, the user's message when a constraint fails, as
    #: written in the code: the view showing it translates it (see `View.refusing`)
    refusals: ClassVar[Mapping[str, str]] = MappingProxyType({})

    def __init__(self, model: SqliteModel) -> None:
        # weak: the model owns its tables, and should go (with its file) once unused
        self._model = cast("SqliteModel", weakref.proxy(model))
        self.changed = SignalNoArgs()

    @contextlib.contextmanager
    def connection(self) -> Generator[sqlite3.Connection]:
        """Give the database's connection for one transaction; see `SqliteModel.connection`.

        Raises `RefusedError` when a constraint fails, the transaction rolled back.
        """
        try:
            with self._model.connection(changing=self) as db:
                yield db
        except sqlite3.IntegrityError as error:
            message = str(error)
            refusal = next((text for key, text in self.refusals.items() if key in message), message)
            raise RefusedError(refusal) from error

    def fetch(self, cls: type[T], sql: str, parameters: Parameters = ()) -> list[T]:
        """Run the query `sql` and get its rows as `cls` instances (an `attrs` class)."""
        with self.connection() as db:
            return [CONVERTER.structure(dict(row), cls) for row in db.execute(sql, parameters)]

    def fetch_one(self, cls: type[T], sql: str, parameters: Parameters = ()) -> T | None:
        """Run the query `sql` and get its first row as a `cls` instance; None if none."""
        with self.connection() as db:
            row = db.execute(sql, parameters).fetchone()
        return None if row is None else CONVERTER.structure(dict(row), cls)

    def fetch_column(self, sql: str, parameters: Parameters = ()) -> list[Any]:
        """Run the query `sql` and get its rows' first column, e.g. a list of names."""
        with self.connection() as db:
            return [row[0] for row in db.execute(sql, parameters)]


class _DeclaredTable(Generic[SqliteTableT]):
    """A table a `SqliteModel` class declares, which each model builds (see `table`)."""

    def __init__(self, table_type: type[SqliteTableT]) -> None:
        self.table_type = table_type


def table(table_type: type[SqliteTableT]) -> SqliteTableT:
    """Declare a table of a `SqliteModel`, in the model's class.

    E.g. ``runs = table(Runs)``. Each model builds its own table, as an attribute of the
    same name, before it creates its database. The tables are built in the order the
    classes declare them, a base class's first.
    """
    # the model's attribute is the table: typed as one, as `attrs.Factory` is
    return cast("SqliteTableT", _DeclaredTable(table_type))


class SqliteModel(Model):
    """A model whose data is a SQLite database, saved and opened with the study.

    Declare the tables in the class, ``runs = table(Runs)``, for the callbacks to reach
    (``model.runs.add(...)``), or add them in `__init__` with `add_table`. A study's
    database is created from the tables' `create` scripts at `schema_version`. When a
    study saved at an older version is opened, `migrations` bring it up to date.
    """

    data_name: ClassVar[str | None] = "data.sqlite"
    #: the tables' version, kept in the database (``PRAGMA user_version``); raise it with
    #: every change to the tables, adding the migration from the previous one
    schema_version: ClassVar[int] = 1
    #: by version: the function bringing a database at that version to the next one
    migrations: ClassVar[Mapping[int, Callable[[sqlite3.Connection], None]]] = {}
    #: seconds opening a study's database may take, checks and migrations included: its
    #: schema comes from the file, and a view of it may never finish (e.g. a recursive one)
    open_time_limit: ClassVar[float] = 30.0
    #: set on the connection of every study's database: SQLite keeps these per connection,
    #: not in the file, and New and Open each start a connection of their own. No WAL
    #: journal: it lets other connections read during a write, and the model has one
    pragmas: ClassVar[Mapping[str, int | str]] = MappingProxyType(
        {
            "foreign_keys": "ON",
            # the database is a scratch copy nothing reopens after a crash: waiting for the
            # disk on every commit protects nothing, the study file is written apart
            "synchronous": "OFF",
            # a row replaced (`INSERT OR REPLACE`) fires its delete triggers, and a trigger
            # may fire itself, so triggers keeping other tables up to date see every change
            "recursive_triggers": "ON",
        }
    )

    def __init__(self) -> None:
        self._tables: list[SqliteTable] = []
        declared: dict[str, _DeclaredTable[Any]] = {}
        for cls in reversed(type(self).__mro__):
            declared.update(
                (name, value)
                for name, value in vars(cls).items()
                if isinstance(value, _DeclaredTable)
            )
        for name, declared_table in declared.items():
            # before the database, which `_new_database` creates with them
            built = declared_table.table_type(self)
            self._tables.append(built)
            setattr(self, name, built)
        # one connection for the model, which threads (a worker, web requests) take in turn
        self._lock = threading.RLock()
        self._depth = 0
        self._changed: list[SqliteTable] = []
        self._database = self._new_database()

    @property
    def signals(self) -> list[Signal[Unpack[tuple[Any, ...]]]]:
        """Get the model's signals, its tables' (`SqliteTable.changed`) among them."""
        tables = [vars(table).values() for table in self._tables]
        return [
            *super().signals,
            *(value for values in tables for value in values if isinstance(value, Signal)),
        ]

    def add_table(self, table_type: type[SqliteTableT]) -> SqliteTableT:
        """Add a table, created in the current database too, and return it."""
        table = table_type(self)
        with self._lock:
            self._database.connection.executescript(table.create)
        self._tables.append(table)
        return table

    @contextlib.contextmanager
    def connection(self, *, changing: SqliteTable | None = None) -> Generator[sqlite3.Connection]:
        """Give the database's connection for one transaction.

        The transaction commits once the block ends, or rolls back if the block raises, so
        its writes land together or not at all. A block inside another (one table's method
        calling another's) joins the outer transaction. If the block changed rows,
        `changing`'s `changed` is emitted after the commit. For a block in a job's thread, it
        is emitted on the main thread (see `Job.call_on_main_thread`), where the views it
        refreshes are.
        """
        changed: list[SqliteTable] = []
        with self._lock:
            db = self._database.connection
            before = db.total_changes
            outermost = self._depth == 0
            self._depth += 1
            try:
                yield db
                if (
                    changing is not None
                    and db.total_changes != before
                    and changing not in self._changed
                ):
                    self._changed.append(changing)
                if outermost:
                    db.commit()
                    changed, self._changed = self._changed, []
            except BaseException:
                if outermost:
                    db.rollback()
                    self._changed = []
                raise
            finally:
                self._depth -= 1
        # outside the lock: a view refreshing may query another thread's way
        job = current_job()
        for table in changed:
            if job is None:
                table.changed.emit()
            else:
                job.call_on_main_thread(table.changed.emit)

    def new(self) -> None:
        self._replace_database(self._new_database())

    def save_data(self, path: Path) -> None:
        target = sqlite3.connect(str(path))
        try:
            with self._lock:
                self._database.connection.backup(target)
        finally:
            target.close()

    def open_data(self, path: Path) -> None:
        """Open a study's database, refused unless it is made as a new one is.

        The file may come from anyone (e.g. a web upload): its schema is the file's own,
        whose views and triggers would run in the app. Until it is checked, its views and
        triggers may call no function with side effects (`trusted_schema`), and the whole
        open is cut after `open_time_limit`.
        """
        database = _Database(self.pragmas)
        db = database.connection
        try:
            source = sqlite3.connect(str(path))
            try:
                source.backup(db)
            finally:
                source.close()
            db.execute("PRAGMA trusted_schema = OFF")
            deadline = time.monotonic() + self.open_time_limit
            # a true answer interrupts the statement running (`OperationalError`)
            db.set_progress_handler(lambda: time.monotonic() > deadline, 10_000)
            try:
                self._check(db)
                self._upgrade(db)
                self._check_schema(db)
            finally:
                db.set_progress_handler(None, 0)
            db.execute(
                _pragma_statement("trusted_schema", self.pragmas.get("trusted_schema", "ON"))
            )
        except sqlite3.DatabaseError as error:
            database.close()
            msg = "its data isn't a valid database"
            raise InvalidStateError(msg) from error
        except BaseException:
            database.close()
            raise
        self._replace_database(database)

    def loaded(self) -> None:
        # every table may have changed; emitted only now, so the views refreshing read the
        # study's views (e.g. a filter), not the ones it replaces
        for table in self._tables:
            table.changed.emit()

    def close(self) -> None:
        self._database.close()

    def _new_database(self) -> _Database:
        database = _Database(self.pragmas)
        db = database.connection
        for table in self._tables:
            db.executescript(table.create)
        # an int, which a pragma can't take as a parameter
        db.execute(f"PRAGMA user_version = {int(self.schema_version)}")
        db.commit()
        return database

    def _replace_database(self, database: _Database) -> None:
        with self._lock:
            previous, self._database = self._database, database
        previous.close()

    def _check(self, db: sqlite3.Connection) -> None:
        # not `quick_check`, which skips the indexes' content: a study's database is small
        (result,) = db.execute("PRAGMA integrity_check").fetchone()
        if result != "ok":
            msg = "its data is damaged"
            raise InvalidStateError(msg)

    def _check_schema(self, db: sqlite3.Connection) -> None:
        """Refuse a database (brought up to date) not made as a new one is."""
        new = self._new_database()
        try:
            expected = _schema(new.connection)
        finally:
            new.close()
        if _schema(db) != expected:
            msg = "its data doesn't match this application"
            raise InvalidStateError(msg)

    def _upgrade(self, db: sqlite3.Connection) -> None:
        """Bring a database opened from a study up to `schema_version`."""
        (version,) = db.execute("PRAGMA user_version").fetchone()
        if version > self.schema_version:
            msg = "it was saved by a newer version of the application"
            raise InvalidStateError(msg)
        if version < 1:  # every study's database has a version: this one isn't a study's
            msg = "its data doesn't match this application"
            raise InvalidStateError(msg)
        for step in range(version, self.schema_version):
            migrate = self.migrations.get(step)
            if migrate is None:
                msg = f"its data (version {version}) can't be brought up to date"
                raise InvalidStateError(msg)
            migrate(db)
        db.execute(f"PRAGMA user_version = {int(self.schema_version)}")
        db.commit()


class _Database:
    """A connection to a scratch database in a temporary file, deleted with it."""

    def __init__(self, pragmas: Mapping[str, int | str]) -> None:
        statements = [_pragma_statement(name, value) for name, value in pragmas.items()]
        fd, name = tempfile.mkstemp(prefix="composeui-", suffix=".sqlite")
        os.close(fd)
        self.path = Path(name)
        # threads take turns through the model's lock
        self.connection = sqlite3.connect(name, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        for statement in statements:
            self.connection.execute(statement)
        # also when the model is dropped unclosed (e.g. an expired web session's)
        self._finalizer = weakref.finalize(self, _discard, self.connection, self.path)

    def close(self) -> None:
        self._finalizer()


def _schema(db: sqlite3.Connection) -> set[tuple[object, ...]]:
    """Get what a database is made of: each table's columns, each other object's SQL.

    A table's columns, not its SQL: a migration can only add a column (`ALTER TABLE ...
    ADD COLUMN`), without the `CHECK` or `REFERENCES` a new database's table may have.
    Neither can query the database, so the file's own are kept.
    """
    schema: set[tuple[object, ...]] = set()
    for kind, name, table_name, sql in db.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_master"
    ):
        if kind == "table":
            # by name, not position: a column added by a migration comes last
            rows = db.execute("SELECT * FROM pragma_table_xinfo(?)", (name,))
            schema.add((kind, name, frozenset(tuple(row)[1:] for row in rows)))
        else:
            schema.add((kind, name, table_name, " ".join((sql or "").split())))
    return schema


def _pragma_statement(name: str, value: int | str) -> str:
    """Get the statement setting a pragma, which can't take its value as a parameter."""
    if re.fullmatch(r"[A-Za-z_]+", name) is None or (
        isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]+", value) is None
    ):
        msg = f"Not a pragma setting: {name} = {value!r}"
        raise ValueError(msg)
    return f"PRAGMA {name} = {value}"


def _discard(connection: sqlite3.Connection, path: Path) -> None:
    connection.close()
    path.unlink(missing_ok=True)

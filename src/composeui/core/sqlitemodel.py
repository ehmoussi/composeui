"""A model keeping the app's data in a SQLite database of its own.

The app writes its schema and its queries, in `SqliteTable` classes; the model gives
them a connection, runs each block of work as one transaction, and saves and opens the
database with the study. It works on a scratch copy in a temporary file: the user's
study only changes when it's saved.
"""

from __future__ import annotations

import contextlib
import datetime
import decimal
import functools
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
from composeui.core.view import (
    CONVERTER,
    ColumnKind,
    Filter,
    FilterOperator,
    Sort,
    SourceColumn,
    column_kind,
)

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

    @contextlib.contextmanager
    def reading(self) -> Generator[sqlite3.Connection]:
        """Give a connection reading the database alone; see `SqliteModel.reading`."""
        with self._model.reading() as db:
            yield db

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


#: the seconds a connection waits for another's lock before it fails: in the WAL journal,
#: only a write for another's, or a `PRAGMA` changing the journal
WAIT_SECONDS = 60.0
#: the ids a query takes at most at once, below SQLite's limit of parameters
_IDS_PER_QUERY = 900
#: each text operator, as a `LIKE` pattern of the filter's value (escaped), negated or not
_LIKES: Mapping[FilterOperator, tuple[str, bool]] = MappingProxyType(
    {
        FilterOperator.CONTAINS: ("%{}%", False),
        FilterOperator.NOT_CONTAINS: ("%{}%", True),
        FilterOperator.STARTS_WITH: ("{}%", False),
        FilterOperator.ENDS_WITH: ("%{}", False),
    }
)
#: each text comparison, in SQL, ignoring the case of ASCII letters
_TEXT_COMPARISONS: Mapping[FilterOperator, str] = MappingProxyType(
    {FilterOperator.TEXT_EQUAL: "=", FilterOperator.TEXT_NOT_EQUAL: "<>"}
)
#: each comparison, in SQL
_COMPARISONS: Mapping[FilterOperator, str] = MappingProxyType(
    {
        FilterOperator.EQUAL: "=",
        FilterOperator.NOT_EQUAL: "<>",
        FilterOperator.LESS: "<",
        FilterOperator.LESS_OR_EQUAL: "<=",
        FilterOperator.GREATER: ">",
        FilterOperator.GREATER_OR_EQUAL: ">=",
    }
)


def _escaped(text: str) -> str:
    r"""Escape `LIKE`'s wildcards in `text`, with a backslash (``ESCAPE '\'``)."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _sql_value(value: Any) -> Any:
    """Get a filter's value as SQLite stores it: a date as ISO text, a number as a number."""
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return float(value)
    return value  # an enum's column filters as text: never compared


@functools.lru_cache(maxsize=32)
def _compiled(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


def _casefold(value: Any) -> str:
    """SQL's ``casefold``: a cell's text as Python compares it, ignoring any case."""
    return "" if value is None else str(value).casefold()


def _folded(cell: str, *, is_ascii: bool) -> str:
    """Get the SQL of `cell`, case-folded by Python unless compared with ASCII text typed.

    SQLite ignores the case of ASCII letters alone: "é" wouldn't find "É". Text typed in
    ASCII keeps SQLite's comparison, which an index serves, without Python's call per row
    (3 to 4 times slower). It doesn't find a cell whose letters fold into it: "strasse"
    doesn't find "Straße", which "Straße" finds.
    """
    return cell if is_ascii else f"casefold({cell})"


def _regexp(pattern: str, value: Any) -> bool:
    """SQLite's ``REGEXP``: whether `pattern` is found in `value`'s text, ignoring case."""
    return _compiled(pattern).search("" if value is None else str(value)) is not None


class SqliteSource:
    """A `TableSource` of a query's rows, which a large table reads a window at a time.

    It takes the `SqliteTable` whose rows the query reads, the query itself, the column
    of the rows' ids (e.g. a primary key) and the query's columns that the table shows.
    SQLite sorts and filters the rows: the order is a ``SELECT`` of the ids, and the cells
    a ``SELECT`` of some ids' rows, so no more rows than those shown come to Python. The
    table's `changed` reads them again. Only the declared columns sort and filter, by name:
    SQLite takes no column name as a parameter, the values are. It reads on connections
    of its own (`SqliteModel.reading`): the rows committed, never waiting for a write, nor
    the cells for the order a job reads.

    A text compares ignoring its case as a `ListSource` does, but text typed in ASCII
    alone compares in SQLite (see `_folded`). It sorts ignoring the case of ASCII letters
    alone (``NOCASE``). Equal cells, and the rows unsorted, keep the order of their ids.
    A ``/regex/`` filter, or a text not in ASCII, calls Python on each row: index the
    columns that sort instead.
    """

    def __init__(
        self,
        table: SqliteTable,
        query: str,
        *,
        id_column: str,
        columns: Sequence[SourceColumn],
    ) -> None:
        self._table = table
        self._query = query
        self._id = _identifier(id_column)
        self._columns = {column.name: column for column in columns}

    @property
    def columns(self) -> Sequence[SourceColumn]:
        return tuple(self._columns.values())

    @property
    def changed(self) -> SignalNoArgs:
        return self._table.changed

    def count(self) -> int:
        with self._table.reading() as db:
            # read to the end: the connection is reused (see `SqliteModel.reading`)
            ((count,),) = db.execute(f"SELECT COUNT(*) FROM ({self._query})").fetchall()  # noqa: S608 (the app's query)
        return int(count)

    def ordered_ids(
        self, sort: Sort | None, search: str, filters: Mapping[str, Filter]
    ) -> list[Any]:
        conditions: list[str] = []
        parameters: list[Any] = []
        needle = search.strip()
        texts = [
            name
            for name, column in self._columns.items()
            if column_kind(column.type) is ColumnKind.TEXT
        ]
        if needle != "" and len(texts) == 0:
            conditions.append("0")  # no text column holds it, as a `ListSource` finds
        elif needle != "":
            is_ascii = needle.isascii()
            if not is_ascii:
                needle = needle.casefold()
            cells = [_folded(_identifier(name), is_ascii=is_ascii) for name in texts]
            conditions.append(
                "(" + " OR ".join(f"{cell} LIKE ? ESCAPE '\\'" for cell in cells) + ")"
            )
            parameters.extend([f"%{_escaped(needle)}%"] * len(texts))
        for name, row_filter in filters.items():
            condition, values = self._condition(self._column(name), row_filter)
            conditions.append(condition)
            parameters.extend(values)
        # by id unsorted: else in the order of an index a filter reads by, no header showing it
        queries = [(conditions, self._id)]
        if sort is not None:
            column = self._column(sort.column)
            name = _identifier(column.name)
            is_text = column_kind(column.type) is ColumnKind.TEXT
            order = f"{name} COLLATE NOCASE" if is_text else name
            direction = " DESC" if sort.descending else ""
            empty = f"({name} IS NULL OR {name} = '')"
            if len(conditions) > 0:
                # the empty cells last, in both orders, SQLite sorting the rows passing:
                # read in their column's index order, the table would be read row by row
                queries = [(conditions, f"{empty} ASC, {order}{direction}, {self._id}")]
            else:
                # apart, the cells with a value read in their column's index order: an
                # ORDER BY starting with the empty cells couldn't
                queries = [
                    ([f"NOT {empty}"], f"{order}{direction}, {self._id}"),
                    ([empty], self._id),
                ]
        with self._table.reading() as db:
            db.create_function("regexp", 2, _regexp, deterministic=True)
            db.create_function("casefold", 1, _casefold, deterministic=True)
            db.execute("BEGIN")  # the queries read the same rows, a write committed between
            try:
                return [
                    row[0]
                    for where, order_by in queries
                    for row in db.execute(self._select_ids(where, order_by), parameters)
                ]
            finally:
                db.rollback()

    def _select_ids(self, conditions: list[str], order_by: str) -> str:
        """Get the query of the ids of the rows passing `conditions`, ordered by `order_by`."""
        sql = f"SELECT {self._id} FROM ({self._query})"  # noqa: S608 (quoted, the app's query)
        if len(conditions) > 0:
            sql += " WHERE " + " AND ".join(conditions)
        return f"{sql} ORDER BY {order_by}"

    def cells(self, ids: Sequence[Any], columns: Sequence[str]) -> dict[Any, list[Any]]:
        types = [self._column(name).type for name in columns]
        names = ", ".join(_identifier(name) for name in columns)
        found: dict[Any, list[Any]] = {}
        with self._table.reading() as db:
            for start in range(0, len(ids), _IDS_PER_QUERY):
                chunk = list(ids[start : start + _IDS_PER_QUERY])
                marks = ", ".join("?" * len(chunk))
                sql = (
                    f"SELECT {self._id}, {names} FROM ({self._query})"  # noqa: S608 (quoted)
                    f" WHERE {self._id} IN ({marks})"
                )
                for row in db.execute(sql, chunk):
                    found[row[0]] = [
                        None if value is None else CONVERTER.structure(value, field_type)
                        for value, field_type in zip(tuple(row)[1:], types)
                    ]
        return found

    def _column(self, name: str) -> SourceColumn:
        column = self._columns.get(name)
        if column is None:
            msg = f"Cannot read the column {name!r} of a SqliteSource: it declares none so."
            raise ValueError(msg)
        return column

    @staticmethod
    def _condition(column: SourceColumn, row_filter: Filter) -> tuple[str, list[Any]]:
        """Get the SQL condition of `row_filter` on `column`, and its parameters.

        As `Filter.matches` reads a cell: an empty one's text is "", and it fails a
        comparison.
        """
        name = _identifier(column.name)
        text = f"COALESCE({name}, '')"
        operator, value = row_filter.operator, row_filter.value
        if operator is FilterOperator.EMPTY:
            return f"({name} IS NULL OR {name} = '')", []
        if operator in _LIKES:
            pattern, is_negated = _LIKES[operator]
            negation = "NOT " if is_negated else ""
            cell = _folded(text, is_ascii=row_filter.typed_ascii)
            return f"{cell} {negation}LIKE ? ESCAPE '\\'", [pattern.format(_escaped(value))]
        if operator in _TEXT_COMPARISONS:
            collation = " COLLATE NOCASE" if row_filter.typed_ascii else ""
            cell = _folded(text, is_ascii=row_filter.typed_ascii)
            return f"{cell} {_TEXT_COMPARISONS[operator]} ?{collation}", [value]
        if operator is FilterOperator.MATCHES:
            return f"regexp(?, {name})", [value.pattern]
        if operator is FilterOperator.RANGE:
            return f"{name} BETWEEN ? AND ?", [_sql_value(value), _sql_value(row_filter.upper)]
        return f"{name} {_COMPARISONS[operator]} ?", [_sql_value(value)]


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
    #: set on the connections of every study's database: SQLite keeps these per
    #: connection, not in the file, and New and Open each start a connection of their own
    pragmas: ClassVar[Mapping[str, int | str]] = MappingProxyType(
        {
            # the connections `reading` read during a write, its rows uncommitted (else a
            # write spilling to the disk locks them out until it commits); the study file
            # is saved in the default journal (`save_data`)
            "journal_mode": "WAL",
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
        # which database the queries `reading` read, and how many: held for no query, so a
        # read never waits for the turn a write holds
        self._readers_lock = threading.Lock()
        self._closed = False
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

    @contextlib.contextmanager
    def reading(self) -> Generator[sqlite3.Connection]:
        """Give a connection that only reads the database, for a long query.

        Unlike `connection()`, it waits for no other thread's turn, and holds none: the
        model's other queries run meanwhile, e.g. a large table's cells while a job orders
        its rows or writes some (`SqliteSource`). In the WAL journal, it reads the rows
        committed, during a write too. A database New or Open replace meanwhile, or the
        model's `close`, is deleted once the query is over. Once the model is closed,
        raises `sqlite3.ProgrammingError`, as `connection()` does: e.g. a web download
        its session's end cuts short.

        The connection is reused, e.g. for the next window of a large table: read each
        query's rows to the end in the block. A query left half read keeps the rows as
        they were when it started, for the next reader too.
        """
        with self._readers_lock:
            if self._closed:  # its file is gone
                msg = "Cannot operate on a closed database."
                raise sqlite3.ProgrammingError(msg)
            database = self._database
            database.readers += 1
            db = database.idle_readers.pop() if len(database.idle_readers) > 0 else None
        try:
            if db is None:
                db = database.open_reader()
            yield db
        finally:
            with self._readers_lock:
                database.readers -= 1
                if db is not None:
                    database.idle_readers.append(db)
                if database.readers == 0 and (database is not self._database or self._closed):
                    database.close()

    def new(self) -> None:
        self._replace_database(self._new_database())

    def save_data(self, path: Path) -> None:
        target = sqlite3.connect(str(path))
        try:
            with self._lock:
                self._database.connection.backup(target)
            # the backup copies the WAL journal: a file another app opens leaves none beside it
            target.execute("PRAGMA journal_mode = DELETE")
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
            database.start_journal()  # after the backup: it keeps the file's page size
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
        # not the write's turn: closing the app doesn't wait for a job's long write
        with self._readers_lock:
            self._closed = True
            if self._database.readers == 0:  # else the last query `reading` it closes it
                self._database.close()

    def _new_database(self) -> _Database:
        database = _Database(self.pragmas)
        database.start_journal()
        db = database.connection
        for table in self._tables:
            db.executescript(table.create)
        # an int, which a pragma can't take as a parameter
        db.execute(f"PRAGMA user_version = {int(self.schema_version)}")
        db.commit()
        return database

    def _replace_database(self, database: _Database) -> None:
        with self._lock, self._readers_lock:
            previous, self._database = self._database, database
            if previous.readers > 0:
                return  # closed once the queries `reading` it are over
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
    """A connection to a scratch database in a temporary file, deleted with it.

    Its journal is SQLite's default until `start_journal` sets the one of `pragmas`: a
    backup into a WAL database from one of another page size fails.
    """

    def __init__(self, pragmas: Mapping[str, int | str]) -> None:
        statements = [
            _pragma_statement(name, value)
            for name, value in pragmas.items()
            if name != "journal_mode"
        ]
        #: the model's `pragmas`, set on each connection: SQLite keeps them per connection
        self.pragma_statements = statements
        journal = pragmas.get("journal_mode")
        self._journal = None if journal is None else _pragma_statement("journal_mode", journal)
        fd, name = tempfile.mkstemp(prefix="composeui-", suffix=".sqlite")
        os.close(fd)
        self.path = Path(name)
        # threads take turns through the model's lock
        self.connection = sqlite3.connect(name, check_same_thread=False, timeout=WAIT_SECONDS)
        self.connection.row_factory = sqlite3.Row
        for statement in statements:
            self.connection.execute(statement)
        #: the read-only connections not in use, for the next queries `reading` it
        self.idle_readers: list[sqlite3.Connection] = []
        # also when the model is dropped unclosed (e.g. an expired web session's)
        self._finalizer = weakref.finalize(
            self, _discard, self.connection, self.path, self.idle_readers
        )
        #: the queries reading it on connections of their own (`SqliteModel.reading`)
        self.readers = 0

    def open_reader(self) -> sqlite3.Connection:
        """Open a read-only connection, with the model's `pragmas`: any thread uses it."""
        uri = f"{self.path.as_uri()}?mode=ro"
        reader = sqlite3.connect(uri, uri=True, timeout=WAIT_SECONDS, check_same_thread=False)
        for statement in self.pragma_statements:
            reader.execute(statement)
        return reader

    def start_journal(self) -> None:
        """Set the journal of the model's `pragmas`, which the file keeps."""
        if self._journal is not None:
            self.connection.execute(self._journal)

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


def _discard(connection: sqlite3.Connection, path: Path, readers: list[sqlite3.Connection]) -> None:
    for reader in readers:  # first: the last connection closed deletes the WAL journal
        reader.close()
    readers.clear()
    connection.close()
    # the WAL journal's files too, which the last connection closed deletes, unless it crashed
    for name in (path.name, f"{path.name}-wal", f"{path.name}-shm"):
        path.with_name(name).unlink(missing_ok=True)

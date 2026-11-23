"""A model keeping the app's data in SQLite databases (`DatabaseModel`).

The app writes its schema and its queries, in `SqliteTable` classes, which a
`SqliteDatabase` gathers. The database gives them a connection and runs each block of
work as one transaction. A `per_session` database is saved and opened with the study. It
works on a scratch copy in a temporary file: the user's study only changes when it's saved.
"""

from __future__ import annotations

import array
import atexit
import contextlib
import csv
import datetime
import decimal
import functools
import gzip
import io
import itertools
import json
import logging
import math
import operator
import os
import re
import sqlite3
import tempfile
import threading
import time
import weakref
from pathlib import Path
from types import MappingProxyType
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    ClassVar,
    Generic,
    NamedTuple,
    Optional,
    TypeVar,
    Union,
    cast,
    get_args,
    overload,
)
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, build_opener, urlopen

import attrs
from typing_extensions import dataclass_transform, override

from composeui.core._files import partial_path, scratch_directory
from composeui.core._views.tables import ColumnKind, column_kind
from composeui.core.jobs import current_job
from composeui.core.model import InvalidStateError, Model, RefusedError
from composeui.core.shared import SharedData
from composeui.core.signal import Signal, SignalNoArgs
from composeui.core.view import CONVERTER, Filter, FilterOperator, Sort, SourceColumn

if TYPE_CHECKING:
    from collections.abc import Generator, Iterable, Iterator, Mapping, Sequence
    from http.client import HTTPMessage
    from typing import IO, NoReturn
    from urllib.request import Request

    from attrs import AttrsInstance
    from typing_extensions import TypeAlias, Unpack

    from composeui.core.jobs import Job, Jobs
    from composeui.core.view import MainView

    #: a query's parameters: by position, or by name
    Parameters: TypeAlias = Union[Sequence[Any], Mapping[str, Any]]

__all__ = [
    "AllowedUrls",
    "CSVSqliteTable",
    "DatabaseModel",
    "ReadOnlyDatabaseError",
    "SqliteDatabase",
    "SqliteSource",
    "SqliteTable",
    "as_parameters",
    "csv_field",
    "define_csv_row",
    "open_csv_url",
    "per_session",
    "shared",
    "table",
    "unique_name",
]

LOGGER = logging.getLogger("COMPOSEUI")

_T = TypeVar("_T")
SqliteTableT = TypeVar("SqliteTableT", bound="SqliteTable")
_DeclaredT = TypeVar("_DeclaredT")


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
    """A table of a `SqliteDatabase` (or a few related ones), with the queries the app needs.

    `create` is the SQL script that creates it, run in every new database. Its methods read
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

    def __init__(self, database: SqliteDatabase) -> None:
        # weak: the database owns its tables, and should go (with its file) once unused
        self._database = cast("SqliteDatabase", weakref.proxy(database))
        self.changed = SignalNoArgs()

    @contextlib.contextmanager
    def connection(self) -> Generator[sqlite3.Connection]:
        """Give the database's connection for one transaction; see `SqliteDatabase.connection`.

        Raises `RefusedError` when a constraint fails, the transaction rolled back.
        """
        try:
            with self._database.connection(changing=self) as db:
                yield db
        except sqlite3.IntegrityError as error:
            message = str(error)
            refusal = next((text for key, text in self.refusals.items() if key in message), message)
            raise RefusedError(refusal) from error

    @contextlib.contextmanager
    def reading(self) -> Generator[sqlite3.Connection]:
        """Give a connection reading the database alone; see `SqliteDatabase.reading`."""
        with self._database.reading() as db:
            yield db

    def fetch(self, cls: type[_T], sql: str, parameters: Parameters = ()) -> list[_T]:
        """Run the query `sql` and get its rows as `cls` instances (an `attrs` class)."""
        with self.connection() as db:
            return [CONVERTER.structure(dict(row), cls) for row in db.execute(sql, parameters)]

    def fetch_one(self, cls: type[_T], sql: str, parameters: Parameters = ()) -> _T | None:
        """Run the query `sql` and get its first row as a `cls` instance; None if none."""
        with self.connection() as db:
            row = db.execute(sql, parameters).fetchone()
        return None if row is None else CONVERTER.structure(dict(row), cls)

    def fetch_column(self, sql: str, parameters: Parameters = ()) -> list[Any]:
        """Run the query `sql` and get its rows' first column, e.g. a list of names."""
        with self.connection() as db:
            return [row[0] for row in db.execute(sql, parameters)]

    def insert_batches(
        self,
        sql: str,
        rows: Iterable[Parameters],
        *,
        db: sqlite3.Connection | None = None,
        batch_size: int = 100_000,
        limit: int | None = None,
    ) -> Generator[int]:
        """Insert rows in batches and yield the cumulative number of rows submitted.

        Rows are positional or named SQL parameters. Read at most ``limit`` rows, or all
        rows if None. ``batch_size`` must be positive; ``limit`` must be nonnegative.
        Counts describe submitted rows, not affected rows (e.g. with INSERT OR IGNORE).

        Exhaust the generator to commit, or use ``contextlib.closing`` to roll back when
        stopping early. All batches share one transaction. Inside ``connection()``, they
        join its transaction instead: the caller must raise to roll that transaction back.
        If ``db`` is supplied, use it without committing, rolling back or closing it.
        Pass a connection from ``connection()`` to keep the table's change notifications.
        """
        yield from self._insert_batches(
            lambda connection, batch: connection.executemany(sql, batch),
            rows,
            db=db,
            batch_size=batch_size,
            limit=limit,
        )

    def _insert_batches(
        self,
        insert: Callable[[sqlite3.Connection, list[Parameters]], object],
        rows: Iterable[Parameters],
        *,
        db: sqlite3.Connection | None = None,
        batch_size: int,
        limit: int | None,
    ) -> Generator[int]:
        """Insert rows as `insert_batches` does, each batch with `insert`."""
        if batch_size <= 0:
            msg = "batch_size must be positive"
            raise ValueError(msg)
        if limit is not None and limit < 0:
            msg = "limit must be nonnegative"
            raise ValueError(msg)
        iterator = iter(rows)
        count = 0
        with self.connection() if db is None else contextlib.nullcontext(db) as connection:
            while limit is None or count < limit:
                size = batch_size if limit is None else min(batch_size, limit - count)
                batch = list(itertools.islice(iterator, size))
                if not batch:
                    break
                insert(connection, batch)
                count += len(batch)
                yield count


@overload
def csv_field(
    name: str,
    *,
    date_format: str,
    default: Any = attrs.NOTHING,
    factory: Optional[Callable[[], Any]] = None,
    converter: Any = None,
    init: bool = True,
    alias: Optional[str] = None,
    kw_only: bool = False,
    **kwargs: Any,
) -> datetime.datetime: ...


@overload
def csv_field(
    name: str,
    *,
    date_format: None = None,
    default: Any = attrs.NOTHING,
    factory: Optional[Callable[[], Any]] = None,
    converter: Any = None,
    init: bool = True,
    alias: Optional[str] = None,
    kw_only: bool = False,
    **kwargs: Any,
) -> Any: ...


def csv_field(name: str, *, date_format: str | None = None, **kwargs: Any) -> Any:
    """Declare a CSV field, with an optional strptime format for a date or datetime."""
    if date_format is not None and kwargs.get("converter") is not None:
        msg = "Use either date_format or converter, not both"
        raise TypeError(msg)
    metadata = dict(kwargs.pop("metadata", {}))
    metadata["csv_name"] = name
    if date_format is not None:
        metadata["csv_date_format"] = date_format
    return attrs.field(metadata=metadata, **kwargs)


_RowClassT = TypeVar("_RowClassT", bound=type)


@dataclass_transform(field_specifiers=(attrs.field, csv_field))
def define_csv_row(cls: _RowClassT) -> _RowClassT:
    """Define an attrs row class with typed CSV field specifiers.

    Use ``@define_csv_row`` instead of ``@attrs.define`` when fields use `csv_field`.
    For mypy, enable the ``composeui.mypy`` plugin.
    """
    return attrs.define(cls)


#: the parameters of one statement of `CSVSqliteTable`'s import, at most: SQLite's default
#: limit before its version 3.32, which a system's Python may still use
_PARAMETERS_PER_INSERT = 999
#: the exact types whose values `_sql_value` gives back as they are
_STORED_AS_IS = frozenset({str, int, float, bool, bytes, type(None)})


def _dict_rows(reader: csv.DictReader[str]) -> Generator[dict[Any, Any]]:
    """Get the rows of `reader` as iterating over it does, without its Python call per row."""
    names = reader.fieldnames
    if names is None:
        return
    nb_names = len(names)
    for cells in reader.reader:
        if len(cells) == 0:  # a blank line is no row
            continue
        row: dict[Any, Any] = dict(zip(names, cells))
        if len(cells) > nb_names:
            row[reader.restkey] = cells[nb_names:]
        elif len(cells) < nb_names:
            row.update(dict.fromkeys(names[len(cells) :], reader.restval))
        yield row


@functools.lru_cache(maxsize=65536)
def _parsed_date(value: Any, date_format: str) -> datetime.datetime:
    """Parse a CSV date: a file often repeats one, and `strptime` is the import's slowest part.

    `fill` empties the cache at its end, so that it holds no memory between two imports. It
    holds a month of dates to the minute, as a file may go through its dates several times.
    """
    return datetime.datetime.strptime(value, date_format)  # noqa: DTZ007 (preserve CSV timezone semantics)


@functools.lru_cache(maxsize=65536)
def _naive_date_text(value: datetime.datetime) -> str:
    return value.isoformat()


def _csv_cell(cell: Any) -> Any:
    """Get a CSV cell as SQLite stores it, a date repeated in the file from the cache."""
    # naive only: two aware dates of the same instant are equal, but their texts differ
    if type(cell) is datetime.datetime and cell.tzinfo is None:
        return _naive_date_text(cell)
    return _sql_value(cell)


def _csv_structure_hook(field: attrs.Attribute[Any]) -> Callable[[Any, Any], Any] | None:
    date_format = field.metadata.get("csv_date_format")
    if date_format is None:
        return None if field.converter is not None else CONVERTER.get_structure_hook(field.type)
    args = get_args(field.type)
    non_null = tuple(arg for arg in args if arg is not type(None))
    nullable = len(non_null) == 1 and type(None) in args
    field_type = non_null[0] if nullable else field.type
    if field_type not in (datetime.date, datetime.datetime):
        msg = f"date_format requires a date or datetime field: {field.name}"
        raise TypeError(msg)

    def structure(value: Any, _type: Any) -> datetime.date | None:
        # first: a CSV's cell is text, and this runs for each of them
        if type(value) is str:
            parsed = _parsed_date(value, date_format)
        elif value is None:  # `row_parameters` refuses it for a required field
            return None
        # a frame's date, already in the field's type (see `_typed_value`)
        elif isinstance(value, datetime.date):
            return value
        else:
            parsed = _parsed_date(value, date_format)
        return parsed.date() if field_type is datetime.date else parsed

    return structure


def _typed_value(value: Any, value_type: Any, header: str) -> Any:
    """Get `value` in the type of its field when nothing is lost; refuse it else."""
    if isinstance(value, float) and math.isnan(value):
        return None
    if value_type is int and isinstance(value, float):
        if not value.is_integer():
            msg = f"{header} takes a whole number, not {value}"
            raise RefusedError(msg)
        return int(value)
    if value_type is datetime.date and isinstance(value, datetime.datetime):
        if value.time() != datetime.time():
            msg = f"{header} takes a date, not {value}"
            raise RefusedError(msg)
        return value.date()
    if value_type is datetime.datetime and type(value) is datetime.date:
        return datetime.datetime.combine(value, datetime.time())
    return value


class _CSVField(NamedTuple):
    header: str
    alias: str
    field_type: Any
    structure: Callable[[Any, Any], Any] | None
    #: whether None is refused: converted, it would read as a value, such as the text "None"
    is_required: bool
    #: the field's type without its Optional
    value_type: Any


@contextlib.contextmanager
def _csv_text(binary: io.BufferedIOBase, *, encoding: str) -> Generator[io.TextIOWrapper]:
    """Decode a binary CSV stream, detect gzip, and close its wrappers on exit."""
    with contextlib.ExitStack() as stack:
        buffer = stack.enter_context(io.BufferedReader(binary))
        stream = (
            stack.enter_context(gzip.GzipFile(fileobj=buffer, mode="rb"))
            if buffer.peek(2).startswith(b"\x1f\x8b")
            else buffer
        )
        text = stack.enter_context(io.TextIOWrapper(stream, encoding=encoding, newline=""))
        yield text


def _replay_csv_sample(sample: str, text: io.TextIOWrapper) -> Generator[str]:
    with io.StringIO(sample, newline="") as prefix:
        for line in prefix:
            # A sample can end inside a physical line, including a quoted field.
            yield line if line.endswith(("\r", "\n")) else line + text.readline()
    yield from text


def _names(names: Iterable[str]) -> frozenset[str]:
    return frozenset(names)


def _ports(ports: Iterable[int]) -> frozenset[int]:
    return frozenset(ports)


#: the port of each scheme that `AllowedUrls` takes
_DEFAULT_PORTS: Mapping[str, int] = MappingProxyType({"http": 80, "https": 443})


@attrs.frozen
class AllowedUrls:
    """The URLs that an import takes from a user: the app's hosts, and never a local file."""

    #: the host names allowed, compared without case, such as ``{"data.example.org"}``
    hosts: frozenset[str] = attrs.field(converter=_names)
    #: the schemes allowed, among ``http`` and ``https``
    schemes: frozenset[str] = attrs.field(default=frozenset({"https"}), converter=_names)
    #: the ports allowed beside the scheme's own, 80 for ``http`` and 443 for ``https``: a host
    #: often serves more on its other ports, to the server that an import runs on
    ports: frozenset[int] = attrs.field(default=frozenset(), converter=_ports)
    #: whether to follow a redirect to an allowed URL; a redirect elsewhere is always refused
    follows_redirects: bool = False

    def check(self, url: str) -> None:
        """Raise `RefusedError` unless `url` is allowed."""
        try:
            parts = urlsplit(url)
            host = parts.hostname
            port = parts.port
        except ValueError as error:
            msg = f"This address isn't valid: {url!r}"
            raise RefusedError(msg) from error
        allowed_hosts = {name.casefold() for name in self.hosts}
        if (
            parts.scheme not in self.schemes - {"file"}
            or host is None
            or host.casefold() not in allowed_hosts
            or port not in {None, _DEFAULT_PORTS.get(parts.scheme), *self.ports}
            # read in another way by some URL parsers, on either side of the host
            or "\\" in url
            or parts.username is not None
        ):
            msg = f"This address isn't allowed: {url!r}"
            raise RefusedError(msg)


class _CheckedRedirects(HTTPRedirectHandler):
    """Check each redirect's address before its request is sent."""

    def __init__(self, allowed: AllowedUrls) -> None:
        self._allowed = allowed

    @override
    def redirect_request(
        self,
        req: Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> Request | None:
        if not self._allowed.follows_redirects:
            refusal = f"This address redirects to another: {newurl!r}"
            raise RefusedError(refusal)
        self._allowed.check(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


@contextlib.contextmanager
def open_csv_url(
    url: str,
    *,
    encoding: str = "utf-8",
    timeout: float = 30.0,
    allowed: AllowedUrls | None = None,
) -> Generator[io.TextIOWrapper]:
    """Open an HTTP, HTTPS or file URL as CSV text, and close its streams on exit.

    Detect gzip by its content, not its filename. Preserve CSV newlines and decode with
    ``encoding``. ``timeout`` sets the socket timeout in seconds, not a total download
    deadline. Network, decompression and decoding errors propagate to the caller.

    Give a URL from a user only with ``allowed``, which raises `RefusedError` for a URL or a
    redirect outside it, before its request. Without it, the URL is trusted: any host, any
    redirect, and local files.
    """
    # first: a URL from a user gets the refusal that the app expects, whatever its form
    if allowed is not None:
        allowed.check(url)
    if urlsplit(url).scheme not in {"http", "https", "file"}:
        msg = "CSV URLs must use http, https or file"
        raise ValueError(msg)
    if allowed is None:
        opened = urlopen(url, timeout=timeout)  # noqa: S310 (schemes checked above; trusted URLs only)
    else:
        opened = build_opener(_CheckedRedirects(allowed)).open(url, timeout=timeout)
    with opened as response, _csv_text(response, encoding=encoding) as text:
        yield text


class CSVSqliteTable(SqliteTable):
    """A CSV table whose schema comes from an attrs row class.

    The class builds `create` from the row class: set `indexes` to add to it, not `create`.
    """

    row_type: ClassVar[type[AttrsInstance]]
    name: ClassVar[str]
    insert: ClassVar[str] = ""
    #: the SQL script that creates the table's indexes, run after the ``CREATE TABLE``
    indexes: ClassVar[str] = ""
    _create_table: ClassVar[str] = ""
    _column_names: ClassVar[tuple[str, ...]]
    _read_cells: ClassVar[operator.attrgetter[tuple[Any, ...]]]
    _csv_fields: ClassVar[tuple[_CSVField, ...]]
    _rows_per_insert: ClassVar[int]

    @override
    def __init_subclass__(
        cls, *, row_type: type[AttrsInstance] | None = None, name: str | None = None, **kwargs: Any
    ) -> None:
        super().__init_subclass__(**kwargs)
        if row_type is None and name is None:
            if "indexes" in vars(cls):
                cls.create = cls._create_table + cls.indexes
            return
        if row_type is None or not name:
            msg = "CSVSqliteTable requires an attrs row_type and a table name"
            raise TypeError(msg)
        attrs.resolve_types(row_type)
        fields = attrs.fields(row_type)
        if not fields:
            msg = "CSV row classes must have at least one field"
            raise TypeError(msg)
        sql_types = {
            str: "TEXT",
            int: "INTEGER",
            bool: "INTEGER",
            float: "REAL",
            bytes: "BLOB",
            datetime.date: "DATE",
            datetime.datetime: "TIMESTAMP",
            decimal.Decimal: "REAL",
        }
        columns = []
        for field in fields:
            args = get_args(field.type)
            non_null = tuple(arg for arg in args if arg is not type(None))
            nullable = len(non_null) == 1 and type(None) in args
            field_type = non_null[0] if nullable else field.type
            if field_type not in sql_types:
                msg = f"Unsupported CSV field type for {field.name}: {field.type}"
                raise TypeError(msg)
            constraint = "" if nullable else " NOT NULL"
            columns.append(f"{_identifier(field.name)} {sql_types[field_type]}{constraint}")
        cls.row_type = row_type
        cls.name = name
        cls._column_names = tuple(field.name for field in fields)
        # the first name twice: `attrgetter` gives a tuple only for several names
        cls._read_cells = operator.attrgetter(*cls._column_names, cls._column_names[0])
        cls._csv_fields = tuple(
            _CSVField(
                header=field.metadata.get("csv_name", field.name),
                alias=field.alias,
                field_type=field.type,
                structure=_csv_structure_hook(field),
                is_required=field.converter is None and type(None) not in get_args(field.type),
                value_type=next(
                    (arg for arg in get_args(field.type) if arg is not type(None)), field.type
                ),
            )
            for field in fields
            if field.init
        )
        cls._create_table = f"CREATE TABLE {_identifier(name)} ({', '.join(columns)});"
        cls.create = cls._create_table + cls.indexes
        names = ", ".join(_identifier(field.name) for field in fields)
        placeholders = ", ".join("?" for _ in fields)
        cls.insert = f"INSERT INTO {_identifier(name)} ({names}) VALUES ({placeholders})"  # noqa: S608 (quoted identifiers)
        cls._rows_per_insert = max(1, _PARAMETERS_PER_INSERT // len(fields))

    def source(self, *, headers: Mapping[str, str] | None = None) -> SqliteSource:
        """Build a source with schema-derived types and SQLite row ids.

        By default, show every field under its CSV header (or its field name).
        ``headers`` selects, orders and labels the fields to show. Raises `KeyError`
        for an unknown field, or `ValueError` if fields shadow all SQLite row-id names.
        Use `SqliteSource` directly for custom queries or explicit primary keys.
        """
        fields = attrs.fields_dict(self.row_type)
        if headers is None:
            headers = {
                field.name: field.metadata.get("csv_name", field.name) for field in fields.values()
            }
        columns = [
            SourceColumn(name, header, fields[name].type) for name, header in headers.items()
        ]
        names = {name.casefold() for name in fields}
        row_id = next((name for name in ("rowid", "_rowid_", "oid") if name not in names), None)
        if row_id is None:
            msg = "CSV fields shadow all SQLite row-id names; use SqliteSource with an explicit key"
            raise ValueError(msg)
        # SQLite otherwise names every hidden row-id expression "rowid".
        identifier = _identifier(row_id)
        query = f"SELECT {identifier} AS {identifier}, * FROM {_identifier(self.name)}"  # noqa: S608 (quoted identifiers)
        return SqliteSource(self, query, id_column=row_id, columns=columns)

    def row_parameters(self, row: dict[str, Any]) -> Parameters:
        """Convert CSV fields through the row class and return SQL parameters."""
        values = {}
        try:
            # unpacked, and no call for a value SQLite stores as it is: this runs for each row
            for header, alias, field_type, structure, is_required, _ in self._csv_fields:
                if header in row:
                    value = row[header]
                    if value is None and is_required:
                        msg = f"The row has no value for {header}"
                        raise RefusedError(msg)
                    values[alias] = value if structure is None else structure(value, field_type)
            instance = self.row_type(**values)
        except (ValueError, TypeError) as error:
            raise RefusedError(str(error)) from error
        return tuple(
            [
                cell if type(cell) in _STORED_AS_IS else _csv_cell(cell)
                for cell in self._read_cells(instance)[:-1]
            ]
        )

    def fill(
        self,
        text: Iterable[str],
        *,
        batch_size: int = 100_000,
        limit: int | None = None,
        **csv_options: Any,
    ) -> Generator[int]:
        """Import CSV text and yield cumulative row counts.

        Pass an open text file (with ``newline=''``) or another iterable of lines.
        The caller owns and closes it. Extra keywords go to ``csv.DictReader``,
        for example ``delimiter=';'`` or ``fieldnames=['name', 'value']``.
        Exhaust the generator to commit. Use ``contextlib.closing`` when stopping
        early to roll back rows. Nested transactions follow
        `SqliteTable.insert_batches`'s rules.
        """
        reader = csv.DictReader(text, **csv_options)
        # not `fill_rows`: a CSV's cells are text, and this runs for each of them
        rows = (self.row_parameters(row) for row in _dict_rows(reader))
        yield from self._insert_rows(rows, batch_size=batch_size, limit=limit)

    def fill_rows(
        self,
        rows: Iterable[dict[str, Any]],
        *,
        batch_size: int = 100_000,
        limit: int | None = None,
    ) -> Generator[int]:
        """Import rows, each a dictionary by CSV header, and yield cumulative row counts.

        The values go through the row class as a CSV's text does. A value may also have the
        field's own type, such as a date, or one that converts without a loss: a whole float
        for an int, a date at midnight for a date and time, or the reverse. NaN is None. Any
        other value raises `RefusedError`, as a float with a fraction does for an int.
        Transactions follow `fill`.
        """
        parameters = (self.row_parameters(self._typed_row(row)) for row in rows)
        yield from self._insert_rows(parameters, batch_size=batch_size, limit=limit)

    def _insert_rows(
        self, parameters: Iterable[Parameters], *, batch_size: int, limit: int | None
    ) -> Generator[int]:
        try:
            yield from self._insert_batches(
                self._insert_many, parameters, batch_size=batch_size, limit=limit
            )
        finally:
            _parsed_date.cache_clear()
            _naive_date_text.cache_clear()

    def _insert_many(self, connection: sqlite3.Connection, batch: list[Parameters]) -> None:
        """Insert `batch` with statements of many rows each.

        Not `executemany`: SQLite runs a step for each row of it, and Python's `sqlite3`
        gives the GIL away at each step. Imports in several threads at once then took 20
        times longer, the threads waiting for each other on every row.
        """
        size = self._rows_per_insert
        for start in range(0, len(batch), size):
            rows = batch[start : start + size]
            connection.execute(self._insert_of(len(rows)), list(itertools.chain(*rows)))

    def _insert_of(self, nb_rows: int) -> str:
        """Get the statement inserting `nb_rows` rows into the table."""
        row = "(" + ", ".join("?" for _ in self._column_names) + ")"
        head = self.insert[: self.insert.index(" VALUES ")]
        return f"{head} VALUES {', '.join([row] * nb_rows)}"

    def fill_from_file(  # noqa: PLR0913 (keep decoding, detection and import options explicit)
        self,
        path: str | os.PathLike[str],
        *,
        encoding: str = "utf-8",
        sniff: bool = False,
        sniff_sample_size: int = 8192,
        batch_size: int = 100_000,
        limit: int | None = None,
        **csv_options: Any,
    ) -> Generator[int]:
        """Import a plain or gzip CSV file and yield cumulative submitted-row counts.

        Accept a path string or path-like object, relative or absolute. Detect gzip
        from the content. Own and close the file; other options follow `fill`.
        Exhaust the generator to commit, or use ``contextlib.closing`` when stopping
        early to close the file and roll back. File and decoding errors propagate.
        Set ``sniff=True`` to detect the dialect from at most ``sniff_sample_size``
        decoded characters (8192 by default). The size must be positive when sniffing
        and is ignored otherwise.
        Explicit CSV options override detection. Detection failure raises `RefusedError`.
        """
        with (
            Path(path).open("rb") as binary,
            _csv_text(binary, encoding=encoding) as text,
            contextlib.closing(
                self._fill_stream(
                    text,
                    sniff=sniff,
                    sniff_sample_size=sniff_sample_size,
                    batch_size=batch_size,
                    limit=limit,
                    **csv_options,
                )
            ) as batches,
        ):
            yield from batches

    def fill_from_url(  # noqa: PLR0913 (keep transport, detection and import options explicit)
        self,
        url: str,
        *,
        encoding: str = "utf-8",
        timeout: float = 30.0,
        allowed: AllowedUrls | None = None,
        sniff: bool = False,
        sniff_sample_size: int = 8192,
        batch_size: int = 100_000,
        limit: int | None = None,
        **csv_options: Any,
    ) -> Generator[int]:
        """Import CSV from a URL and yield cumulative submitted-row counts.

        `open_csv_url` handles decoding, gzip and stream cleanup, and ``allowed``, which a
        URL from a user needs. Other options follow `fill`. Exhaust the generator to commit;
        use ``contextlib.closing`` if iteration can stop early, to close the streams and roll
        back. Existing rows are retained.
        ``sniff=True`` detects the dialect as in `fill_from_file`, without seeking.
        ``sniff_sample_size`` sets its limit in decoded characters (8192 by default).
        """
        with (
            open_csv_url(url, encoding=encoding, timeout=timeout, allowed=allowed) as text,
            contextlib.closing(
                self._fill_stream(
                    text,
                    sniff=sniff,
                    sniff_sample_size=sniff_sample_size,
                    batch_size=batch_size,
                    limit=limit,
                    **csv_options,
                )
            ) as batches,
        ):
            yield from batches

    def _typed_row(self, row: dict[str, Any]) -> dict[str, Any]:
        """Convert a row's values for their fields; the converters would read them as text."""
        typed = dict(row)
        for csv_field_ in self._csv_fields:
            if csv_field_.header in typed:
                typed[csv_field_.header] = _typed_value(
                    typed[csv_field_.header], csv_field_.value_type, csv_field_.header
                )
        return typed

    def _fill_stream(
        self,
        text: io.TextIOWrapper,
        *,
        sniff: bool,
        sniff_sample_size: int,
        batch_size: int,
        limit: int | None,
        **csv_options: Any,
    ) -> Generator[int]:
        lines: Iterable[str] = text
        if sniff:
            if sniff_sample_size <= 0:
                msg = "sniff_sample_size must be positive"
                raise ValueError(msg)
            sample = text.read(sniff_sample_size)
            try:
                dialect = csv.Sniffer().sniff(sample)
            except csv.Error as error:
                msg = (
                    "Cannot detect the CSV dialect; increase sniff_sample_size or disable sniff"
                    " and supply explicit CSV options"
                )
                raise RefusedError(msg) from error
            csv_options = {"dialect": dialect, **csv_options}
            lines = _replay_csv_sample(sample, text)
        yield from self.fill(lines, batch_size=batch_size, limit=limit, **csv_options)


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


#: the ids read from SQLite at a time, as Python objects
ID_BATCH = 10_000
#: the ids a source reads in one JSON text at most: about 4 MiB of Python objects at once
ONE_TEXT_IDS = 100_000
#: whether SQLite orders an aggregate's values (``json_group_array(id ORDER BY ...)``)
_ORDERS_AGGREGATES = sqlite3.sqlite_version_info >= (3, 44, 0)
#: SQLite's instructions that the check of empty cells may take before the sort gives up on
#: it: the check of an indexed column takes a few, one computing an app's GROUP BY millions
EMPTY_CHECK_BUDGET = 100_000


def _has_no_empty_cell(db: sqlite3.Connection, check: str) -> bool:
    """Tell whether the query `check` finds no empty cell, within `EMPTY_CHECK_BUDGET`.

    Over the budget (e.g. a query SQLite computes again for the check), say False: the
    sort then reads the empty cells apart, as without the check.
    """
    stopped = False

    def stop() -> bool:
        nonlocal stopped
        stopped = True
        return True  # stops the statement; the read transaction goes on

    db.set_progress_handler(stop, EMPTY_CHECK_BUDGET)
    try:
        return db.execute(check).fetchall() == [(0,)]
    except sqlite3.OperationalError:
        # an error not the budget's (e.g. the app's query fails) comes again in the sort's
        # queries, which read the same query: no test tells which one raised it
        if not stopped:  # pragma: no cover
            raise
        return False
    finally:
        db.set_progress_handler(None, 0)


def _numbered_ids(
    db: sqlite3.Connection, ordered: str, parameters: list[Any], count: int
) -> Iterator[list[Any]]:
    """Read the `count` ids of the query `ordered` in JSON texts of `ID_BATCH` ids.

    SQLite numbers them in a temporary table, in an index's order when the sort has one:
    a window's ``row_number()`` would take 3 times as long. Each insert takes the next
    number, in the order of the query's rows. The caller's transaction holds the table.
    """
    db.execute("CREATE TEMP TABLE composeui_ids (n INTEGER PRIMARY KEY, id)")
    try:
        db.execute(f"INSERT INTO temp.composeui_ids (id) {ordered}", parameters)
        for start in range(1, count + 1, ID_BATCH):
            ((text,),) = db.execute(
                "SELECT json_group_array(id ORDER BY n) FROM temp.composeui_ids"
                " WHERE n >= ? AND n < ?",
                (start, start + ID_BATCH),
            ).fetchall()
            yield json.loads(text)
    finally:
        db.execute("DROP TABLE temp.composeui_ids")


def _read_ids(batches: Iterable[list[Any]]) -> Sequence[Any]:
    """Keep the ids of `batches`, in turn: in an `array` while integers, else in a list."""
    ids: array.array[int] | list[Any] = array.array("q")
    for batch in batches:
        if isinstance(ids, array.array):
            size = len(ids)
            try:
                ids.extend(batch)
                continue
            except TypeError:  # e.g. a text id (SQLite's integers fit in 64 bits)
                ids = ids[:size].tolist()  # the batch's ids extended before it failed
        ids.extend(batch)
    return ids


def _regexp(pattern: str, value: Any) -> bool:
    """SQLite's ``REGEXP``: whether `pattern` is found in `value`'s text, ignoring case."""
    return _compiled(pattern).search("" if value is None else str(value)) is not None


class SqliteSource:
    """A `TableSource` of a query's rows, which a large table reads a window at a time.

    It takes the `SqliteTable` whose rows the query reads, the query itself, the column
    of the rows' ids (e.g. a primary key) and the query's columns that the table shows.
    SQLite sorts and filters the rows: the order is a ``SELECT`` of the ids, and the cells
    a ``SELECT`` of some ids' rows. So no more rows than those shown come to Python. The
    table's `changed` reads them again. Only the declared columns sort and filter, by name:
    SQLite takes no column name as a parameter, the values are. It reads on connections
    of its own (`SqliteDatabase.reading`): the rows committed, never waiting for a write, nor
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
            # read to the end: the connection is reused (see `SqliteDatabase.reading`)
            ((count,),) = db.execute(f"SELECT COUNT(*) FROM ({self._query})").fetchall()  # noqa: S608 (the app's query)
        return int(count)

    def ordered_ids(
        self, sort: Sort | None, search: str, filters: Mapping[str, Filter]
    ) -> Sequence[Any]:
        """Get the ids as `TableSource.ordered_ids` says: integer ids in an `array`.

        Read a batch at a time, never all as Python objects: 8 bytes an id, not 40.
        """
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
        # without filters: whether the column has an empty cell, else one query orders the rows
        empty_check: str | None = None
        plain: list[tuple[list[str], str]] = []
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
                # a cell found stops each EXISTS: a column with empty cells loses no time
                empty_check = (
                    f"SELECT EXISTS (SELECT 1 FROM ({self._query}) WHERE {name} IS NULL)"  # noqa: S608 (quoted, the app's query)
                    f" OR EXISTS (SELECT 1 FROM ({self._query}) WHERE {name} = '')"
                )
                plain = [([], f"{order}{direction}, {self._id}")]
        with self._table.reading() as db:
            db.create_function("regexp", 2, _regexp, deterministic=True)
            db.create_function("casefold", 1, _casefold, deterministic=True)
            db.execute("BEGIN")  # the queries read the same rows, a write committed between
            try:
                # no empty cell: no test of each cell, nor a scan of the table for the empty
                # ones (a third of the time to sort 10 million rows by an indexed number)
                if empty_check is not None and _has_no_empty_cell(db, empty_check):
                    queries = plain
                return _read_ids(
                    batch
                    for where, order_by in queries
                    for batch in self._id_batches(db, where, order_by, parameters)
                )
            finally:
                db.rollback()

    def _id_batches(
        self, db: sqlite3.Connection, conditions: list[str], order_by: str, parameters: list[Any]
    ) -> Iterator[list[Any]]:
        """Read the ids of the rows passing `conditions`, ordered by `order_by`, in batches.

        A row read gives the GIL to another thread, which another CPU must wake: sessions
        reading at once wait on each other at each row. So SQLite puts the ids in JSON texts,
        one row each, when it can order an aggregate's values: all in one text up to
        `ONE_TEXT_IDS`, else `ID_BATCH` a text, numbered in a temporary table. The read's
        transaction (`ordered_ids`) holds the count and the rows the same.
        """
        rows = f"FROM ({self._query})"
        if len(conditions) > 0:
            rows += " WHERE " + " AND ".join(conditions)
        ordered = f"SELECT {self._id} {rows} ORDER BY {order_by}"
        if _ORDERS_AGGREGATES:
            # JSON keeps integers and texts as they are, not a real's last digits, and takes
            # a blob for JSON of its own: other ids are read row by row
            count, has_other = db.execute(
                f"SELECT count(*), max(typeof({self._id}) NOT IN ('integer', 'text', 'null'))"
                f" {rows}",
                parameters,
            ).fetchone()
            if not has_other:  # None without rows
                if count <= ONE_TEXT_IDS:
                    # SQLite sorts the values itself, not in an index's order: fine for few
                    sql = f"SELECT json_group_array({self._id} ORDER BY {order_by}) {rows}"
                    ((text,),) = db.execute(sql, parameters).fetchall()
                    yield json.loads(text)
                else:
                    yield from _numbered_ids(db, ordered, parameters, count)
                return
        cursor = db.execute(ordered, parameters)
        while batch_rows := cursor.fetchmany(ID_BATCH):
            yield [row[0] for row in batch_rows]

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
    """A table a `SqliteDatabase` class declares, which each database builds (see `table`)."""

    def __init__(self, table_type: type[SqliteTableT]) -> None:
        self.table_type = table_type


def table(table_type: type[SqliteTableT]) -> SqliteTableT:
    """Declare a table of a `SqliteDatabase`, in the database's class.

    E.g. ``runs = table(Runs)``. Each database builds its own table, as an attribute of the
    same name, before it creates its file. The tables are built in the order the classes
    declare them, a base class's first.
    """
    # the database's attribute is the table: typed as one, as `attrs.Factory` is
    return cast("SqliteTableT", _DeclaredTable(table_type))


def _declared(cls: type, kind: type[_DeclaredT]) -> dict[str, _DeclaredT]:
    """Get the attributes of `kind` that `cls` and its bases declare, a base class's first."""
    declared: dict[str, _DeclaredT] = {}
    for base in reversed(cls.__mro__):
        declared.update(
            (name, value) for name, value in vars(base).items() if isinstance(value, kind)
        )
    return declared


class SqliteDatabase:
    """A SQLite database: its tables, their version, and the migrations between versions.

    Declare the tables in the class, ``runs = table(Runs)``, for the callbacks to reach
    (``model.study.runs.add(...)``), or add them in `__init__` with `add_table`. A new
    database is created from the tables' `create` scripts at `schema_version`. When a
    database saved at an older version is opened, `migrations` bring it up to date.

    It isn't a model: a `DatabaseModel` declares it, e.g. ``study = per_session(Study)`` for
    a database of each session, saved in the study, or ``crm = shared(Crm)`` for one that
    every session reads and writes.
    """

    #: the tables' version, kept in the database (``PRAGMA user_version``); raise it with
    #: every change to the tables, adding the migration from the previous one
    schema_version: ClassVar[int] = 1
    #: by version: the function bringing a database at that version to the next one
    migrations: ClassVar[Mapping[int, Callable[[sqlite3.Connection], None]]] = {}
    #: seconds opening a study's database may take, checks and migrations included: its
    #: schema comes from the file, and a view of it may never finish (e.g. a recursive one)
    open_time_limit: ClassVar[float] = 30.0
    #: set on the connections of every database file: SQLite keeps these per connection,
    #: not in the file, and New and Open each start a connection of their own
    pragmas: ClassVar[Mapping[str, int | str]] = MappingProxyType(
        {
            # the connections `reading` read during a write, its rows uncommitted (else a
            # write spilling to the disk locks them out until it commits); the study file
            # is saved in the default journal (`_Engine.save`)
            "journal_mode": "WAL",
            "foreign_keys": "ON",
            # the database is a scratch copy nothing reopens after a crash: waiting for the
            # disk on every commit protects nothing, the study file is written apart. A
            # shared database kept in a file of its own waits for it (`NORMAL`)
            "synchronous": "OFF",
            # a row replaced (`INSERT OR REPLACE`) fires its delete triggers, and a trigger
            # may fire itself, so triggers keeping other tables up to date see every change
            "recursive_triggers": "ON",
        }
    )

    def __init__(self) -> None:
        self._tables: list[SqliteTable] = []
        for name, declared_table in _declared(type(self), _DeclaredTable).items():
            # before the file, which the engine creates with them
            built = declared_table.table_type(self)
            self._tables.append(built)
            setattr(self, name, built)
        # its model gives it one once it's built: a session's copy, or a shared one
        self._engine: _Engine | _Handle | None = None

    @property
    def _signals(self) -> list[Signal[Unpack[tuple[Any, ...]]]]:
        """Get its tables' signals (`SqliteTable.changed` among them)."""
        tables = [vars(table).values() for table in self._tables]
        return [value for values in tables for value in values if isinstance(value, Signal)]

    def _started(self) -> _Engine | _Handle:
        engine = self._engine
        assert engine is not None, "its model gives it an engine as it builds it"
        return engine

    def add_table(self, table_type: type[SqliteTableT]) -> SqliteTableT:
        """Add a table, created in the current file too, and return it.

        In `__init__` alone for a `shared` database: each session's copy adds it, but the
        file is created once.
        """
        table = table_type(self)
        if self._engine is not None:  # else created with the others once it's built
            self._engine.add_table(table)
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
        refreshes are. For a `shared` database, it is emitted in the other sessions too,
        each on its own main thread.

        The threads take turns, those of every session for a `shared` database. A `shared`
        database opened `read_only` reads here as `reading` does, and refuses a write
        (`ReadOnlyDatabaseError`).
        """
        with self._started().connection(changing=changing) as db:
            yield db

    @contextlib.contextmanager
    def reading(self) -> Generator[sqlite3.Connection]:
        """Give a connection that only reads the database, for a long query.

        Unlike `connection()`, it waits for no other thread's turn, and holds none. The
        database's other queries run meanwhile, e.g. a large table's cells while a job
        orders its rows or writes some (`SqliteSource`). In the WAL journal, it reads the
        rows committed, during a write too. A file New or Open replace meanwhile, or the
        model's `close`, is deleted once the query is over. Once the model is closed,
        raises `sqlite3.ProgrammingError`, as `connection()` does: e.g. a web download
        its session's end cuts short.

        The connection is reused, e.g. for the next window of a large table: read each
        query's rows to the end in the block. A query left half read keeps the rows as
        they were when it started, for the next reader too.
        """
        with self._started().reading() as db:
            yield db

    def fill(self, job: Job[None, Any]) -> None:
        """Fill a `shared` database once, as it's created: override it to write its rows.

        It runs in a thread of its own, before any session can use the database, and the
        sessions' `ready` wait for it. `job` reports its progress to them, and is canceled
        once no session waits: stop then, e.g. with `job.raise_if_canceled()`. A fill
        that fails or stops leaves no file, and the next `ready` fills again. Never
        called for a `per_session` database.
        """

    def ready(self, job: Job[Any, Any]) -> None:
        """Wait, in `job`'s thread, until the database can be used: its `fill` is done.

        The first session runs `fill`, and the others wait for it, its progress reported
        to their jobs. Raises `JobCanceledError` once `job` is canceled. Returns at once
        for a database without `fill`, or a `per_session` one. A `shared` database with
        `fill` refuses any query until its session's `ready` has returned.
        """
        self._started().ready(job)

    def forget(self) -> None:
        """Have the next sessions start a new copy of a `shared` database, filled again.

        The sessions that have it keep theirs, which is deleted once the last one is done
        with it. Refused for a `per_session` database, which New replaces, and for a
        database kept in a file (`location`).
        """
        self._started().forget()


class ReadOnlyDatabaseError(sqlite3.OperationalError):
    """A write refused by a database shared `read_only`, which its sessions only read."""


def _emit(changed: list[SqliteTable]) -> None:
    """Emit the tables' `changed`, on the main thread if this is a job's."""
    job = current_job()
    for table in changed:
        if job is None:
            table.changed.emit()
        else:
            job.call_on_main_thread(table.changed.emit)


class _Engine:
    """A database file's connections, which threads take in turn, and its life.

    A `per_session` database's engine is its own, which New and Open give a new file. A
    `shared` database's file has one engine for every session (`_Generation`).
    """

    def __init__(
        self,
        owner: SqliteDatabase,
        pragmas: Mapping[str, int | str],
        database: _Database | None = None,
        *,
        path: Path | None = None,
        shared: bool = False,
    ) -> None:
        # weak: the database owns its engine
        self._owner = cast("SqliteDatabase", weakref.proxy(owner))
        self._pragmas = pragmas
        #: a shared file's engine: a job New drops still writes in it, and it emits no
        #: `changed`, which each session's handle emits instead (`_Handle`)
        self._shared = shared
        # one connection for the file, which threads (a worker, web requests) take in turn
        self._lock = threading.RLock()
        # which file the queries `reading` read, and how many: held for no query, so a
        # read never waits for the turn a write holds
        self._readers_lock = threading.Lock()
        self._closed = False
        #: the turns held, which keep the connection open once the engine is closed
        self._turns = 0
        self._depth = 0
        self._changed: list[SqliteTable] = []
        #: the transactions committed that changed rows (`_data_revision`), and those of them
        #: not made by a job started with the study (`data_version`)
        self.writes = 0
        self.user_writes = 0
        self._database = self._new_database(path) if database is None else database

    def add_table(self, table: SqliteTable) -> None:
        with self._turn() as db:
            db.executescript(table.create)

    @contextlib.contextmanager
    def _turn(self) -> Generator[sqlite3.Connection]:
        """Hold the turn on the file's connection, which `close` leaves open until its end.

        Closing a connection during another thread's statement crashes the process.
        """
        with self._lock:
            job = current_job()
            if not self._shared and job is not None and job.is_dropped:  # study replaced
                msg = "A job dropped by a new study can't use the database."
                raise RefusedError(msg)
            database = self._database
            if database.acquire():
                # released last: Python's exit waits for a close that the turn's end makes
                try:
                    with self._readers_lock:
                        if self._closed:
                            msg = "Cannot operate on a closed database."
                            raise sqlite3.ProgrammingError(msg)
                        self._turns += 1
                    try:
                        yield database.connection
                    finally:
                        with self._readers_lock:
                            self._turns -= 1
                            self._close_if_unused(self._database)
                finally:
                    database.release()
                return
        # out of the turn's lock: a job's thread that waits there would block the main thread
        _refuse_at_exit()

    def _close_if_unused(self, database: _Database) -> None:
        """Close a replaced file, or a closed engine's, once unused; hold the readers' lock."""
        is_over = database is not self._database or (self._closed and self._turns == 0)
        if is_over and database.readers == 0:
            database.close()

    @contextlib.contextmanager
    def connection(
        self,
        *,
        changing: SqliteTable | None = None,
        on_commit: Callable[[list[SqliteTable]], None] | None = None,
    ) -> Generator[sqlite3.Connection]:
        """Give the connection for one transaction; see `SqliteDatabase.connection`.

        `on_commit` gets the tables whose `changed` the commit emits, once the turn is over.
        Without it, a session's own database emits them, and a shared file's engine none:
        its `fill`'s, which no session sees yet.
        """
        changed: list[SqliteTable] = []
        with self._turn() as db:
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
                    if db.total_changes != before:
                        self.writes += 1
                        job = current_job()
                        if job is None or not job._is_the_study_s:  # noqa: SLF001
                            self.user_writes += 1
            except BaseException:
                if outermost:
                    db.rollback()
                    self._changed = []
                raise
            finally:
                self._depth -= 1
        # outside the lock: a view refreshing may query another thread's way
        if on_commit is not None:
            on_commit(changed)
        elif not self._shared:
            _emit(changed)

    @contextlib.contextmanager
    def reading(self) -> Generator[sqlite3.Connection]:
        """Give a connection that only reads; see `SqliteDatabase.reading`."""
        database, db = self._take_reader()
        try:
            if db is None:
                db = database.open_reader()
            yield db
        finally:
            self._give_back_reader(database, db)

    def _take_reader(self) -> tuple[_Database, sqlite3.Connection | None]:
        """Count a reader of the file, and take an idle connection, if any."""
        db = None
        with self._readers_lock:
            if self._closed:  # its file is gone
                msg = "Cannot operate on a closed database."
                raise sqlite3.ProgrammingError(msg)
            database = self._database
            is_taken = database.acquire()
            if is_taken:
                database.readers += 1
                db = database.idle_readers.pop() if len(database.idle_readers) > 0 else None
        if not is_taken:  # out of the readers' lock, as a turn's refusal
            _refuse_at_exit()
        return database, db

    def _give_back_reader(self, database: _Database, db: sqlite3.Connection | None) -> None:
        try:
            with self._readers_lock:
                database.readers -= 1
                if db is not None:
                    database.idle_readers.append(db)
                self._close_if_unused(database)
        finally:
            # released last: Python's exit waits for a close that the reader's end makes
            database.release()

    def ready(self, job: Job[Any, Any]) -> None:
        """Return: a session's own database needs no fill."""

    def forget(self) -> None:
        msg = "A per_session database forgets nothing: New gives the session a new one"
        raise TypeError(msg)

    def pin(self) -> _PinnedDatabase:
        """Pin the committed rows of now: a reader's transaction, which a copy reads later.

        Another thread copies them while the app goes on writing. Counted as a reader, so a
        file New or Open replace stays open until the copy is released.
        """
        database, db = self._take_reader()
        try:
            if db is None:
                db = database.open_reader()
            # a read starts the transaction's snapshot in the WAL journal, not `BEGIN`
            db.execute("BEGIN")
            db.execute("SELECT count(*) FROM sqlite_master").fetchone()
        except BaseException:  # pragma: no cover (a read of the database's own scratch file)
            if db is not None and db.in_transaction:
                db.rollback()
            self._give_back_reader(database, db)
            raise
        return _PinnedDatabase(self, database, db)

    def new(self) -> None:
        self._replace_database(self._new_database())

    def save(self, path: Path) -> None:
        target = sqlite3.connect(str(path))
        try:
            with self._turn() as db:
                db.backup(target)
            # the backup copies the WAL journal: a file another app opens leaves none beside it
            target.execute("PRAGMA journal_mode = DELETE")
        finally:
            target.close()

    def open_study(self, path: Path) -> None:
        """Open a study's database, refused unless it is made as a new one is.

        The file may come from anyone (e.g. a web upload): its schema is the file's own,
        whose views and triggers would run in the app. Until it is checked, its views and
        triggers may call no function with side effects (`trusted_schema`), and the whole
        open is cut after `open_time_limit`.
        """
        database = _Database(self._pragmas)
        db = database.connection
        try:
            source = sqlite3.connect(str(path))
            try:
                source.backup(db)
            finally:
                source.close()
            database.start_journal()  # after the backup: it keeps the file's page size
            db.execute("PRAGMA trusted_schema = OFF")
            deadline = time.monotonic() + self._owner.open_time_limit
            # a true answer interrupts the statement running (`OperationalError`)
            db.set_progress_handler(lambda: time.monotonic() > deadline, 10_000)
            try:
                self._check(db)
                self._upgrade(db)
                self._check_schema(db)
            finally:
                db.set_progress_handler(None, 0)
            db.execute(
                _pragma_statement("trusted_schema", self._pragmas.get("trusted_schema", "ON"))
            )
        except sqlite3.DatabaseError as error:
            database.close()
            msg = "its data isn't a valid database"
            raise InvalidStateError(msg) from error
        except BaseException:
            database.close()
            raise
        self._replace_database(database)

    def open_kept(self, *, read_only: bool) -> None:
        """Bring the file of a shared database, kept from a previous run, up to date.

        The server's own file: checked against a new database, not for damage. Read-only,
        it must be at `schema_version` already.
        """
        db = self._database.connection
        try:
            if read_only:
                self._check_version(db)
            else:
                self._database.start_journal()
                self._upgrade(db)
            self._check_schema(db)
        except InvalidStateError as error:
            msg = f"{self._database.path}: {error}"
            raise InvalidStateError(msg) from error

    def _check_version(self, db: sqlite3.Connection) -> None:
        """Refuse a read-only database at another version: it can't be brought up to date."""
        (version,) = db.execute("PRAGMA user_version").fetchone()
        if version != self._owner.schema_version:
            msg = (
                f"its version ({version}) isn't {self._owner.schema_version}, and a"
                " read-only database can't be brought up to date"
            )
            raise InvalidStateError(msg)

    def loaded(self) -> None:
        # every table may have changed; emitted only now, so the views refreshing read the
        # study's views (e.g. a filter), not the ones it replaces
        for table in self._owner._tables:  # noqa: SLF001 (its own database's)
            table.changed.emit()

    def close(self) -> None:
        # not the write's turn: closing the app doesn't wait for a job's long write, whose
        # end closes it, as the last query `reading` it does
        with self._readers_lock:
            self._closed = True
            if self._turns > 0:  # what a server's stop waits for (`wait_for_closed_writes`)
                self._database.closing = True
            self._close_if_unused(self._database)

    def _new_database(self, path: Path | None = None) -> _Database:
        """Create the tables in a new file: a temporary one, or `path`, which it keeps."""
        database = _Database(self._pragmas, path, keep=path is not None)
        database.start_journal()
        db = database.connection
        for table in self._owner._tables:  # noqa: SLF001 (its own database's)
            db.executescript(table.create)
        # an int, which a pragma can't take as a parameter
        db.execute(f"PRAGMA user_version = {int(self._owner.schema_version)}")
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
        """Bring a database opened from a file up to `schema_version`."""
        schema_version = self._owner.schema_version
        (version,) = db.execute("PRAGMA user_version").fetchone()
        if version > schema_version:
            msg = "it was saved by a newer version of the application"
            raise InvalidStateError(msg)
        if version < 1:  # every database made here has a version: this one isn't one
            msg = "its data doesn't match this application"
            raise InvalidStateError(msg)
        for step in range(version, schema_version):
            migrate = self._owner.migrations.get(step)
            if migrate is None:
                msg = f"its data (version {version}) can't be brought up to date"
                raise InvalidStateError(msg)
            migrate(db)
        if version != schema_version:
            # a write only then: a shared file opened again doesn't wait for a write of the
            # engine it had, which a job of a session that ended may still make
            db.execute(f"PRAGMA user_version = {int(schema_version)}")
        db.commit()

    def finish_file(self) -> None:
        """Close a shared database's new file, in SQLite's default journal: one file alone."""
        with self._turn() as db:
            db.execute("PRAGMA journal_mode = DELETE")
        self.close()


SqliteDatabaseT = TypeVar("SqliteDatabaseT", bound=SqliteDatabase)


class _PerSession(Generic[SqliteDatabaseT]):
    """A database a `DatabaseModel` class declares, which each model builds (see `per_session`)."""

    def __init__(self, database_type: type[SqliteDatabaseT], data_name: str | None) -> None:
        self.database_type = database_type
        self.data_name = data_name


def per_session(
    database_type: type[SqliteDatabaseT], *, data_name: str | None = None
) -> SqliteDatabaseT:
    """Declare a database of a `DatabaseModel` that each session has its own copy of.

    E.g. ``study = per_session(Study)``. Each model builds its own database, as an attribute
    of the same name, in a temporary file. The study saves it as its file `data_name`
    (``<attribute>.sqlite`` by default), and New and Open replace it. A model has at most
    one: a study holds one file of data.
    """
    # the model's attribute is the database: typed as one, as `table` does
    return cast("SqliteDatabaseT", _PerSession(database_type, data_name))


#: what tells a shared database's files apart: its class, its file, and whether it's read-only
_StoreKey: TypeAlias = "tuple[type[SqliteDatabase], Optional[Path], bool]"


class _Shared(Generic[SqliteDatabaseT]):
    """A database a `DatabaseModel` class shares between the sessions (see `shared`)."""

    def __init__(
        self,
        database_type: type[SqliteDatabaseT],
        location: Path | Callable[[], Path] | None,
        *,
        read_only: bool,
    ) -> None:
        self.database_type = database_type
        # a path is resolved once: the process's folder may change
        self.location = (
            location if location is None or callable(location) else Path(location).resolve()
        )
        self.read_only = read_only

    def key(self) -> _StoreKey:
        """Get the key of its store, calling a callable `location` for the file."""
        location = self.location
        if callable(location):
            location = Path(location()).resolve()
        return (self.database_type, location, self.read_only)


def shared(
    database_type: type[SqliteDatabaseT],
    *,
    location: Path | Callable[[], Path] | None = None,
    read_only: bool = False,
) -> SqliteDatabaseT:
    """Declare a database of a `DatabaseModel` that every session of the process shares.

    E.g. ``crm = shared(Crm, location=Path("crm.sqlite"))``. The process opens it once, as
    the first model is built, and runs its migrations then. Each model's attribute is the
    session's handle on it, of the database's class: a write in one session emits its
    tables' `changed` in every other one, on its own main thread. The study neither saves
    nor opens it, and New leaves it alone.

    With a `location`, the database is kept in that file, across the process's runs: `fill`
    fills it only when the file doesn't exist yet. The process closes the file once no
    session holds it, e.g. between two tests, and the next model opens it again. Without a
    `location`, it's a temporary file, deleted as the process ends, and `fill` fills it in
    each process. With `read_only`, the sessions only read it: only `fill` writes.

    A callable `location` gives the file as each model is built, e.g. a file under a folder
    that the app reads as it starts, or that each test sets. When the callable gives another
    file, the sessions built before keep the previous file.
    """
    # the model's attribute is the database: typed as one, as `table` does
    return cast("SqliteDatabaseT", _Shared(database_type, location, read_only=read_only))


class DatabaseModel(Model):
    """A model whose data is in databases, which its class declares.

    E.g. ``study = per_session(Study)``, for the callbacks to reach
    (``model.study.runs.add(...)``). Its fields are databases, never tables: declare the
    tables in a `SqliteDatabase`. The `per_session` database is saved and opened with the
    study; the `shared` ones are the process's.
    """

    @override
    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        tables = _declared(cls, _DeclaredTable)
        if len(tables) > 0:
            msg = (
                f"{cls.__name__} declares tables ({', '.join(tables)}): declare them in a"
                " SqliteDatabase, and the database in the model with per_session"
            )
            raise TypeError(msg)
        per_sessions = _declared(cls, _PerSession)
        if len(per_sessions) > 1:
            msg = (
                f"{cls.__name__} declares several per_session databases"
                f" ({', '.join(per_sessions)}): a study holds one, put their tables together"
            )
            raise TypeError(msg)
        filled = [
            name
            for name, declared in per_sessions.items()
            if declared.database_type.fill is not SqliteDatabase.fill
        ]
        if len(filled) > 0:
            msg = (
                f"{cls.__name__}.{filled[0]} is a per_session database with a fill:"
                " only a shared database is filled"
            )
            raise TypeError(msg)
        cls.data_name = next(
            (
                f"{name}.sqlite" if declared.data_name is None else declared.data_name
                for name, declared in per_sessions.items()
            ),
            None,
        )

    def __init__(self) -> None:
        #: the engine of the database saved with the study: none or one
        self._per_session: list[_Engine] = []
        #: the session's handles on the shared databases
        self._handles: list[_Handle] = []
        #: every database, whose tables' signals are the model's
        self._databases: list[SqliteDatabase] = []
        # the shared files, by field: a callable `location` gives its file only now
        fields: dict[str, tuple[_Shared[Any], _StoreKey]] = {}
        for name, declared_shared in _declared(type(self), _Shared).items():
            key = declared_shared.key()
            twice = next((other for other, (_, seen) in fields.items() if seen == key), None)
            if twice is not None:
                msg = (
                    f"{type(self).__name__} shares the same database in several fields"
                    f" ({twice}, {name}): one is enough"
                )
                raise TypeError(msg)
            fields[name] = (declared_shared, key)
        try:
            for name, declared_per_session in _declared(type(self), _PerSession).items():
                database = declared_per_session.database_type()
                engine = _Engine(database, database.pragmas)
                database._engine = engine  # noqa: SLF001 (the engine it's built for)
                self._per_session.append(engine)
                self._databases.append(database)
                setattr(self, name, database)
            for name, (declared_shared, key) in fields.items():
                store = _store_of(key)
                database = declared_shared.database_type()
                handle = _Handle(store, database)
                database._engine = handle  # noqa: SLF001 (the engine it's built for)
                self._handles.append(handle)
                store.attach(handle)
                self._databases.append(database)
                setattr(self, name, database)
        except BaseException:
            self.close()  # e.g. a shared file of a newer version: its temporary files go
            raise

    @property
    @override
    def signals(self) -> list[Signal[Unpack[tuple[Any, ...]]]]:
        """Get the model's signals, its databases' tables' (`SqliteTable.changed`) among them."""
        return [
            *super().signals,
            *(signal for database in self._databases for signal in database._signals),  # noqa: SLF001 (its own database)
        ]

    @override
    def _set_main_view(self, main_view: MainView) -> None:
        # the shared databases tell this session's views of the other sessions' writes
        for handle in self._handles:
            handle.jobs = weakref.ref(main_view.jobs)

    @property
    @override
    def data_version(self) -> int:
        """Get the committed writes of the `per_session` database, not of the study's jobs.

        Those of the jobs started with the study (as the app starts, New, Open) aren't
        counted: the next start makes them again. The `shared` databases' aren't either:
        the study doesn't save them.
        """
        return sum(engine.user_writes for engine in self._per_session)

    @override
    def _data_revision(self) -> int:
        return sum(engine.writes for engine in self._per_session)

    @override
    def _pin_data(self) -> _PinnedDatabase | None:
        # called only for a model with data (`data_name`), so with its database
        return next((engine.pin() for engine in self._per_session), None)

    @override
    def new(self) -> None:
        for engine in self._per_session:
            engine.new()

    @override
    def save_data(self, path: Path) -> None:
        for engine in self._per_session:
            engine.save(path)

    @override
    def open_data(self, path: Path) -> None:
        """Open a study's database, refused unless it is made as a new one is.

        See `SqliteDatabase.open_time_limit`: the file may come from anyone, e.g. a web
        upload, and its schema is checked before its views and triggers may run.
        """
        for engine in self._per_session:
            engine.open_study(path)

    @override
    def loaded(self) -> None:
        for engine in self._per_session:
            engine.loaded()

    @override
    def close(self) -> None:
        for engine in self._per_session:
            engine.close()
        for handle in self._handles:
            handle.close()


class _Generation:
    """A file of a shared database, and the sessions' handles bound to it."""

    def __init__(self, core: SqliteDatabase, engine: _Engine) -> None:
        #: the database the engine reads its tables and settings from, which `fill` filled
        self.core = core
        self.engine = engine
        self.holders = 0
        #: closed once forgotten and no longer held: a handle can't bind to it
        self.closed = False


class _Fill(SharedData["_Generation", Any]):
    """A shared database's file, filled once for every session (see `SharedData`)."""

    def __init__(self, store: _SharedStore) -> None:
        super().__init__(store.open_generation)
        self.__name__ = store.database_type.__name__

    @override
    def _shared(self, value: _Generation) -> tuple[_Generation, Callable[[_Generation], Any]]:
        # the file is shared as it is: its sessions' handles keep it apart
        return value, _same

    def kept(self) -> _Generation | None:
        """Get the file filled for the next sessions; None until one is, or once forgotten."""
        with self._condition:
            return self._value if self._has_value else None


def _same(value: _Generation) -> _Generation:
    return value


class _SharedStore:
    """A `shared` database in this process: its file, and the sessions' handles on it.

    Each handle binds to the current file (`_Generation`): at once, or once `fill` has run.
    After `forget`, the next handles bind to a new file, and the previous one is closed
    once its last handle is. A database kept in a file is closed once no handle holds it,
    and opened again, without `fill`, by the next one.
    """

    def __init__(self, key: _StoreKey) -> None:
        self.database_type, self.location, self.read_only = key
        pragmas = dict(self.database_type.pragmas)
        if self.location is not None and str(pragmas.get("synchronous", "")).upper() == "OFF":
            # a file kept across the runs, which a crash must leave whole
            pragmas["synchronous"] = "NORMAL"
        self.pragmas: Mapping[str, int | str] = MappingProxyType(pragmas)
        # reentrant: a handle bound at once opens the file under it
        self._lock = threading.RLock()
        self._handles: weakref.WeakSet[_Handle] = weakref.WeakSet()
        #: the file of the next sessions, for a database without `fill` (else `_Fill.kept`)
        self._current: _Generation | None = None
        self._fill = _Fill(self) if self.database_type.fill is not SqliteDatabase.fill else None
        # the changes to tell other sessions, by handle, while a thread of its own tells it:
        # it holds no other lock while it waits for its session's, and a busy session (e.g.
        # a long web request) delays no other one
        self._notices = threading.Lock()
        self._pending: dict[_Handle, set[int]] = {}

    def attach(self, handle: _Handle) -> None:
        """Count a session's new handle, bound to the current file unless it needs a fill."""
        with self._lock:
            self._handles.add(handle)
            if self._fill is None:
                if self._current is None:
                    self._current = self.open_generation(None)
                self._bind(handle, self._current)

    def ready(self, handle: _Handle, job: Job[Any, Any]) -> None:
        """Bind `handle` to the filled file, filling it first if no other session has."""
        assert self._fill is not None, "a handle without a fill is bound as it's attached"
        while True:
            generation = self._fill(job)
            with self._lock:
                if handle.closed or handle.generation is not None:
                    # closed meanwhile, or ready in another job of its session
                    self._close_if_unused(generation)
                    return
                if not generation.closed:
                    self._bind(handle, generation)
                    return
            # closed by its last handle before this one got it: open, or fill, again

    def release(self, handle: _Handle) -> None:
        """Forget a closed handle, closing a file no other handle needs."""
        with self._lock:
            self._handles.discard(handle)
            generation, handle.generation = handle.generation, None
            if generation is not None:
                generation.holders -= 1
                self._close_if_unused(generation)

    def forget(self) -> None:
        if self.location is not None:
            msg = (
                f"{self.database_type.__name__} is kept in {self.location}: only a shared"
                " database in a temporary file can be forgotten"
            )
            raise TypeError(msg)
        with self._lock:
            previous = self._kept()
            self._stop_keeping()
            self._close_if_unused(previous)

    def _stop_keeping(self) -> None:
        """Have the next handle bind to a file opened, or filled, anew."""
        self._current = None
        if self._fill is not None:
            self._fill.forget()

    def _bind(self, handle: _Handle, generation: _Generation) -> None:
        handle.generation = generation
        generation.holders += 1

    def _kept(self) -> _Generation | None:
        """Get the file of the next sessions, if there is one yet."""
        return self._current if self._fill is None else self._fill.kept()

    def _close_if_unused(self, generation: _Generation | None) -> None:
        if generation is None or generation.holders != 0:
            return
        if generation is self._kept():
            if self.location is None:  # a temporary file: the next sessions' data is only there
                return
            # the file keeps it: a process doesn't hold a file that no session reads, e.g. one
            # per test
            self._stop_keeping()
        generation.closed = True
        generation.engine.close()

    def open_generation(self, job: Job[Any, Any] | None) -> _Generation:
        """Open the kept file, or make a new one, filled by `job` if not None."""
        location = self.location
        if location is not None and location.exists():
            return self._opened(location)
        core = self.database_type()
        with contextlib.ExitStack() as files:
            # a kept file is made beside, then renamed: a failed fill, or a crash, leaves none
            path = None if location is None else files.enter_context(partial_path(location))
            engine = _Engine(core, self.pragmas, path=path, shared=True)
            core._engine = engine  # noqa: SLF001 (the engine it's built for)
            try:
                if job is not None:
                    core.fill(job)
                    # a fill may stop early and return, e.g. once its last session left
                    job.raise_if_canceled()
                if location is None or path is None:  # a temporary file: the engine's own
                    return _Generation(core, engine)
                engine.finish_file()
            except BaseException:
                engine.close()
                raise
            with self._lock:
                # else filled meanwhile by a canceled run: this one's file goes with `path`
                if not location.exists():  # pragma: no branch
                    path.replace(location)
        return self._opened(location)

    def _opened(self, location: Path) -> _Generation:
        core = self.database_type()
        database = _Database(self.pragmas, location, keep=True, read_only=self.read_only)
        engine = _Engine(core, self.pragmas, database, shared=True)
        core._engine = engine  # noqa: SLF001 (the engine it's built for)
        try:
            engine.open_kept(read_only=self.read_only)
        except BaseException:
            engine.close()
            raise
        return _Generation(core, engine)

    def tell(self, writer: _Handle, generation: _Generation, indices: set[int]) -> None:
        """Have the other sessions on `generation`'s file emit the `changed` of these tables."""
        with self._lock:
            # a kept file's generations are the same file: a write on a closed one, e.g. by a
            # job of a session that ended, is also on the one opened again
            others = [
                handle
                for handle in self._handles
                if handle is not writer
                and handle.generation is not None
                and (self.location is not None or handle.generation is generation)
            ]
        if len(others) == 0:
            return
        with self._notices:
            # a session told already gets these with the changes its thread hasn't told yet
            untold = [handle for handle in others if handle not in self._pending]
            for handle in others:
                self._pending.setdefault(handle, set()).update(indices)
            # counted before this write returns: the session's `Jobs.wait` waits for them
            expecting = [(handle, _expect_post(handle)) for handle in untold]
        for handle, jobs in expecting:
            # a daemon: the process doesn't wait for it to end
            thread = threading.Thread(
                target=self._tell_session,
                args=(handle, jobs),
                name=f"composeui-{self.database_type.__name__}-notices",
                daemon=True,
            )
            try:
                thread.start()
            except RuntimeError:
                # e.g. no thread left: the write is done, and the session is told the next one
                with self._notices:
                    del self._pending[handle]
                _expected_post_over(jobs)
                LOGGER.exception("Telling a session of a change failed")

    def _tell_session(self, handle: _Handle, jobs: weakref.ReferenceType[Jobs] | None) -> None:
        """Tell a session its tables changed, the changes made meanwhile together, until none.

        The thread keeps the handle until then, not its session (`_Handle.deliver`).
        """
        try:
            while True:
                with self._notices:
                    indices = self._pending[handle]
                    if len(indices) == 0:  # all told: the next change starts another thread
                        del self._pending[handle]
                        return
                    self._pending[handle] = set()
                _deliver(handle, indices)
        finally:
            _expected_post_over(jobs)


def _expect_post(handle: _Handle) -> weakref.ReferenceType[Jobs] | None:
    """Have the jobs of `handle`'s session expect a post, if it has an app: get them."""
    jobs = None if handle.jobs is None else handle.jobs()
    if jobs is None:
        return None
    jobs._expect_post()  # noqa: SLF001 (counted for `Jobs.wait`)
    return weakref.ref(jobs)


def _expected_post_over(jobs: weakref.ReferenceType[Jobs] | None) -> None:
    """Have `jobs`, of `_expect_post`, no longer expect the post."""
    live = None if jobs is None else jobs()
    if live is not None:
        live._expected_post_over()  # noqa: SLF001 (counted for `Jobs.wait`)


def _deliver(handle: _Handle, indices: set[int]) -> None:
    """Tell a session its tables changed, logging what its callbacks raise."""
    try:
        handle.deliver(indices)
    except Exception:  # a session's callback: its next changes are still told
        LOGGER.exception("Telling a session of a change failed")


#: the shared databases of the process (`_store_of`)
_STORES: dict[_StoreKey, _SharedStore] = {}
_STORES_LOCK = threading.Lock()


def _store_of(key: _StoreKey) -> _SharedStore:
    """Get the process's store of a shared database, made by its first session."""
    location = key[1]
    with _STORES_LOCK:
        store = _STORES.get(key)
        if store is None:
            if location is not None and any(other[1] == location for other in _STORES):
                msg = (
                    f"{location} is shared already, by another class or with another"
                    " read_only: one file, one shared database"
                )
                raise ValueError(msg)
            store = _STORES[key] = _SharedStore(key)
    return store


class _Handle:
    """A session's handle on a shared database: the session's tables on the store's file."""

    def __init__(self, store: _SharedStore, owner: SqliteDatabase) -> None:
        self._store = store
        # weak: the database owns its handle
        self._owner = weakref.ref(owner)
        #: the file it reads and writes, once bound (`_SharedStore.attach`, `ready`)
        self.generation: _Generation | None = None
        self.closed = False
        #: its session's jobs, which hand the other sessions' changes to its main thread
        self.jobs: weakref.ReferenceType[Jobs] | None = None

    def add_table(self, table: SqliteTable) -> None:
        msg = (
            f"{self._store.database_type.__name__} is shared: its tables are created once,"
            " as declared by its class or added in its __init__"
        )
        raise TypeError(msg)

    def _bound(self) -> _Generation:
        if self.closed:
            msg = "Cannot operate on a closed database."
            raise sqlite3.ProgrammingError(msg)
        generation = self.generation
        if generation is None:
            name = self._store.database_type.__name__
            msg = f"{name} isn't filled yet: call its ready(job) in a job first"
            raise RuntimeError(msg)
        return generation

    @contextlib.contextmanager
    def connection(self, *, changing: SqliteTable | None = None) -> Generator[sqlite3.Connection]:
        generation = self._bound()
        if self._store.read_only:
            with self._read_only(generation) as db:
                yield db
            return
        on_commit = functools.partial(self._committed, generation)
        with generation.engine.connection(changing=changing, on_commit=on_commit) as db:
            yield db

    @contextlib.contextmanager
    def reading(self) -> Generator[sqlite3.Connection]:
        generation = self._bound()
        if self._store.read_only:
            with self._read_only(generation) as db:
                yield db
            return
        with generation.engine.reading() as db:
            yield db

    @contextlib.contextmanager
    def _read_only(self, generation: _Generation) -> Generator[sqlite3.Connection]:
        """Read on a connection that refuses a write with a message of its own."""
        with generation.engine.reading() as db:
            try:
                yield db
            except sqlite3.OperationalError as error:
                if db.in_transaction:  # a write refused began one: the next reader reuses db
                    db.rollback()
                if "readonly database" not in str(error):
                    raise
                name = self._store.database_type.__name__
                msg = f"{name} is shared read-only: its sessions can't write to it"
                raise ReadOnlyDatabaseError(msg) from error

    def _committed(self, generation: _Generation, changed: list[SqliteTable]) -> None:
        """Emit this session's `changed`, and have the other sessions emit theirs."""
        if len(changed) == 0:
            return
        _emit(changed)
        owner = self._owner()
        assert owner is not None  # its write's own database
        tables = owner._tables  # noqa: SLF001 (its own database's)
        self._store.tell(self, generation, {tables.index(table) for table in changed})

    def deliver(self, indices: set[int]) -> None:
        """Emit the `changed` of another session's write, on this session's main thread."""
        owner = self._owner()
        if owner is None or self.closed:
            return
        tables = [owner._tables[index] for index in sorted(indices)]  # noqa: SLF001 (its own database's)

        def emit() -> None:
            # a web session ended meanwhile runs it no more (`call_in_session`)
            for table in tables:
                table.changed.emit()

        jobs = None if self.jobs is None else self.jobs()
        if jobs is None:  # no app: as a write of its own outside a job
            emit()
        else:
            jobs._post(emit)  # noqa: SLF001 (the session's main thread)

    def ready(self, job: Job[Any, Any]) -> None:
        if self.closed:
            msg = "Cannot operate on a closed database."
            raise sqlite3.ProgrammingError(msg)
        if self.generation is None:
            self._store.ready(self, job)

    def forget(self) -> None:
        self._store.forget()

    def close(self) -> None:
        self.closed = True
        self._store.release(self)


class _PinnedDatabase:
    """A database's rows pinned by a reader's transaction (`_Engine.pin`)."""

    def __init__(self, engine: _Engine, database: _Database, db: sqlite3.Connection) -> None:
        self._engine = engine
        self._database = database
        self._db = db

    def write(self, path: Path) -> None:
        target = sqlite3.connect(str(path))
        try:
            self._db.backup(target)
            # as `_Engine.save`: a file another app opens leaves no journal beside it
            target.execute("PRAGMA journal_mode = DELETE")
        finally:
            target.close()

    def release(self) -> None:
        self._db.rollback()  # the read's transaction, before another query reuses the reader
        self._engine._give_back_reader(self._database, self._db)  # noqa: SLF001 (its engine)


class _Database:
    """A connection to a database file: a temporary one, deleted with it, unless `keep`.

    Its journal is SQLite's default until `start_journal` sets the one of `pragmas`: a
    backup into a WAL database from one of another page size fails. A `read_only` one
    writes nothing, its journal included.
    """

    def __init__(
        self,
        pragmas: Mapping[str, int | str],
        path: Path | None = None,
        *,
        keep: bool = False,
        read_only: bool = False,
    ) -> None:
        statements = [
            _pragma_statement(name, value)
            for name, value in pragmas.items()
            if name != "journal_mode"
        ]
        #: the database's `pragmas`, set on each connection: SQLite keeps them per connection
        self.pragma_statements = statements
        journal = pragmas.get("journal_mode")
        self._journal = None if journal is None else _pragma_statement("journal_mode", journal)
        if path is None:
            # the process's own folder: a crash's file goes at the next start
            fd, name = tempfile.mkstemp(
                prefix="composeui-", suffix=".sqlite", dir=scratch_directory()
            )
            os.close(fd)
            path = Path(name)
        self.path = path
        # threads take turns through the engine's lock
        self.connection = sqlite3.connect(
            f"{path.as_uri()}?mode=ro" if read_only else str(path),
            uri=read_only,
            check_same_thread=False,
            timeout=WAIT_SECONDS,
        )
        self.connection.row_factory = sqlite3.Row
        for statement in statements:
            self.connection.execute(statement)
        #: the read-only connections not in use, for the next queries `reading` it
        self.idle_readers: list[sqlite3.Connection] = []
        # also when the database is dropped unclosed (e.g. an expired web session's)
        self._finalizer = weakref.finalize(
            self, _discard, self.connection, self.path, self.idle_readers, keep=keep
        )
        # not by Python's exit itself: it would close the connection under a job's statement,
        # which crashes the process (`_close_at_exit`)
        self._finalizer.atexit = False  # type: ignore[misc]  # a property that typeshed misses
        #: the queries reading it on connections of their own (`SqliteDatabase.reading`)
        self.readers = 0
        #: the turns and the readers that use it now, which Python's exit waits for
        self.users = 0
        #: every reader's connection, idle or reading: Python's exit interrupts their queries
        self.reader_connections: list[sqlite3.Connection] = []
        #: its model is closed while a turn holds it, which closes it at its end
        self.closing = False
        # until its end, the thread that made it may use it outside a turn (e.g. `open_study`)
        self._creator = threading.current_thread()
        with _USERS:
            _OPEN_DATABASES.add(self)

    def acquire(self) -> bool:
        """Count a use of the database; tell if it may start: not once Python exits.

        The caller refuses one that may not with `_refuse_at_exit`, once out of its locks.
        """
        with _USERS:
            if _Exit.started:
                return False
            self.users += 1
            return True

    def release(self) -> None:
        """Count a use of the database as over."""
        with _USERS:
            self.users -= 1
            _USERS.notify_all()

    def close_at_exit(self) -> None:
        """Close the database as Python exits, unless another thread may still use it."""
        creator = self._creator
        if self.users == 0 and (creator is threading.current_thread() or not creator.is_alive()):
            self.close()

    def open_reader(self) -> sqlite3.Connection:
        """Open a read-only connection, with the database's `pragmas`: any thread uses it."""
        uri = f"{self.path.as_uri()}?mode=ro"
        reader = sqlite3.connect(uri, uri=True, timeout=WAIT_SECONDS, check_same_thread=False)
        for statement in self.pragma_statements:
            reader.execute(statement)
        self.reader_connections.append(reader)
        return reader

    def start_journal(self) -> None:
        """Set the journal of the database's `pragmas`, which the file keeps."""
        if self._journal is not None:
            self.connection.execute(self._journal)

    def close(self) -> None:
        # not by calling it: Python's exit turns the finalizers into no-ops, and a job's write
        # can end its turn, which closes the database, after
        detached = self._finalizer.detach()
        if detached is not None:
            _, discard, args, kwargs = detached
            discard(*args, **kwargs)


class _Exit:
    """Whether Python's exit has started: the databases then take no more queries."""

    started = False


#: the databases open in this process: Python's exit closes those that no thread uses
_OPEN_DATABASES: weakref.WeakSet[_Database] = weakref.WeakSet()
#: guards each database's `users` and `_Exit.started`, and wakes an exit that waits for them
_USERS = threading.Condition()
#: seconds that an exit waits for the writes running, before it interrupts them
EXIT_WAIT_SECONDS = 5.0
#: seconds that an exit then waits for the writes interrupted to stop
INTERRUPTED_WAIT_SECONDS = 1.0


def _wait_for_users(databases: list[_Database], timeout: float) -> None:
    """Wait up to `timeout` seconds for no thread to use `databases`, then interrupt them.

    A write interrupted ends with an `sqlite3.OperationalError`, and rolls back.
    """

    def used() -> list[_Database]:
        return [database for database in databases if database.users > 0]

    with _USERS:
        if _USERS.wait_for(lambda: len(used()) == 0, timeout):
            return
        for database in used():
            for connection in [database.connection, *database.reader_connections]:
                # one closed meanwhile, by the end of its turn, has nothing left to stop
                with contextlib.suppress(sqlite3.ProgrammingError):
                    # thread-safe: it stops the statement running, at its next step
                    connection.interrupt()
        _USERS.wait_for(lambda: len(used()) == 0, INTERRUPTED_WAIT_SECONDS)


def _refuse_at_exit() -> NoReturn:
    """Refuse a use of a database once Python exits; call it out of the engine's locks."""
    if threading.current_thread() is threading.main_thread():
        msg = "The app is exiting: its database takes no more queries."
        raise RefusedError(msg)
    # a job's thread waits for the process's end: an error that it would write as Python
    # exits can abort the process
    with _USERS:
        while True:
            _USERS.wait()


def wait_for_closed_writes() -> None:
    """Wait briefly for the writes on the closed models' databases: e.g. as a server stops.

    A write that goes on after `EXIT_WAIT_SECONDS` is interrupted.
    """
    with _USERS:
        closing = [database for database in _OPEN_DATABASES if database.closing]
    _wait_for_users(closing, EXIT_WAIT_SECONDS)


def _close_at_exit() -> None:
    """Close the databases as Python exits, once their writes are over or interrupted.

    A database that a thread still uses stays open: the process's end releases it, and the
    next start removes its files.
    """
    with _USERS:
        _Exit.started = True
        databases = list(_OPEN_DATABASES)
    _wait_for_users(databases, EXIT_WAIT_SECONDS)
    for database in databases:
        database.close_at_exit()


# a job's thread is a daemon: Python's exit doesn't wait for it
atexit.register(_close_at_exit)


def _remove_file(path: Path) -> None:
    """Delete a database file, with the WAL journal's files a crash may leave beside it."""
    for name in (path.name, f"{path.name}-wal", f"{path.name}-shm", f"{path.name}-journal"):
        path.with_name(name).unlink(missing_ok=True)


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


def _discard(
    connection: sqlite3.Connection,
    path: Path,
    readers: list[sqlite3.Connection],
    *,
    keep: bool,
) -> None:
    for reader in readers:  # first: the last connection closed deletes the WAL journal
        reader.close()
    readers.clear()
    connection.close()
    if not keep:
        # the WAL journal's files too, which the last connection closed deletes, unless it crashed
        _remove_file(path)

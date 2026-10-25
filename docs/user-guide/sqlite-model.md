# A SQLite model

Views hold what is shown. Some data has many rows, relations between them, and queries over
them, for example runs and their results, or a catalogue of parts. This data belongs in a
`SqliteModel`: a SQLite database of the app's own, with its own schema and SQL. The study
saves and opens it.

```python
import attrs

from composeui.core.sqlitemodel import SqliteModel, SqliteTable, table


@attrs.define
class Run:
    id: int
    radius: float


class Runs(SqliteTable):
    create = "CREATE TABLE run(id INTEGER PRIMARY KEY, radius REAL NOT NULL);"

    def add(self, radius: float) -> None:
        with self.connection() as db:
            db.execute("INSERT INTO run(radius) VALUES (?)", (radius,))

    def above(self, radius: float) -> list[Run]:
        return self.fetch(Run, "SELECT * FROM run WHERE radius > ?", (radius,))


class PipeModel(SqliteModel):
    runs = table(Runs)
```

Give the model to the app:
`run(PipeMainView, build_model=PipeModel, setup_model=PipeMainView.connect_model)`.
A `ModelApplication` (`QtModelApplication`, `TextualModelApplication`,
`WebModelApplication`) takes the same arguments. Callbacks that ask for `model` reach the
tables (`model.runs.add(...)`).

- **Transactions.** `with self.connection() as db:` commits once the block ends, and rolls
  back if the block raises. A block inside another block joins it. The threads take turns
  on the model's connection.
- **Reads apart.** `with self.reading() as db:` gives a connection that only reads, and takes no
  turn: it neither waits for a write nor holds one up. It reads the rows committed, not those of a
  transaction still open. The connection is reused: read each query's rows to the end in the block,
  else the next reader sees the rows as they were when the query started. A large table's
  [`SqliteSource`](tables.md#rows-in-sqlite) reads its rows this way.
- **Settings.** `pragmas` is set on the connection of every study, because SQLite keeps
  these settings per connection, not in the file. Foreign keys and recursive triggers are
  on. `synchronous` is off, because the model's database is a scratch copy and the study file
  is written separately. The journal is `WAL`, so that `reading` reads during a write; the
  study file is saved in SQLite's default journal. Override `pragmas` to change them
  (`pragmas = {**SqliteModel.pragmas, "cache_size": -64000}`).
- **Typed rows.** `fetch` and `fetch_one` turn rows into `attrs` instances through the
  `cattrs` converter of the views. `fetch_column` gives the first column of a query, for
  example a list of names. `as_parameters(row)` gives the fields of an instance as the named
  parameters of a query.
- **Batch inserts.** `insert_batches(sql, rows, batch_size=100_000, limit=None)` accepts
  an iterable of positional or named SQL parameters. It yields the cumulative number of
  rows submitted after each batch, including a final partial batch. Counts are not the
  number of affected rows when SQL ignores a row. `limit` caps the rows read without
  consuming an extra row; zero reads none. The batch size must be positive, and the limit
  must be nonnegative or `None` (all rows).
  Exhaust the generator to commit all batches together. If iteration can stop early, use
  `contextlib.closing` so the open transaction rolls back. Inside an existing
  `connection()` block, batches join that transaction; raise out of the outer block to
  roll it back. Keep progress callbacks short: the transaction stays open between yields.
  To reuse an open connection explicitly, pass `db=db`. The helper does not commit,
  roll back, or close a supplied connection. Get it from the table's `connection()` to
  keep change notifications; that outer block controls the transaction.
- **New names.** `unique_name(db, "run", "name", "Run")` gives "Run", or else "Run 2",
  "Run 3", and so on: the first name that the column doesn't hold, whatever its case. Use it
  for a row that the user adds, then renames.
- **Refusals.** When a constraint fails, the transaction is refused: `connection()` raises a
  `RefusedError` (`composeui.core.model`). Its message is the table's message for the
  constraint, from `refusals`, else the message of SQLite. `refusals` maps a part of the
  SQLite message to a message, for example
  `{"thin_wall": "its wall must be thinner than its radius"}`.
  A view shows the refusal in the status bar with
  `with self.refusing(self.tr("Can't add the pipe: {error}")):`. The message is translated
  too: the catalog check finds the `refusals` of a table in the module of a view. In a
  `cell_edited` or `record_edited` callback, the edit is refused as well.
- **Refreshing views.** The `changed` signal of a table is emitted after a commit that
  changed rows through the table, and after New and Open, once the views are loaded. So the
  views that show the rows can follow. Connect it in `setup_model(main_view, model)`. The
  app calls `setup_model` once the main view and the model are built, and on the web for
  each session. A method of the main view keeps the connection beside the views that it
  refreshes. A view's method that asks for `model` gets it, and `now=True` shows the rows
  right away:

  ```python
  def connect_model(self, model: PipeModel) -> None:  # PipeMainView's
      model.runs.changed.connect(self.show_runs, now=True)
  ```

- **Studies.** New starts an empty database. Save and Open (and `-f`) save and open the
  state of the views and the database together, as a zip archive with the app's `extension`.
  The model works on a scratch copy in a temporary file. So the user's file changes only
  when the user saves it, and a failed save leaves the file whole. Opening checks everything
  first. When a file doesn't fit, the study stays as it was, and the status bar says why.
- **Versions.** Raise `schema_version` with every change to the tables. Add the step from
  the previous version to `migrations` (`{1: add_stress_column}`). When the user opens a
  study saved by an older version, the model brings it up to date. A study saved by a newer
  version is refused.
- **Opened databases are checked.** A study can come from anyone, such as a web upload or
  an email. Its database must be made as a new one is: the same tables with the same
  columns, and the same views, triggers and indexes, with the same SQL. Otherwise it is
  refused, because a view or a trigger in the file would run in the app. So each migration
  must leave the database as a new one at its version. For example, it recreates a view from
  the same SQL as `create`. The `CHECK` and `REFERENCES` of a table are not compared,
  because `ALTER TABLE ... ADD COLUMN` can't add all of them. Opening a database, its
  migrations included, stops after `open_time_limit` seconds (30 by default).
- **Writing from a job.** The function of a [job](threads.md) can write to
  the tables: the model's lock lets one thread at a time use the connection. The `changed`
  signal of a write in a job is emitted on the main thread, through
  `job.call_on_main_thread`, so the views refresh there. New and Open drop the jobs before
  they replace the database. Check `job.is_canceled` in the transaction that writes, so a
  canceled job never writes into the next study:

  ```python
  def sweep(job: Job[int], model: PipeModel, radii: list[float]) -> int:  # in its thread
      for count, radius in enumerate(radii):
          with model.runs.connection():
              if job.is_canceled:
                  return count
              model.runs.add(radius)  # joins the transaction
      return len(radii)
  ```

- **On the web,** the database of each session is deleted with the session.

[`src/examples/pipecatalogue.py`](../../src/examples/pipecatalogue.py) puts it together, on
every backend (`uv run python -m examples.pipecatalogue --backend qt`):

- The database checks the pipes of a catalogue as a form in a
  [sidebar](organizing-the-window.md#sidebar) adds them.
- A [list of views](organizing-the-window.md#a-list-of-views) shows an expander per pipe, beside a
  tree of the pipes by material.
- A filtered query lists the pipes, with their mass from a SQL view that joins them to their
  material.
- Each pipe has an installation date, picked with a `DateInputView`, which the list can
  filter by. Studies saved before the date column existed get the column when they open,
  through a migration.

[`src/examples/pipesweep.py`](../../src/examples/pipesweep.py) writes to its model from a job
(`uv run python -m examples.pipesweep --backend qt`).

## Importing CSV data

`CSVSqliteTable` creates a table and its insertion SQL from an `attrs` row class and a
table name. Each CSV row is converted to that class before insertion, so attrs converters,
defaults, factories, and validators apply.

```python
from datetime import datetime
from io import StringIO

import attrs

from composeui.core.sqlitemodel import CSVSqliteTable, SqliteModel, csv_field, table


@attrs.define
class Reading:
    recorded: datetime = csv_field("Recorded", date_format="%d/%m/%Y %H:%M")
    value: float = csv_field("Value", validator=attrs.validators.ge(0))
    station: str = csv_field("Station", default="unknown")


class Readings(CSVSqliteTable, row_type=Reading, name="reading"):
    pass


class ReadingModel(SqliteModel):
    readings = table(Readings)


model = ReadingModel()
try:
    text = StringIO("Recorded;Value\n25/10/2026 17:00;12.5\n")
    for count in model.readings.fill(text, delimiter=";", batch_size=1000):
        print(f"Submitted {count} rows")
    source = model.readings.source(headers={"recorded": "Recorded at", "value": "Value"})
    print(f"Source contains {source.count()} rows")
finally:
    model.close()
```

- **Columns.** Field names become SQL column names. CSV headers match those names unless
  `csv_field("Header")` gives another header. Plain attrs fields work too. Supported field
  types are `str`, `int`, `bool`, `float`, `bytes`, `decimal.Decimal`, `datetime.date`, and
  `datetime.datetime`, plus `Optional` forms. Optional fields permit SQL `NULL`; other
  fields are `NOT NULL`. A default supplies a missing header, not an empty CSV cell.
  Computed attrs fields (`init=False`) are stored too. No primary key or indexes are added.
  Use SQLite's `rowid` for a row identifier, or add indexes in the table's `create` script.
- **Table sources.** Assign `model.readings.source()` to a `DataTableView.source` to show
  the imported rows. Field types come from the row class. Headers use `csv_field` names,
  or field names for plain attrs fields. Pass `headers={"field": "Label", ...}` to select,
  order, and label the columns. Unknown fields raise `KeyError`. The source uses SQLite's
  hidden row IDs and the table's `changed` signal. If fields shadow all three SQLite row-ID
  names (`rowid`, `_rowid_`, and `oid`, case-insensitive), creation raises `ValueError`.
  Use [`SqliteSource`](tables.md#rows-in-sqlite) directly for custom queries or explicit keys.
- **Conversion.** Without a converter, fields use the shared cattrs converter.
  `csv_field` forwards attrs options such as `converter`, `validator`, `default`, and
  `factory`. For nonstandard values, supply a converter: for example, map `"yes"` and `"no"`
  to booleans, or use `decimal.Decimal` for decimal text. Validators run after conversion.
- **Dates.** `date_format` uses `datetime.strptime` and returns a `date` or `datetime`
  according to the annotation. Without a format, dates use ISO text. Static type checking
  rejects a formatted field annotated as `float`, for example. Table declaration also checks
  the type at runtime. Do not combine `date_format` and `converter`. SQLite stores dates
  and datetimes as ISO text; timezone offsets supplied by the format are preserved.
- **Input.** `fill` accepts an iterable of text lines. Open files with `newline=""` and
  the required encoding. The caller owns that input. For a path, use
  [`fill_from_file`](#csv-files) to open and close the file automatically. For URLs, use
  [`fill_from_url` or `open_csv_url`](#csv-urls) to handle downloads and gzip decompression.
  Extra keywords, such as `delimiter` and `fieldnames`, go to `csv.DictReader`.
- **Progress and transactions.** `fill(text, batch_size=100_000, limit=None)` yields
  cumulative submitted-row counts. All batches share one transaction. Exhaust the generator
  to commit. If iteration can stop early, use `contextlib.closing` to roll back.
  Nested transactions follow the batch-insert rules above. `limit` caps imported rows
  without reading another data row. The input remains open.
- **Invalid rows.** Conversion and attrs validation errors (`ValueError` or `TypeError`)
  become `RefusedError`, with the original exception as their cause. The whole import rolls
  back, including earlier batches. In a UI callback, `self.refusing(...)` can show the
  refusal. In a [job](threads.md), let it reach `job.failed` and update the UI in that
  signal's handler. An empty or invalid schema is a declaration error, not a user refusal.
- **Saved data.** CSV tables are part of the SQLite study, like other tables. Reconnect
  data sources after Open or reload through the table's `changed` signal. Sources are not
  serialized with the views. Reuse restored rows instead of importing them a second time.

### CSV files

`CSVSqliteTable.fill_from_file(path, ...)` opens a plain or gzip CSV file and imports its
rows. Pass a path string or a `pathlib.Path`, absolute or relative to the current working
directory. Gzip is detected from the content, not the file suffix.

With `ReadingModel` from the preceding example, import a local `readings.csv.gz` file as
follows. The file uses the same semicolon-separated columns:

```python
from contextlib import closing

model = ReadingModel()
try:
    with closing(
        model.readings.fill_from_file("readings.csv.gz", sniff=True, batch_size=1000)
    ) as batches:
        for count in batches:
            print(f"Submitted {count} rows")
finally:
    model.close()
```

`encoding="utf-8"` sets the text encoding. `batch_size`, `limit`, and CSV options follow
`fill`. The method appends rows and yields cumulative submitted-row counts. Exhaust the
generator to commit. If iteration can stop early, use `contextlib.closing` to close the
file and roll back. Nested transactions follow `fill`'s rules. File, decompression, and
decoding errors propagate; a missing file raises `FileNotFoundError`.

### CSV URLs

`CSVSqliteTable.fill_from_url` imports CSV from a trusted HTTP, HTTPS, or file URL.
It detects gzip from the content, even when the URL has no `.gz` suffix. Other compression
formats are not supported. Like `fill`, it appends rows and yields cumulative submitted-row
counts. It does not cache downloads or skip imports when the table already contains rows.

With `ReadingModel` from the preceding example, import a local `readings.csv.gz` file as
follows. The file uses the same semicolon-separated columns:

```python
from contextlib import closing
from pathlib import Path

url = Path("readings.csv.gz").resolve().as_uri()
model = ReadingModel()
try:
    with closing(model.readings.fill_from_url(url, delimiter=";", batch_size=1000)) as batches:
        for count in batches:
            print(f"Submitted {count} rows")
finally:
    model.close()
```

`encoding="utf-8"` sets the text encoding. `timeout=30.0` sets the socket timeout in seconds,
not a deadline for the whole download. `batch_size`, `limit`, and CSV options follow `fill`.
Exhaust the generator to commit. If iteration can stop early, use `contextlib.closing` to
close the response and roll back the import. Nested transactions follow the same rules
as `fill`.

For CSV processing without a SQLite import, use `open_csv_url` from the same module.
It preserves newlines for the CSV reader and closes the text stream and response on exit:

```python
import csv

from composeui.core.sqlitemodel import open_csv_url

with open_csv_url(url) as text:
    print(next(csv.DictReader(text, delimiter=";")))
```

Both APIs propagate network, decompression, and decoding errors. Conversion and validation
errors in `fill_from_url` become `RefusedError`, as with `fill`. Use these APIs only with
trusted URLs: they do not restrict hosts, redirects, or local file access. Unsupported URL
schemes raise `ValueError`.

Run downloads in a [job](threads.md) to keep the UI responsive. The
[Uber pickups example](../../src/examples/uberpickups.py) uses `fill_from_url` and reports
batch counts through a [reusable loading task](threads.md#reusable-loading-tasks).

### CSV dialect detection

Pass `sniff=True` to `fill_from_file` or `fill_from_url` to infer the CSV dialect with
`csv.Sniffer`. `sniff_sample_size=8192` limits the sample to that many decoded characters,
after gzip decompression. For wide headers or long rows, increase it, for example to
`sniff_sample_size=65536`. The size must be positive when sniffing; otherwise it is ignored.
The sampled text is replayed for parsing, including partial lines and quoted newlines. No
seek is required, so HTTP streams work too.

Explicit CSV options, including `delimiter`, `quotechar`, and `dialect`, override detected
settings. Without `sniff=True`, the comma-separated default and explicit options work as
before. No header inference is performed: the first row supplies column names unless
`fieldnames` is supplied.

Detection failure raises `RefusedError` with instructions to increase the sample size or
disable sniffing and supply explicit CSV options. A larger sample can help, but detection
can still guess the wrong dialect. For a known format, leave sniffing off and set its
options explicitly. Sampling reads ahead of the current batch or row limit, but only the
requested rows are imported. Import errors and early closure retain the same rollback
rules. An invalid sample size raises `ValueError` when sniffing is enabled.

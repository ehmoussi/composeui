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
- **Batch inserts.** `insert_batches(sql, rows, batch_size=100_000, limit=None)` inserts
  `rows`, an iterable of the positional or named parameters of `sql`, a batch at a time.
  - It is a generator. After each batch, it yields the number of rows sent so far, the last
    batch included. When the SQL ignores a row, this is not the number of rows inserted.
  - `limit` sets the number of rows to read, and reads no row past it. A `limit` of 0 reads
    none, and `None` reads all of them. `batch_size` is positive, and `limit` is not
    negative.
  - All the batches are one transaction. Read the generator to the end to commit them.
    When the loop can stop early, wrap the generator in `contextlib.closing`: closing it
    rolls the transaction back.
  - The transaction stays open between two batches, so keep the loop's own work short, for
    example a progress report.
  - Inside a `connection()` block, the batches join its transaction. The block commits
    them, and an exception out of it rolls them back.
  - `db=db` inserts on a connection that you give. The generator then never commits, rolls
    back, or closes it. Take it from the table's `connection()`, so that the table emits
    `changed`.
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

A `CSVSqliteTable` imports CSV data into a table of the model. An `attrs` row class gives
the table its columns: the table converts each CSV row into the class before it inserts
it. So the converters, defaults, factories, and validators of the class apply.

```python
from datetime import datetime
from io import StringIO

import attrs

from composeui.core.sqlitemodel import CSVSqliteTable, SqliteModel, csv_field, define_csv_row, table


@define_csv_row
class Reading:
    recorded: datetime = csv_field(name="Recorded", date_format="%d/%m/%Y %H:%M")
    value: float = csv_field(name="Value", validator=attrs.validators.ge(0))
    station: str = csv_field(name="Station", default="unknown")


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

- **The row class.** `@define_csv_row` applies `attrs.define` with its default options. It
  also tells type checkers that `csv_field` declares a field, not a default value.
  `csv_field(name="Header")` gives the CSV header of the field. A row class with
  `@attrs.define` also works when the app runs, but a type checker then reads each
  `csv_field` as a default value.
- **Type checks with mypy.** Turn on the plugin of ComposeUI:

  ```toml
  [tool.mypy]
  plugins = ["composeui.mypy"]
  ```

  Install mypy yourself: ComposeUI does not import it when the app runs. The plugin gives
  mypy the CSV fields, as attrs fields, and the types of converters such as `str.strip`.
  So mypy checks the arguments of the class as attrs builds them: with their converters,
  defaults, factories, aliases, and `init=False` fields.
- **Columns.** Each field is a column of the same name. The CSV header of a column is its
  `csv_field` name, else its field name: plain `attrs` fields work too.
  - The types of the fields are `str`, `int`, `bool`, `float`, `bytes`, `decimal.Decimal`,
    `datetime.date`, and `datetime.datetime`, or an `Optional` of one of them.
  - An `Optional` field accepts SQL `NULL`. The other fields are `NOT NULL`.
  - A default fills a column that the CSV data doesn't have, not an empty cell.
  - A computed field (`init=False`) is stored too.
  - The table has no primary key and no index. Use SQLite's `rowid` to identify a row, and
    add the indexes in the table's `create` script.
- **A source for a large table.** `model.readings.source()` gives a
  [`SqliteSource`](tables.md#rows-in-sqlite) of the rows, for a `DataTableView`.
  - The types of its columns come from the row class, and their headers are the CSV
    headers.
  - `headers={"field": "Label", ...}` selects, orders, and labels the columns. An unknown
    field raises `KeyError`.
  - The source identifies the rows by SQLite's hidden row id, and follows the table's
    `changed` signal. When the fields take all three names of the row id (`rowid`,
    `_rowid_`, and `oid`, in any case), `source()` raises `ValueError`.
  - For a query of your own, or a key of your own, build a `SqliteSource` yourself.
- **Conversion.** A field without a converter goes through the `cattrs` converter of the
  views. `csv_field` passes the options of `attrs`, such as `converter`, `validator`,
  `default`, and `factory`. Give a converter for other values, for example to turn "yes" and
  "no" into booleans. The validators run after the conversion.
- **Dates.** `date_format` reads the text with `datetime.strptime`. The field gets a `date`
  or a `datetime`, as its annotation says. Without a format, the text is ISO 8601.
  - A field with a `date_format` must be a `date` or a `datetime`. The mypy plugin refuses
    another type, and the table refuses it when Python defines it.
  - A field has a `date_format` or a `converter`, not both.
  - SQLite keeps the dates as ISO 8601 text. A time zone offset that the format reads is
    kept.
- **Input.** `fill` reads an iterable of lines of text, which you open and close. Open a
  file with `newline=""` and its encoding. To import a file, use
  [`fill_from_file`](#csv-files), which opens and closes it. To import a URL, use
  [`fill_from_url`](#csv-urls). The other keyword arguments, such as `delimiter` and
  `fieldnames`, go to `csv.DictReader`.
- **Progress and transactions.** `fill(text, batch_size=100_000, limit=None)` follows the
  rules of [`insert_batches`](#a-sqlite-model): it yields the rows sent so far, and commits
  all the batches together once the loop reads it to the end. `limit` sets the number of
  rows to import. `fill` does not close the input.
- **Invalid rows.** An error of conversion or of validation (`ValueError` or `TypeError`)
  becomes a `RefusedError`, caused by the original error. The whole import rolls back,
  with the batches before it. In a callback, `self.refusing(...)` shows the refusal. In a
  [job](threads.md), let it reach `job.failed`, and show it in the callback of that signal.
  An empty or wrong row class is an error of the code, not a refusal.
- **Studies.** A CSV table is part of the study, like the other tables. After Open or a
  reload, build the sources again from the table's `changed` signal: the study does not
  save them with the views. Use the rows that the study holds: do not import them again.

### CSV files

`fill_from_file(path, ...)` imports a CSV file, plain or gzip. The path is a string or a
`pathlib.Path`, absolute or from the current directory. The method tells a gzip file by
its content, not by its suffix:

```python
from contextlib import closing

model = ReadingModel()  # the model of the previous example
try:
    with closing(
        model.readings.fill_from_file("readings.csv.gz", sniff=True, batch_size=1000)
    ) as batches:
        for count in batches:
            print(f"Submitted {count} rows")
finally:
    model.close()
```

- `encoding="utf-8"` sets the encoding of the text. `batch_size`, `limit`, and the CSV
  options are those of `fill`.
- The method adds the rows to the table, and follows the transaction rules of `fill`.
  Closing it early closes the file, and rolls the import back.
- An error of the file, of the decompression, or of the decoding goes to the caller. A
  missing file raises `FileNotFoundError`.

### CSV URLs

`fill_from_url(url, ...)` imports CSV data from an HTTP, HTTPS, or file URL. It tells gzip
data by its content, also without a `.gz` suffix. It reads no other compression:

```python
from contextlib import closing
from pathlib import Path

model = ReadingModel()  # the model of the first example
url = Path("readings.csv.gz").resolve().as_uri()  # or an https:// URL
try:
    with closing(model.readings.fill_from_url(url, delimiter=";", batch_size=1000)) as batches:
        for count in batches:
            print(f"Submitted {count} rows")
finally:
    model.close()
```

- `encoding="utf-8"` sets the encoding of the text. `timeout=30.0` is the time, in seconds,
  that each read of the socket waits, not the time of the whole download. `batch_size`,
  `limit`, and the CSV options are those of `fill`.
- The method adds the rows to the table, and follows the transaction rules of `fill`.
  Closing it early closes the response, and rolls the import back.
- It keeps no copy of the download, and imports the rows again into a table that already
  has them.

To read CSV data from a URL without importing it, use `open_csv_url` from the same module.
It keeps the newlines for the CSV reader, and closes the text and the response at the end
of the block:

```python
import csv

from composeui.core.sqlitemodel import open_csv_url

with open_csv_url(url) as text:
    print(next(csv.DictReader(text, delimiter=";")))
```

- An error of the network, of the decompression, or of the decoding goes to the caller. An
  error of conversion or of validation in `fill_from_url` becomes a `RefusedError`, as in
  `fill`. A URL of another scheme raises `ValueError`.
- **Give these functions trusted URLs only.** They accept every host, follow redirects, and
  read local files.

A download takes time: run it in a [job](threads.md). The
[Uber pickups example](../../src/examples/uberpickups.py) imports its CSV with
`fill_from_url`, and shows the count of rows in a
[reusable loading task](threads.md#reusable-loading-tasks).

### CSV dialect detection

`sniff=True` makes `fill_from_file` and `fill_from_url` find the CSV dialect, such as the
delimiter, with `csv.Sniffer`.

- **The sample.** `sniff_sample_size=8192` is the number of characters that the sniffer
  reads, after the decompression and the decoding. For long headers or rows, give a larger
  sample, for example `sniff_sample_size=65536`. With `sniff=True`, a size that is not
  positive raises `ValueError`. Without it, the size is ignored.
- **No seek.** The import reads the sample again from memory, with its partial lines and
  its quoted newlines. So an HTTP stream works too. The sample can read past the rows of a
  batch or of `limit`, but the import keeps only the rows asked for.
- **Your options win.** `delimiter`, `quotechar`, and `dialect` replace what the sniffer
  finds. Without `sniff=True`, the import reads commas, or the options that you give.
- **The header.** The sniffer does not guess whether the first row is a header: the first
  row names the columns, unless you give `fieldnames`.
- **When it fails.** When the sniffer finds no dialect, the import raises a `RefusedError`.
  Its message says to give a larger sample, or to turn sniffing off and give the CSV
  options. A larger sample can help, but the sniffer can still guess wrong. For a known
  format, leave sniffing off and give its options.
- **Errors.** An import with sniffing rolls back as one without: on an error, or when the
  loop stops early.

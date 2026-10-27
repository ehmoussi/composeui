# Importing CSV data

A table of a [SQLite model](sqlite-model.md) can import CSV data from a file or a URL. These
sections cover the table, its sources of CSV data, and how it finds the CSV dialect.

## A CSV table

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
  [`SqliteSource`](tables.md#rows-in-sqlite) of the rows, for a `SourceTableView`.
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
  rules of [`insert_batches`](sqlite-model.md): it yields the rows sent so far, and commits
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

## CSV files

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

## CSV URLs

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

## CSV dialect detection

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

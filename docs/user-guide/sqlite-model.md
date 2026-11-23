# A SQLite model

Views hold what is shown. Some data has many rows, relations between them, and queries over
them, for example runs and their results, or a catalog of parts. This data belongs in a
SQLite database of the app's own, with its own schema and SQL. A `SqliteDatabase` declares
its tables. A `DatabaseModel` declares the database with `per_session`: each user works on
a copy of their own, which the study saves and opens.

```python
import attrs

from composeui.core.sqlitemodel import (
    DatabaseModel,
    SqliteDatabase,
    SqliteTable,
    per_session,
    table,
)


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


class PipeDatabase(SqliteDatabase):
    runs = table(Runs)


class PipeModel(DatabaseModel):
    study = per_session(PipeDatabase)
```

Give the model to the app:
`run(PipeMainView, build_model=PipeModel, setup_model=PipeMainView.connect_model)`.
A `ModelApplication` (`QtModelApplication`, `TextualModelApplication`,
`WebModelApplication`) takes the same arguments. Callbacks that ask for `model` reach the
tables through the database (`model.study.runs.add(...)`).

- **One database per study.** A `DatabaseModel` declares at most one `per_session` database,
  and no table of its own: the tables go in the `SqliteDatabase`. The study saves the
  database as a file named after the model's attribute, `study.sqlite` here. Give
  `data_name` to keep another name, such as the `data.sqlite` of the studies saved before
  ComposeUI had `DatabaseModel`: `per_session(PipeDatabase, data_name="data.sqlite")`.
- **Transactions.** `with self.connection() as db:` commits once the block ends, and rolls
  back if the block raises. A block inside another block joins it. The threads take turns
  on the database's connection.
- **Separate reads.** `with self.reading() as db:` gives a connection that only reads, and takes no
  turn: it neither waits for a write nor holds one up. It reads the rows committed, not those of a
  transaction still open. The connection is reused: read each query's rows to the end in the block,
  else the next reader sees the rows as they were when the query started. A large table's
  [`SqliteSource`](tables.md#rows-in-sqlite) reads its rows this way.
- **Settings.** The database's `pragmas` is set on the connection of every study, because
  SQLite keeps these settings per connection, not in the file. Foreign keys and recursive
  triggers are on. `synchronous` is off, because the database is a scratch copy and the study
  file is written separately. The journal is `WAL`, so that `reading` reads during a write; the
  study file is saved in SQLite's default journal. Override `pragmas` to change them
  (`pragmas = {**SqliteDatabase.pragmas, "cache_size": -64000}`).
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
  "Run 3", and so on: the first name that the column does not hold, whatever its case. Use it
  for a row that the user adds, then renames.
- **Refusals.** When a constraint fails, the transaction is refused: `connection()` raises a
  `RefusedError` (`composeui.core.model`). Its message is the table's message for the
  constraint, from `refusals`, else the message of SQLite. `refusals` maps a part of the
  SQLite message to a message, for example
  `{"thin_wall": "its wall must be thinner than its radius"}`.
  A view shows the refusal in a [notification](building-views.md#notifications) with
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
      model.study.runs.changed.connect(self.show_runs, now=True)
  ```

- **Studies.** New starts an empty database. Save and Open (and `-f`) save and open the
  state of the views and the database together, as a zip archive with the app's `extension`.
  The database is a scratch copy in a temporary file. So the user's file changes only
  when the user saves it, and a failed save leaves the file whole. Opening checks everything
  first. When a file does not fit, the study stays as it was, and a notification says why.
- **Versions.** Raise the database's `schema_version` with every change to the tables. Add
  the step from the previous version to its `migrations` (`{1: add_stress_column}`). When the
  user opens a study saved by an older version, the database is brought up to date. A study
  saved by a newer version is refused.

  version is refused.
- **Opened databases are checked.** A study can come from anyone, such as a web upload or
  an email. Its database must be made as a new one is: the same tables with the same
  columns, and the same views, triggers, and indexes, with the same SQL. Otherwise it is
  refused, because a view or a trigger in the file would run in the app. So each migration
  must leave the database as a new one at its version. For example, it recreates a view from
  the same SQL as `create`. The `CHECK` and `REFERENCES` of a table are not compared,
  because `ALTER TABLE ... ADD COLUMN` cannot add all of them. Opening a database, its
  migrations included, stops after `open_time_limit` seconds (30 by default).
- **Writing from a job.** The function of a [job](threads.md) can write to
  the tables: the database's lock lets one thread at a time use the connection. After a commit,
  `job.call_on_main_thread` delivers the `changed` signal with the same
  [threading rules as other job callbacks](threads.md#how-jobs-behave). New and Open drop the
  jobs before they replace the database. Check `job.is_canceled` in the transaction that
  writes, so a canceled job never writes into the next study:

  ```python
  def sweep(job: Job[int], model: PipeModel, radii: list[float]) -> int:  # in its thread
      for count, radius in enumerate(radii):
          with model.study.runs.connection():
              if job.is_canceled:
                  return count
              model.study.runs.add(radius)  # joins the transaction
      return len(radii)
  ```

- **On the web,** the database of each session is deleted with the session.

[`src/examples/pipecatalogue.py`](../../src/examples/pipecatalogue.py) puts it together, on
every backend (`uv run python -m examples.pipecatalogue --backend qt`):

- The database checks the pipes of a catalog as a form in a
  [sidebar](organizing-the-window.md#sidebar) adds them.
- A [list of views](organizing-the-window.md#a-list-of-views) shows an expander per pipe, beside a
  tree of the pipes by material.
- A filtered query lists the pipes, with their mass from a SQL view that joins them to their
  material.
- Each pipe has an installation date, picked with a `DateInputView`, which the list can
  filter by. Studies saved before the date column existed get the column when they open,
  through a migration.

[`src/examples/pipesweep.py`](../../src/examples/pipesweep.py) writes to its database from a job
(`uv run python -m examples.pipesweep --backend qt`).

## A database shared by every session

A `per_session` database is the user's own: on the web, each session has a copy. Data that
every user reads and writes, such as the customers of a CRM, goes in a database that
`shared` declares instead. The process has one, which every session's model reaches:

```python
from pathlib import Path

from composeui.core.sqlitemodel import (
    DatabaseModel,
    SqliteDatabase,
    SqliteTable,
    per_session,
    shared,
    table,
)


class Customers(SqliteTable):
    create = "CREATE TABLE customer(id INTEGER PRIMARY KEY, name TEXT NOT NULL);"

    def add(self, name: str) -> None:
        with self.connection() as db:
            db.execute("INSERT INTO customer(name) VALUES (?)", (name,))

    def names(self) -> list[str]:
        return self.fetch_column("SELECT name FROM customer ORDER BY id")


class Notes(SqliteTable):
    create = "CREATE TABLE note(text TEXT NOT NULL);"


class Study(SqliteDatabase):
    notes = table(Notes)


class Crm(SqliteDatabase):
    customers = table(Customers)


class CrmModel(DatabaseModel):
    study = per_session(Study)  # each user's own, saved in the study
    crm = shared(Crm, location=Path("crm.sqlite"))  # one for every user, kept in a file


alice, bob = CrmModel(), CrmModel()  # two sessions' models
alice.crm.customers.add("Ada")
print(bob.crm.customers.names())  # ['Ada']
alice.close()
bob.close()
```

- **One per process.** The first model built opens the database, and runs its `migrations`
  then, once. Each model's attribute is the session's handle on it, of the database's class.
  A session that ends lets it go: the shared database never keeps a session.
- **Not in the study.** Save and Open leave it out, and New leaves it alone. Its writes are not
  [unsaved changes](building-views.md#unsaved-changes).
- **A file, or a temporary one.** With `location`, the database is kept in that file across the
  runs of the app. SQLite then waits for the disk at each commit (`synchronous = NORMAL`). A
  file of a newer version is refused, with `InvalidStateError`. The process closes the file
  once no session holds it, such as between two tests. The next model opens it again, without
  `fill`. Without `location`, the database is a temporary file, deleted as the process ends.
- **A file chosen as the model is built.** A callable `location` gives the file as each model
  is built, such as a file in a state folder that the app reads as it starts, or that each test
  sets: `shared(Crm, location=lambda: Path(os.environ["CRM_FOLDER"]) / "crm.sqlite")`. When
  the callable gives another file, the sessions built before keep the previous file. They and
  the new sessions don't see each other's writes.
- **Writes take turns.** The threads of every session take turns on its connection, as the
  threads of one session do. `reading` reads without waiting, during a write too.
- **Every session follows.** After a commit, the tables' `changed` is emitted in the session
  that wrote, as for a `per_session` database. Each other session then gets it on its own main
  thread, with the changes made meanwhile together. On the web, the user sees them at their next
  request, such as a click.
- **Text that other users wrote.** A table's Export CSV writes a text cell as it is. A
  spreadsheet runs a cell that starts with `=`, `+`, `-` or `@` as a formula. Check such text
  when a session writes it.
- **One field per database.** A model that declares the same shared database twice is refused,
  and so is a file that two classes, or two `read_only` values, share. A shared database's
  tables are declared in its class or added in its `__init__`: `add_table` on a session's
  handle is refused.

### Filled once, read-only

A database that every session reads, filled once, such as a large CSV file to query, declares
its rows in `fill`. With `read_only=True`, the sessions only read it:

```python
import contextlib

from composeui.core.jobs import Job

DATA_URL = "https://example.org/pickups.csv.gz"


class Pickups(SqliteDatabase):
    rows = table(PickupsTable)  # a CSVSqliteTable

    def fill(self, job: Job[None, int]) -> None:  # once, in a thread of its own
        with contextlib.closing(self.rows.fill_from_url(DATA_URL)) as batches:
            for count in batches:
                job.report_progress(count)


class PickupsModel(DatabaseModel):
    pickups = shared(Pickups, read_only=True)

    def load(self, job: Job[list[int], int]) -> list[int]:  # a task's function
        self.pickups.ready(job)  # the first session fills it, the others wait
        return self.pickups.rows.by_hour()
```

- **`ready(job)` waits for the fill,** in a job's thread. The first session's `ready` starts
  `fill` in a thread of its own, and the others wait for it. Each job gets the fill's progress.
  Until its `ready` returns, a session's queries raise `RuntimeError`. A database without
  `fill`, and a `per_session` one, are ready at once.
- **Kept in a file.** With `location`, `fill` runs only when the file doesn't exist yet. It
  fills a new file beside it, renamed to `location` once `fill` is over. The next runs of the
  app open the file without `fill`. To fill it again, delete the file before the app starts.
- **Canceled or failed.** A job canceled stops waiting and raises `JobCanceledError`. When no
  job waits any longer, the fill's job is canceled: read `job.is_canceled`, or call
  `job.raise_if_canceled()`, to stop early. A fill that fails fails each job that waits for it.
  A fill that stops leaves no file, and the next `ready` fills again. `fill` runs for every
  session, so `job.call_on_main_thread` raises `CalledInJobError` in it, as in a
  [`@shared_data` load](threads.md#data-shared-by-the-sessions).
- **`forget()`** gives the next sessions a new database, filled again, for example after the
  data changed. The sessions that have the previous one keep it. Its file is deleted once the
  last of them ends. A database kept in a file (`location`) and a `per_session` one can't be
  forgotten.
- **Read-only.** `fill` writes, before any session reads. Then a write of a session raises
  `ReadOnlyDatabaseError`, and `connection()` reads as `reading` does. A file of the app that
  is read-only, such as reference data, opens without a write:
  `shared(Materials, location=Path("materials.sqlite"), read_only=True)`. It must be at the
  database's `schema_version`, as it can't be brought up to date.

To import CSV data into a table of the database, see [Importing CSV data](csv-import.md).

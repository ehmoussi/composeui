# Benchmarks

These benchmarks measure the example apps against the [budgets](../ROADMAP.md#budgets) of the
roadmap, what a web session costs as an app grows, the web backend against other Python
frameworks, and what saving idle web sessions to disk gives. They are not part of the test
suite.

Run a benchmark before and after work on speed, or when someone reports a slow case. No schedule
refreshes the results: each result names its commit.

## What to measure

Add a benchmark for an example app when work on its speed needs one. Measure:

- the cold start, and the first useful render;
- the latency of a filter, a sort, and a chart's update;
- the size of the responses on the web;
- the memory of each session, and of the data that the sessions share;
- the throughput with concurrent sessions;
- the cleanup once a session closes.

Use a small dataset, the million-row SQLite table of
[`largetable.py`](../src/examples/largetable.py), and an uploaded dataset within the upload
limits. Publish each result with its versions, hardware, data and settings, as the sections
below do. When you compare with another Python dashboard framework, turn its caching on, and
report the differences between the workloads rather than credit every gap to the execution
model.

The hour move's budget is measured as `uber.py` measures it, with the 200 ms debounce of the
map's job. A browser can get the map's points up to 300 ms later, at its next poll of `/jobs`.

## The Uber pickups benchmark

[`uber.py`](uber.py) measures the two Uber pickups examples:

- [`uberpickups.py`](../src/examples/uberpickups.py) keeps the rows in SQLite.
- [`uberpickupsframe.py`](../src/examples/uberpickupsframe.py) keeps them in a Polars frame.

Both read the same CSV: the 1,028,136 pickups of September 2014. The benchmark downloads it
once to `~/.cache/composeui-bench/`, so that the network is not measured.

Each case is one example on one backend:

- **`core`:** a `ModelApplication` with no renderer. It measures the app's own work.
- **`web`:** the web backend, driven over HTTP by Starlette's `TestClient`. It also measures
  the rendering of the fragments and the size of each response.

Each case does these steps, in order:

1. **Import** the example's module.
2. **Load** the rows, until the jobs are over. On the web, a first page comes before.
3. **Move the hour** to 17 (the busiest), 2 (the quietest), 11, 8 and 23. Each move samples
   up to 10,000 points for the map. Since 0.3.0, it also filters the table to the hour.
4. **Show the table**, then **sort** it by latitude. On the core, **filter** it
   (`>40.75`), then **clear the filter**. On the web, **scroll** to row 5,000.

   On the core, the benchmark moves the slider and checks the box as a renderer does. It sets
   the view's attribute, then emits its signal (`value_changed`, `toggled`).

5. **Close** the model and drop the app (core only), then check that the main view is freed.

Each run is a process of its own, so that its memory is its own. The timed runs and the
memory run are separate, because `tracemalloc` slows Python down several times.

### Run it

Install the `web` and `dataframe` extras, then run:

```bash
uv sync --group dev --all-extras
uv run python benchmarks/uber.py --repeat 3 --output benchmarks/results/uber-<commit>.json
```

`--examples` and `--backends` select fewer cases. A timed run of a SQLite case takes about
15 s.

To measure another version, copy `uber.py` out of the repository first. Then check out the
version, such as the `v0.3.0` tag, and run the copy from the repository's root.

The JSON file holds the environment, a summary per case, and every run. For each step, the
summary gives:

- **`median_s` and `min_s`:** the time over the timed runs.
- **`kept_mib`:** the Python memory that the step keeps, measured by `tracemalloc`.
- **`peak_mib`:** the highest Python memory during the step, above its start.

## Results

Each case had 3 timed runs and 1 memory run, on two versions:

- **0.3.0:** the `v0.3.0` tag (`0fd0ef9`), in
  [`results/uber-v0.3.0.json`](results/uber-v0.3.0.json).
- **main:** `d321c3a` (0.3.1.dev27), 27 commits later, in
  [`results/uber-d321c3a.json`](results/uber-d321c3a.json).

The tables below compare these two versions. ["The hour index"](#the-hour-index) gives a later
change to the SQLite example.

The machine is an Intel Core i9-9900K (8 cores, 16 threads), with Linux in WSL2 and 15 GiB of
memory. The Python is 3.9.23. The times are medians.

### What changed in the examples

The examples do different work in the two versions:

- **The table.** In 0.3.0, the table shows all 1,028,136 rows. On main, it shows the rows of
  the hour picked, such as 73,373 rows for hour 17.
- **An hour move.** In 0.3.0, it samples the map's points. On main, it also gives the table a
  new source. The SQLite example samples the points in a job (`start_latest`), and the
  Polars example in the move's own request.
- **The filter.** The same filter (`lat` above 40.75) keeps 410,145 rows in 0.3.0, and 10,017
  rows of hour 23 on main.

Compare a step between the versions with this in mind: a sort on main sorts fewer rows, and
an hour move does more work.

### The SQLite example

| Step | Core, 0.3.0 | Core, main | Web, 0.3.0 | Web, main |
| --- | ---: | ---: | ---: | ---: |
| Import | 101 ms | 102 ms | 100 ms | 103 ms |
| First page | | | 28 ms | 55 ms |
| Load | 19.5 s | 20.3 s | 20.2 s | 21.8 s |
| Full page, loaded | | | 105 ms | 118 ms |
| Hour 17 | 569 ms | 1.59 s | 657 ms | 1.72 s |
| Hour 2 | 692 ms | 1.70 s | 751 ms | 1.79 s |
| Hour 11 | 608 ms | 1.64 s | 707 ms | 1.75 s |
| Hour 8 | 587 ms | 1.61 s | 671 ms | 1.72 s |
| Hour 23 | 610 ms | 1.66 s | 716 ms | 1.75 s |
| Show table | 0.0 ms | 0.1 ms | 11 ms | 12 ms |
| Sort | 1.83 s | 853 ms | 1.82 s | 863 ms |
| Filter | 775 ms | 411 ms | | |
| Clear filter | 1.82 s | 844 ms | | |
| Scroll | | | 13 ms | 13 ms |
| Close | 11 ms | 10 ms | | |

On the web, a step lasts until no job runs after a poll of `/jobs`. On main, the SQLite
example's hour move therefore includes the job that samples the map's points. A browser polls
every 300 ms (`JOBS_POLL_MS`), so it gets the points up to 300 ms later.

### The Polars example

| Step | Core, 0.3.0 | Core, main | Web, 0.3.0 | Web, main |
| --- | ---: | ---: | ---: | ---: |
| Import | 186 ms | 185 ms | 176 ms | 181 ms |
| First page | | | 6 ms | 8 ms |
| Load | 273 ms | 151 ms | 384 ms | 252 ms |
| Full page, loaded | | | 124 ms | 120 ms |
| Hour 17 | 21 ms | 31 ms | 112 ms | 137 ms |
| Hour 2 | 14 ms | 19 ms | 69 ms | 83 ms |
| Hour 11 | 21 ms | 27 ms | 117 ms | 142 ms |
| Hour 8 | 20 ms | 27 ms | 110 ms | 129 ms |
| Hour 23 | 20 ms | 26 ms | 115 ms | 132 ms |
| Show table | 0.0 ms | 0.1 ms | 11 ms | 11 ms |
| Sort | 193 ms | 11 ms | 209 ms | 26 ms |
| Filter | 83 ms | 8 ms | | |
| Clear filter | 189 ms | 10 ms | | |
| Scroll | | | 21 ms | 14 ms |
| Close | 0.0 ms | 0.0 ms | | |

### Memory

| Measure | Version | SQLite, core | SQLite, web | Polars, core | Polars, web |
| --- | --- | ---: | ---: | ---: | ---: |
| Process peak (RSS) | 0.3.0 | 101 MiB | 118 MiB | 393 MiB | 447 MiB |
| | main | 97 MiB | 112 MiB | 285 MiB | 299 MiB |
| Python peak (`tracemalloc`) | 0.3.0 | 8.3 MiB | 70.9 MiB | 22.4 MiB | 81.4 MiB |
| | main | 8.7 MiB | 25.5 MiB | 22.7 MiB | 37.1 MiB |
| Python peak of a sort | 0.3.0 | 43.4 MiB | 43.6 MiB | 43.2 MiB | 43.4 MiB |
| | main | 1.6 MiB | 1.8 MiB | 1.5 MiB | 1.8 MiB |

`tracemalloc` sees only Python's memory. It does not see SQLite's pages or the Polars frame,
which are outside Python. Use the process peak for the total.

The table keeps the ordered IDs of its rows in Python. A sort of all 1,028,136 rows (0.3.0)
peaks at about 43 MiB. A sort of one hour's rows (main) peaks below 2 MiB. On both versions
and both examples, the main view is freed when the app closes.

### Web response sizes

| Response | SQLite, 0.3.0 | SQLite, main | Polars, 0.3.0 | Polars, main |
| --- | ---: | ---: | ---: | ---: |
| First page, before the load | 14 KB | 15 KB | 10 KB | 10 KB |
| Polls until the end of the load | 239 KB | 241 KB | 239 KB | 240 KB |
| Full page, loaded | 248 KB | 249 KB | 246 KB | 247 KB |
| Hour move | 101–183 KB | 57 KB | 101–183 KB | 158–240 KB |
| Polls after an hour move | 32 B | 101–183 KB | 32 B | 32 B |
| Show table, sort, scroll | 52–54 KB | 52–55 KB | 52–54 KB | 52–55 KB |

A poll with nothing to send is 32 B.

### The hour index

This change adds an index on the hour of each row to the SQLite example, on top of `374e6f9`.
Its results are in [`results/uber-hour-index.json`](results/uber-hour-index.json), with the same
machine, Python, rows and points. The Polars example does not change, and was not measured
again.

| Step | Core, before | Core, with the index | Web, before | Web, with the index |
| --- | ---: | ---: | ---: | ---: |
| Hour 17 | 1.59 s | 308 ms | 1.72 s | 399 ms |
| Hour 2 | 1.70 s | 232 ms | 1.79 s | 289 ms |
| Hour 11 | 1.64 s | 274 ms | 1.75 s | 371 ms |
| Hour 8 | 1.61 s | 275 ms | 1.72 s | 363 ms |
| Hour 23 | 1.66 s | 269 ms | 1.75 s | 367 ms |
| Sort | 853 ms | 58 ms | 863 ms | 71 ms |
| Filter | 411 ms | 21 ms | | |
| Clear filter | 844 ms | 58 ms | | |
| Load | 20.3 s | 20.2 s | 21.8 s | 21.0 s |
| Process peak (RSS) | 97 MiB | 97 MiB | 112 MiB | 112 MiB |

- **The debounce is about 200 ms of each move.** `start_latest` waits 200 ms before it samples
  the map's points. A profile of one run on the core gives 19 to 49 ms for the points' queries,
  and 8 to 47 ms for the rest of the move.
- **A browser can get the points later.** The times above stop after a poll of `/jobs`, sent
  as soon as the job ends. A browser polls every 300 ms.
- **A study costs more.** In one separate measurement, the saved database grows from 51.6 to
  62.4 MiB, and opening a study takes 1.64 s instead of 0.35 s. `benchmarks/uber.py` does not
  measure this.

### The faster CSV import

This change makes `CSVSqliteTable` faster, on top of the hour index. Its results are in
[`results/uber-csv-import.json`](results/uber-csv-import.json), with the same machine, Python,
rows and points. The Polars example does not use this code, and was not measured again.

| Measure | Core, before | Core, after | Web, before | Web, after |
| --- | ---: | ---: | ---: | ---: |
| Load | 20.2 s | 9.67 s | 21.0 s | 9.95 s |
| Python peak of the load | 48.9 MiB | 54.3 MiB | 47.6 MiB | 53.0 MiB |
| Process peak (RSS) | 97 MiB | 102 MiB | 112 MiB | 117 MiB |

- **Most of the gain comes from repeated dates.** The file has 42,907 distinct dates in its
  1,028,136 rows. An import keeps each date parsed, and its text, until the import ends. A file
  whose dates rarely repeat gains less. This was not measured.
- **Each row keeps its checks.** The row class still converts and validates each row.
- **The web's margin is small.** Two runs can differ by about 10%, so a run can take more than
  the 10 s budget of [the roadmap](../ROADMAP.md#budgets).

### Findings

- **The hour index removed most of a SQLite hour move's time.** A move took 1.6 to 1.8 s on
  `d321c3a`, and took 0.6 to 0.75 s in 0.3.0, which did not filter the table. Each of its three
  queries scanned the 1,028,136 rows, and computed `strftime('%H', date_time)` on each row. With
  the index, a move takes 0.23 to 0.4 s.
- **A SQLite load took about 20 s on both versions, and takes about 10 s since the faster CSV
  import.** The import parses and checks each row in Python, now at about 100,000 rows per
  second. Polars reads the same file in 0.15 to 0.4 s, but its process takes about three times
  the memory.
- **A sort or a filter of a SQLite source took 0.4 to 1.8 s before the hour index.** With it,
  a sort takes 58 to 71 ms, and a filter 21 ms. The same operations on Polars took 8 to 26 ms
  on `d321c3a`. The time follows the number of rows that the table reads.
- **Main uses less memory.** The Polars process peaks at 285 MiB instead of 393 MiB. On
  the web, the process's Python memory peaks at 25 to 37 MiB instead of 71 to 81 MiB.
- **The map's points make most of the web's responses.** Up to 10,000 points give 100 to
  180 KB for each hour move. A response that changes only the table is about 55 KB.

### Limits

- **One machine, one Python.** The results come from Python 3.9 in WSL2. Other machines
  and versions give other times. Two runs of the same case can differ by about 10%, and a
  first page by more.
- **No network and no browser.** `TestClient` calls the app in the same process. A real
  browser adds the network, the page's parsing and drawing, and the poll's delay.
- **One session.** This benchmark does not measure concurrent sessions, or the memory of each
  session. See ["The web sessions benchmark"](#the-web-sessions-benchmark).
- **The web's filter is not measured.** The filter editor posts a form that the benchmark
  does not send.
- **The web's cleanup is not measured here.** This benchmark does not end a web session. See
  ["The web sessions benchmark"](#the-web-sessions-benchmark).

## The web sessions benchmark

[`sessions.py`](sessions.py) measures several web sessions of the two Uber pickups examples. It
has three cases:

- **Cleanup.** One process opens 4 sessions through Starlette's `TestClient`, one after another.
  Each session loads the rows and moves the hour once. Then all the sessions expire.
- **Left during a load.** A session expires 0.1 to 4 s after it opens. Each run is a process of
  its own, because the process can crash.
- **Concurrency.** A Uvicorn server runs in one process, and one HTTP client per session runs in
  another. All the sessions load together, then each session moves the hour without a pause.

### Run the sessions benchmark

The benchmark reads `/proc`, so it runs on Linux only.

```bash
uv run python benchmarks/sessions.py --output benchmarks/results/sessions-<commit>.json
```

The defaults run 1, 2 and 4 sessions once, and each session moves the hour 5 times. They take
about 6 minutes. `--examples`, `--sessions`, `--levels`, `--repeat`, `--rounds` and
`--left-repeat` change this. With `--levels 8`, the SQLite example takes about 20 minutes for its
load alone. The JSON file holds a summary, not each sample.

### Sessions results

The results come from `3c647a3`, on the same machine and Python as above, in
[`results/sessions-3c647a3.json`](results/sessions-3c647a3.json). They ran with
`--levels 1 2 4 8 --repeat 2 --rounds 3 --left-repeat 3`, on a longer version of the script that
also measured Python's memory. Other work ran on the machine during part of these runs. A second
run of 4 SQLite sessions, with nothing else running, gives a load of 213 s and a move of 4.2 s.

What each session costs, after the first session:

| Measure | SQLite | Polars |
| --- | ---: | ---: |
| Load | 10 s | 0.22 s |
| Process memory (RSS) | 9.8 MiB | 54 MiB |
| Temporary files | 125 MiB | none |
| Open file descriptors | 5 | 0 |
| Time to close | 11 ms | 0.5 ms |

The first session also takes 34 MiB (SQLite) or 223 MiB (Polars) of process memory. Each session
loads its own copy of the rows.

A session's end frees its main view and its model:

- **Nothing stays.** All 4 main views are freed, and no temporary file stays. The file
  descriptors return to 8.
- **The process memory falls little.** With 4 SQLite sessions, it falls from 113 to 96 MiB. With
  4 Polars sessions, it falls from 458 to 455 MiB. This benchmark does not show why.

Sessions at once, with medians:

| Sessions | SQLite load | SQLite move | SQLite moves/s | SQLite peak | Polars load | Polars move | Polars moves/s | Polars peak |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 9.5 s | 0.37 s | 2.7 | 113 MiB | 0.46 s | 0.21 s | 4.9 | 292 MiB |
| 2 | 17.7 s | 0.43 s | 4.0 | 147 MiB | 0.57 s | 0.28 s | 7.4 | 523 MiB |
| 4 | 206 s | 3.9 s | 0.8 | 223 MiB | 0.62 s | 0.47 s | 8.9 | 1,012 MiB |
| 8 | 1,083 s | 38 s | 0.2 | 385 MiB | 1.0 s | 0.96 s | 8.9 | 1,922 MiB |

A move lasts until a poll of `/jobs` shows that no job runs. The benchmark polls every 50 ms
during a move, and every 300 ms during a load.

A session left during a SQLite load, in 3 runs at each moment:

| Seconds after it opens | `3c647a3` | With the fix |
| ---: | --- | --- |
| 0.1 | The job fails 3 times | Clean 3 times |
| 0.5 | The job fails 3 times | Clean 3 times |
| 1 | The process crashes 3 times | Clean 3 times |
| 2 | The job fails 3 times | Clean 3 times |
| 4 | The job fails 3 times | Clean 3 times |

- **The crash depends on timing.** In a separate check of `3c647a3` with the same moments, 5 of
  15 runs crashed, at 1 s and at 2 s. The other 10 runs ended with a failed job.
- **The fix.** With the change that `d852cea` merged, the main view is freed within 1.5 s, and no
  temporary file stays.

### Sessions findings

- **The SQLite example does not scale past 2 sessions at once.** From 2 to 4 sessions, a load
  takes about 12 times as long, and a move about 9 times as long. Moves also become slower after
  the loads are over. ["Why SQLite sessions slow down"](#why-sqlite-sessions-slow-down) gives the
  cause.
- **The budget holds for one SQLite session.** A move takes 0.37 s, within the 500 ms budget of
  [the roadmap](../ROADMAP.md#budgets). With 2 sessions, the median is 0.43 s, but the 95th
  percentile is 0.80 s. Polars stays within the budget up to 4 sessions at the median, and its
  95th percentile at 4 sessions is 0.54 s.
- **Polars pays with memory.** Its sessions move the hour faster, but 8 sessions take about
  1.9 GiB. Throughput stops growing at about 9 moves per second, from 4 sessions.
- **Disk limits the SQLite example.** At 125 MiB per session, the 1,000 sessions of
  `max_sessions` would take about 125 GB.

### Why SQLite sessions slow down

The cause is the hand-over of Python's global interpreter lock (GIL) between CPUs, for nearly each
row. As the measures below suggest, each row that SQLite reads or writes gives the GIL to another
thread. On several CPUs, the system must wake that thread on another CPU, which is slow.

These checks ran apart, with one `UberPickupsModel` per worker and no web code. A load reads the
first 300,000 rows. A query run calls `pickup_points` 10 times. The times are of the slowest
worker, in one run.

| 4 workers | Load | Query run |
| --- | ---: | ---: |
| One worker alone | 2.9 s | 0.18 s |
| 4 threads, all CPUs | 58 s | 22 s |
| 4 threads, 4 CPUs | 59 s | 22 s |
| 4 threads, 2 CPUs | 9.8 s | 3.6 s |
| 4 threads, 1 CPU | 10.4 s | 0.75 s |
| 4 processes, all CPUs | 3.0 s | 0.19 s |

- **The time goes to the system.** A load of 4 threads on all CPUs takes 70 s of system time and
  4.6 million voluntary context switches. On one CPU, it takes 0.3 s and 5,891.
- **The switch interval does not matter.** `sys.setswitchinterval` from 0.05 ms to 50 ms gives
  55 to 61 s for the load.
- **The disk does not matter.** A database in `/dev/shm` gives 56.5 s for the load.
- **Python 3.14 behaves the same.** 4 threads on all CPUs give 61 s for the load and 20 s for the
  query run. One worker alone takes 1.8 s and 0.11 s.

With the Uvicorn server alone on one CPU, in one run of the concurrency case:

| Sessions | Load, all CPUs | Load, one CPU | Move, all CPUs | Move, one CPU |
| ---: | ---: | ---: | ---: | ---: |
| 4 | 206 s | 36 s | 3.9 s | 0.67 s |
| 8 | 1,083 s | 74 s | 38 s | 1.3 s |

The move on one CPU is still above the 500 ms budget. The scripts of these checks are not in the
repository. A machine without a virtual machine's layer can pay less for each hand-over: all of
these results come from WSL2. Keeping a server on one CPU was not measured with Polars, whose own
threads it would limit.

### Sessions limits

- **No pause between moves.** Each client moves the hour as soon as the last move ends, which is
  more than a real user does. Real sessions with pauses can do better. This was not measured.
- **Forced expiry.** The benchmark sets the store's private `_ttl` to 0 to end the sessions. In
  use, an open page's polls keep its session alive.
- **One machine, one Python.** The results come from Python 3.9 in WSL2, with few runs.
- **One server process.** The benchmark does not measure several processes.
- **No browser.** The clients send requests only. They do not parse or draw the pages.

## The session size benchmark

[`sizes.py`](sizes.py) measures what a web session costs as an app grows. Its apps are built
from one row: a label, a text input, an int input, a checkbox and a button. They grow in two
ways:

- **Sections.** One page of 2 to 65 sections of 10 rows, all shown.
- **Pages.** A router of 1 to 20 pages of 10 rows, one shown.

For each app, Starlette's test client opens 20 sessions in the benchmark's own process. The
memory of a session is what Python allocates for it, measured by `tracemalloc`. The benchmark
also times 30 first pages, and weighs one.

### Run the size benchmark

```bash
uv run python benchmarks/sizes.py --output benchmarks/results/sizes-<commit>.json
```

`--sections` and `--pages` choose the sizes. It takes about a minute. To measure another
version, set `PYTHONPATH` to that version's `src` folder: the results then name the folder that
ComposeUI was imported from (`imported_from`), and the checkout's commit.

### Size results

The results come from Python 3.9.23 on the same machine as above, for two versions:

- **`399c2d5`:** before the work on the sessions' memory, in
  [`results/sizes-399c2d5.json`](results/sizes-399c2d5.json).
- **`c29c765`:** with the shared signals and handler tables (#236) and the pages and tabs built
  once shown (#237), in [`results/sizes-c29c765.json`](results/sizes-c29c765.json).

| App | Views | Memory, `399c2d5` | Memory, `c29c765` | First page, `399c2d5` | First page, `c29c765` |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2 sections | 133 | 268 KiB | 123 KiB | 15 ms | 15 ms |
| 10 sections | 621 | 1,185 KiB | 497 KiB | 53 ms | 54 ms |
| 40 sections | 2,451 | 4,632 KiB | 1,903 KiB | 197 ms | 204 ms |
| 65 sections | 3,976 | 7,532 KiB | 3,102 KiB | 316 ms | 329 ms |
| 1 page | 74 | 161 KiB | 83 KiB | 13 ms | 14 ms |
| 5 pages | 322 | 627 KiB | 187 KiB | 24 ms | 21 ms |
| 10 pages | 632 | 1,209 KiB | 320 KiB | 37 ms | 30 ms |
| 20 pages | 1,252 | 2,372 KiB | 579 KiB | 65 ms | 49 ms |

### Size findings

- **A session's memory grows with its views.** A view costs about 1.9 KiB in `399c2d5`, and
  0.8 KiB in `c29c765`.
- **Pages not shown cost less.** With 20 pages, a session takes 76% less memory, and its first
  page 25% less time, as only the shown page is built.
- **A page that shows every view takes as long as before.** Its time goes to building the views
  and their HTML: 1.1 MiB of HTML for 65 sections.

## The frameworks benchmark

[`frameworks.py`](frameworks.py) compares the web backend with Streamlit, Panel and Dash on one
app of 20 pages of 10 rows. Each row has a label, a text input, an int input, a checkbox and an
Apply button, which writes "Applied" and the row's number in the label. Each framework has its
twin of the app in [`twins/`](twins), written as that framework's users write apps:

- **ComposeUI:** a `Router` of `PageView`s.
- **Streamlit:** `st.navigation`, its pages built by the script.
- **Panel:** `pn.Tabs` with `dynamic=True`, which draws only the shown tab.
- **Dash:** links, and a callback that builds the page. Gunicorn serves it, with one worker and
  8 threads.

Each framework runs its own server, in a virtual environment of its own, on the same Python. The
benchmark makes the environments with `uv`, at the versions that `PINS` names, and keeps them
in `~/.cache/composeui-bench/frameworks/`. Headless Chromium drives each app through
Playwright, as a user does. The benchmark reads the server's memory and CPU time from Linux's
`/proc`, for the whole process tree. For each framework, a new server for each run:

- **Start:** from the server's launch to its first answer.
- **First page:** a new browser context, until the page's ten Apply buttons show. The median of
  10.
- **Bytes:** what a new browser context receives for its first page, HTTP and WebSocket.
- **Click:** an Apply, until its label says so. The median of 10.
- **Page switch:** a link, or a tab on Panel, until the page's buttons show. The median of 10.
- **Bytes per interaction:** what the page sends and receives for a click, a page switch, and a
  text typed into a row's input, then Tab. The bodies of the HTTP requests and responses, as on
  the wire, and the WebSocket frames, without headers. The median of 6, each measured from 1 s
  of quiet before it to 1 s after.
- **Per session:** the memory and the CPU time of 50 sessions kept open, per session.
- **Explored:** the memory of 10 sessions that opened each page, per session.

### Run the frameworks benchmark

It needs Linux, `uv`, and Playwright's Chromium:

```bash
uv run --group browser playwright install chromium
uv run --group browser python benchmarks/frameworks.py \
    --output benchmarks/results/frameworks-<commit>.json
```

The defaults run each framework 3 times, on Python 3.12, in about 40 minutes. `--frameworks`
chooses the other frameworks, `--python` the servers' Python, and `--commits` adds older
commits of ComposeUI, which `git archive` extracts. Their dependencies are the checkout's.

### Frameworks results

The results come from `4bbf7d7`, with each server on Python 3.12, Chromium 148, on the same
machine as above, in [`results/frameworks-4bbf7d7.json`](results/frameworks-4bbf7d7.json). The
times are medians of 3 runs, whose memory per session differs by 1% at most for ComposeUI and
Panel. The bytes are the same in the 3 runs, except for a page switch: what ComposeUI receives
differs by 2% at most, and what Panel sends by 16%. The `399c2d5` column comes from an earlier run, on `b5a68c9`.

| Measure | ComposeUI `4bbf7d7` | ComposeUI `399c2d5` | Streamlit 1.67.0 | Panel 1.10.0 | Dash 4.5.0 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Start | 0.4 s | 0.5 s | 0.5 s | 1.6 s | 0.4 s |
| Idle server | 50 MiB | 58 MiB | 63 MiB | 166 MiB | 83 MiB |
| First page | 139 ms | 144 ms | 984 ms | 1,023 ms | 186 ms |
| Bytes, first page | 64 KiB | 63 KiB | 2,682 KiB | 3,375 KiB | 1,119 KiB |
| Click | 67 ms | 67 ms | 128 ms | 66 ms | 66 ms |
| Page switch | 67 ms | 67 ms | 153 ms | 310 ms | 66 ms |
| Memory per session | 401 KiB | 1,818 KiB | 110 KiB | 14,938 KiB | 14 KiB |
| CPU time per session | 63 ms | 79 ms | 228 ms | 868 ms | 23 ms |
| Memory per session, every page opened | 652 KiB | 1,739 KiB | 419 KiB | 8,172 KiB | 4 KiB |

The bytes of each interaction, sent and received:

| Interaction | ComposeUI | Streamlit 1.67.0 | Panel 1.10.0 | Dash 4.5.0 |
| --- | ---: | ---: | ---: | ---: |
| Click, sent | 11 B | 1,794 B | 240 B | 332 B |
| Click, received | 81 B | 15,816 B | 261 B | 88 B |
| Page switch, sent | 15 B | 107 B | 1,521 B | 213 B |
| Page switch, received | 1,271 B | 15,812 B | 34,074 B | 6,024 B |
| Text typed, sent | 45 B | 1,741 B | 254 B | 0 B |
| Text typed, received | 172 B | 15,812 B | 128 B | 0 B |

The earlier runs are in [`results/frameworks-b5a68c9.json`](results/frameworks-b5a68c9.json),
which names the commit of the benchmark's branch, `d93c2c3`, and in
[`results/frameworks-c29c765.json`](results/frameworks-c29c765.json). On `b5a68c9`, ComposeUI
measured as on `4bbf7d7`: 401 KiB per session, 647 KiB once every page was opened. On
`c29c765`, before the signals made on their first read (#239), a session took 491 KiB, 743 KiB
once every page was opened, and 69 ms of CPU time, and its first page 143 ms.

The earlier runs counted fewer bytes for a first page. Their counter waited with `time.sleep`,
during which Playwright doesn't give the page's events, and missed the requests that ended then.
For Dash, they measured 310 to 520 KiB.

### Frameworks findings

- **ComposeUI's first page is the fastest and the lightest.** It sends 64 KiB, against 1.1 MiB
  for Dash and 2.6 to 3.3 MiB for Streamlit and Panel.
- **A click takes the floor's time,** on ComposeUI, Panel and Dash, and a page switch on
  ComposeUI and Dash. Streamlit takes about twice as long, as it runs its script again. A page
  switch on Panel takes 5 times as long.
- **ComposeUI's interactions are the lightest.** A click sends 11 B and receives 81 B, against
  332 B and 88 B for Dash, and 1.8 KiB and 15.4 KiB for Streamlit. A page switch receives
  1.2 KiB, against 5.9 KiB for Dash, 15.4 KiB for Streamlit and 33 KiB for Panel.
- **ComposeUI sends each change of an input,** 45 B, because its server keeps the field's value.
  Dash sends a value only to a callback that reads it, and this app has none for the input.
  Streamlit runs its script again, and receives 15.4 KiB.
- **A session of ComposeUI takes 3.6 times Streamlit's memory,** and 1.6 times once every page
  was opened. It takes a little more than a quarter of Streamlit's CPU time, and 37 times less
  memory than Panel's.
- **With `session_idle`, an idle session of ComposeUI leaves the memory.** It takes about 83 KiB
  on disk instead (see [the long-running benchmark](#the-long-running-benchmark)). The gap with
  Streamlit stays for the active sessions.
- **Dash keeps almost nothing per session.** Its server holds no state for a session, so it
  cannot keep a session's jobs or data either.

### Frameworks limits

- **An app without data.** The app holds widgets only. With data, how each framework loads and
  keeps it decides most of the memory. Measure a data app the same way before you compare the
  frameworks in general.
- **The frameworks as written, not tuned.** No caching, and each framework's default server.
- **Different models.** Dash keeps no state on the server: a browser sends what each callback
  needs. Streamlit keeps the values of the widgets that a session showed, and runs the script
  again on each event. ComposeUI and Panel keep each session's views.
- **An empty cache.** Each first page comes to a new browser context, which loads the
  framework's scripts. A returning user's browser has them.
- **A floor.** A click and a page switch take at least about 66 ms in this setup, whatever the
  framework: Playwright and the browser take most of it.
- **Bytes without headers.** An interaction of ComposeUI or Dash is an HTTP request, whose
  headers the table leaves out: about 1.5 KiB for a ComposeUI click, with the session cookie.
  Streamlit and Panel send theirs over a WebSocket, whose frames have almost no headers.
- **One machine.** The results come from one machine, in WSL2.

## The idle sessions benchmark

[`idle_sessions.py`](idle_sessions.py) measures what `session_idle` gives: the memory that saving
idle sessions to disk frees, and the time to save and wake them. It serves the frameworks
benchmark's app with Uvicorn, in a process of its own, and drives it with headless Chromium.
Each case opens two batches of sessions, one after the other, on a new server:

- **Kept:** the first batch stays in memory while the second opens.
- **Hibernated:** one sweep saves the first batch to disk before the second opens. The case
  checks that each session and its main view are freed.

Python rarely gives the memory that it frees back to the system. Its small objects live in
arenas, and an arena goes back only once all of its objects are freed. So the server's RSS
doesn't drop after a sweep, and the drop can't measure the freed memory. The second batch shows
it instead: it reuses it. The benchmark compares the RSS of the two cases once both batches are
open, and also reads Python's allocated blocks.

Each user types in an input. After the second batch, the hibernated case reloads the page of
each session of the first batch, which wakes it. It checks the input's value, the address, and
the session cookie.

### Run the idle sessions benchmark

It needs Linux, `uv`, and Playwright's Chromium:

```bash
uv run --group browser python benchmarks/idle_sessions.py \
    --output benchmarks/results/idle-sessions-<commit>.json
```

The defaults run batches of 50 sessions on the first page, and batches of 10 sessions that open
every page, 3 times each, in about 6 minutes. `--sessions`, `--explorers` and `--repeat` change
this.

### Idle sessions results

The results come from `4bbf7d7`, with the server on Python 3.12, Chromium 148, on the same
machine as above, in [`results/idle-sessions-4bbf7d7.json`](results/idle-sessions-4bbf7d7.json).
The memory is the median of 3 runs, which differ by 0.1 MiB at most.

| Measure | 50 sessions, first page | 10 sessions, every page |
| --- | ---: | ---: |
| First batch | 22.9 MiB | 10.5 MiB |
| Second batch, first one kept | 18.3 MiB | 7.3 MiB |
| Second batch, first one saved | 0.1 MiB | 0.2 MiB |
| Both batches, first one kept | 41.2 MiB | 17.9 MiB |
| Both batches, first one saved | 29.6 MiB | 15.8 MiB |
| Memory saved | 11.5 MiB | 2.0 MiB |
| On disk per session | 83 KiB | 83 KiB |
| Save per session | 18 ms | 34 ms |
| Wake, page reload (median) | 140 ms | 138 ms |

### Idle sessions findings

- **The second batch reuses the memory of the first.** It takes almost nothing once the first
  batch is on disk.
- **The first sweep costs about 5 to 7 MiB, once per process.** Saving makes `cattrs` generate
  its functions for each view class, and they stay. This cost takes most of the saving with 10
  sessions. Later sweeps don't pay it.
- **A session on disk takes 83 KiB,** whether it opened one page or all of them: its study holds
  the views of every page.
- **A woken page loads as fast as a first page,** 140 ms against 141 ms in the frameworks
  benchmark.

### Idle sessions limits

- **A sweep on demand.** The benchmark sets `session_idle` to 0 for one sweep, once the requests
  have ended. The server's own timer, and sessions that come and go during a sweep, are in the
  long-running benchmark below.
- **The reload only.** A session also wakes on an action from a page that was not reloaded. The
  server then answers with `HX-Refresh`, which the benchmark doesn't measure.
- **An app without data.** A model's data adds to what a session saves and frees.

## The long-running benchmark

[`hibernation_soak.py`](hibernation_soak.py) runs a server as in a deployment, with and without
`session_idle`, and reads its memory over time. Uvicorn serves the frameworks benchmark's app in a
process of its own. Users arrive at a steady rate. Each user:

1. opens the app and types in an input;
2. opens 3 pages by their tabs and clicks Apply;
3. leaves the tab idle.

One user in 4 comes back 120 s after arriving. It reloads its page, checks the page and its
input's value, and types again. In the hibernated mode, this reload wakes the session from disk.
Apply's label isn't checked: a label is UI text, which a study doesn't keep.

The clients send HTTP requests as htmx does, without a browser. The server's own timer saves the
idle sessions. `session_ttl` is 24 hours, so no session ends. Every second, the benchmark reads the
server's RSS and the size of its saved sessions, until 90 s after the last request.

### Run the long-running benchmark

It reads `/proc`, so it runs on Linux only. It needs `uv`:

```bash
uv run python benchmarks/hibernation_soak.py \
    --output benchmarks/results/hibernation-soak-<commit>.json
```

The defaults run 600 users, 2 per second, with `session_idle` at 30 s in the hibernated mode.
Each mode runs once, in about 17 minutes for both. `--users`, `--rate`, `--pages`, `--idle`,
`--come-back`, `--back-after` and `--settle` change this.

### Long-running results

The results come from `4bbf7d7`, with the server on Python 3.12, on the same machine as above,
in [`results/hibernation-soak-4bbf7d7.json`](results/hibernation-soak-4bbf7d7.json). Each mode
ran once.

| Measure | Kept in memory | `session_idle = 30` |
| --- | ---: | ---: |
| Server RSS at the start | 46 MiB | 46 MiB |
| Server RSS after 600 users | 301 MiB | 112 MiB |
| On disk after 600 users | 0 MiB | 49 MiB |
| First page, median and p95 | 39 ms, 70 ms | 38 ms, 137 ms |
| Action, median and p95 | 4.8 ms, 5.7 ms | 4.9 ms, 13.2 ms |
| Action, slowest | 17 ms | 84 ms |
| Returning user's reload, median and p95 | 34 ms, 39 ms | 126 ms, 209 ms |

Without `session_idle`, the server's RSS grows by 0.42 MiB for each user, until the last one
arrives. With it, the RSS grows quickly for the first minute, then slowly, and stops at 112 MiB.
At 2 users per second, the sessions of the last 30 to 45 s are in memory, about 60 to 90 of them.
The server keeps the memory that this many live sessions took at their peak, and reuses it.

### Long-running findings

- **The memory follows the active users, not all the users.** With `session_idle`, 600 users
  took 66 MiB above the idle server, against 255 MiB without it. More users who leave their tabs
  idle add disk, not memory.
- **A session on disk takes about 83 KiB,** as in the idle sessions benchmark.
- **The sweeps slow some requests down.** A sweep saves sessions in a thread, which shares
  Python's interpreter with the requests. The median doesn't change, but the p95 of an action
  goes from 5.7 to 13 ms, and the slowest action takes 84 ms.
- **A returning user waits for the wake.** Its reload takes 126 ms instead of 34 ms, without the
  browser's time.

### Long-running limits

- **One run of each mode.** The RSS curves are smooth, but the p95 and the slowest times can
  change from run to run.
- **Without a browser.** The times leave out the browser's work, and the page's scripts. A
  returning user's browser also takes its time to draw the page.
- **An app without data.** A model's data adds to what a session saves, frees and wakes.
- **One rate.** The memory with `session_idle` depends on the users active at once. Their number
  is the arrival rate times the sum of `session_idle` and the sweep's interval.

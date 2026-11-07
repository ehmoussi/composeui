# Benchmarks

These benchmarks measure the example apps, against the [budgets](../ROADMAP.md#budgets) of the
roadmap. They are not part of the test suite.

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

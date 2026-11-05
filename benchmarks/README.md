# Benchmarks

These benchmarks measure the example apps. They give the baseline that the milestones of
[the roadmap](../ROADMAP.md) report against (M0). They are not part of the test suite.

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
30 s.

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

### Findings

- **A SQLite hour move takes 1.6 to 1.8 s on main, 0.6 to 0.75 s in 0.3.0.** On main, it filters the
  table too. Each of its three queries scans the 1,028,136 rows: it computes
  `strftime('%H', date_time)` on each row, and no index helps. The table's order (about
  0.8 s) runs in the slider's request. The map's points (about 0.9 s, two scans) run in a
  job.
- **A SQLite load takes about 20 s on both versions.** The CSV import parses and checks each
  row in Python, at about 50,000 rows per second. Polars reads the same file in 0.15 to
  0.4 s, but its process takes three to four times the memory.
- **A sort or a filter of a SQLite source takes 0.4 to 1.8 s.** The same operation on
  Polars takes 8 to 210 ms. The time follows the number of rows that the table shows.
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
- **One session.** The benchmark does not measure concurrent sessions, or the memory of each
  session.
- **The web's filter is not measured.** The filter editor posts a form that the benchmark
  does not send.
- **The web's cleanup is not measured.** The benchmark does not end a web session.

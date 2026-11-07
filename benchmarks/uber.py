"""Measure the two Uber pickups examples against the budgets of ROADMAP.md.

Each case runs in a process of its own, so that its memory is its own. A case builds the
app on a backend ("core": no renderer; "web": Starlette's test client), loads the
September 2014 pickups (1,028,136 rows), moves the hour, sorts and filters the table, and
closes the app. Timed runs and the memory run are separate: `tracemalloc` slows Python
down several times.

    uv run python benchmarks/uber.py --repeat 5 --output benchmarks/results/uber-<commit>.json
"""

from __future__ import annotations

import argparse
import functools
import gc
import json
import os
import platform
import statistics
import subprocess
import sys
import time
import tracemalloc
import urllib.request
import weakref
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, cast

if TYPE_CHECKING:
    from collections.abc import Iterator

    from composeui.webcore.webrenderer import WebRenderer

DATA_URL = "https://s3-us-west-2.amazonaws.com/streamlit-demo-data/uber-raw-data-sep14.csv.gz"
CACHE = Path.home() / ".cache" / "composeui-bench" / "uber-raw-data-sep14.csv.gz"
EXAMPLES = ("uberpickups", "uberpickupsframe")
BACKENDS = ("core", "web")
#: the slider's moves: the start (11), the busiest hour (17), the quietest (2), and back
HOURS = (17, 2, 11, 8, 23)
#: a column of each example to sort and filter by, and the filter's text
TABLE_COLUMN = {"uberpickups": ("lat", ">40.75"), "uberpickupsframe": ("Lat", ">40.75")}
MIB = 1024 * 1024


def fetch_data() -> Path:
    """Download the CSV once: a benchmark measures reading it, not the network."""
    if not CACHE.exists():
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        partial = CACHE.with_suffix(".part")
        urllib.request.urlretrieve(DATA_URL, partial)  # noqa: S310 (a fixed https URL)
        partial.replace(CACHE)
    return CACHE


def peak_rss_mib() -> float | None:
    """Get the process's peak resident memory, or None where `resource` is missing."""
    try:
        import resource  # noqa: PLC0415 (POSIX only)
    except ImportError:  # pragma: no cover (Windows)
        return None
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # kilobytes on Linux, bytes on macOS
    return peak / MIB if sys.platform == "darwin" else peak / 1024


class Clock:
    """Time named steps, and with `tracemalloc` on, their memory."""

    def __init__(self, *, memory: bool) -> None:
        self.memory = memory
        self.steps: dict[str, Any] = {}

    def step(self, name: str, action: Callable[[], Any]) -> Any:
        if self.memory:
            gc.collect()
            before = tracemalloc.get_traced_memory()[0]
            tracemalloc.reset_peak()
        start = time.perf_counter()
        result = action()
        elapsed = time.perf_counter() - start
        entry: dict[str, Any] = {"seconds": elapsed}
        if self.memory:
            current, peak = tracemalloc.get_traced_memory()
            entry["kept_mib"] = (current - before) / MIB
            entry["peak_mib"] = (peak - before) / MIB
        self.steps[name] = entry
        return result


def run_case(example: str, backend: str, data: Path, *, memory: bool) -> dict[str, Any]:
    """Run one case in this process, and give its measures."""
    clock = Clock(memory=memory)
    if memory:
        tracemalloc.start()
    module = clock.step("import", lambda: __import__(f"examples.{example}", fromlist=["_"]))
    url = data.as_uri() if example == "uberpickups" else str(data)
    module.DATA_URL = url
    measures: dict[str, Any] = {"example": example, "backend": backend, "memory": memory}
    if backend == "core":
        measures.update(_core_case(module, clock))
    else:
        measures.update(_web_case(module, clock))
    measures["steps"] = clock.steps
    measures["peak_rss_mib"] = peak_rss_mib()
    if memory:
        measures["traced_peak_mib"] = tracemalloc.get_traced_memory()[1] / MIB
        tracemalloc.stop()
    return measures


def _build_app(module: Any) -> Any:
    from composeui.core.application import ModelApplication  # noqa: PLC0415

    return ModelApplication(
        build_main_view=module.UberPickupsMainView,
        build_model=module.UberPickupsModel,
        setup_model=module.UberPickupsMainView.connect_model,
    )


def _settle(main_view: Any) -> None:
    """Wait for the main view's jobs, and on the core backend, emit their results."""
    if main_view.renderer is None:
        main_view.jobs.wait(timeout=600)
        return
    # the web emits them as they end, under the session's lock (`call_on_main_thread`);
    # a job that ends can start another meanwhile: see `_web_case`'s `poll`
    deadline = time.monotonic() + 600
    while main_view.jobs.is_running:
        if time.monotonic() > deadline:
            msg = "jobs still running after 600 s"
            raise TimeoutError(msg)
        time.sleep(0.001)


def _table_steps(module: Any, main_view: Any, clock: Clock) -> dict[str, Any]:
    """Show the table, sort and filter it: the source orders the rows each time."""
    table = main_view.table
    column, text = TABLE_COLUMN[module.__name__.rsplit(".", 1)[-1]]

    def show() -> None:
        # as a renderer does on a click: the attribute, then the signal
        checkbox = main_view.filters.show_raw_data
        checkbox.is_checked = True
        checkbox.toggled.emit(True)  # noqa: FBT003 (a signal's argument)

    def sort() -> None:
        table.sort_by(column)
        _settle(main_view)

    def filter_by(filters: dict[str, str]) -> Callable[[], None]:
        def action() -> None:
            table.filters = filters
            _settle(main_view)

        return action

    clock.step("show table", show)
    clock.step("sort", sort)
    clock.step("filter", filter_by({column: text}))
    filtered = table.row_count
    clock.step("clear filter", filter_by({}))
    return {"filtered_rows": filtered}


def _move_hours(main_view: Any, clock: Clock) -> dict[str, Any]:
    """Move the slider through `HOURS`: each move samples the map, and may filter the table."""
    rows = {}
    for hour in HOURS:

        def move(hour: int = hour) -> None:
            # as a renderer does on a move: the attribute, then the signal
            main_view.filters.hour.value = hour
            main_view.filters.hour.value_changed.emit(hour)
            _settle(main_view)

        clock.step(f"hour {hour:02d}", move)
        rows[hour] = {
            "rows": main_view.table.row_count,
            "points": len(main_view.pickups_map.points),
        }
    return {"hours": rows}


def _core_case(module: Any, clock: Clock) -> dict[str, Any]:
    def load() -> Any:
        app = _build_app(module)
        _settle(app.main_view)
        return app

    app = clock.step("load", load)
    measures = {"total_rows": sum(app.main_view.pickups_chart.series[0].y)}
    measures.update(_move_hours(app.main_view, clock))
    measures.update(_table_steps(module, app.main_view, clock))
    apps = [app]
    del app  # `_close` holds the last reference
    measures["cleanup"] = _close(apps, clock)
    return measures


def _close(apps: list[Any], clock: Clock) -> dict[str, Any]:
    """Close the model and drop the app, and check that its main view goes away with it."""
    app = apps.pop()
    main_view = weakref.ref(app.main_view)
    clock.step("close", functools.partial(_close_app, app))
    del app
    clock.step("collect", gc.collect)
    return {"main_view_freed": main_view() is None}


def _close_app(app: Any) -> None:
    _settle(app.main_view)
    app.model.close()


def _poll(browser: Any, main_view: Any) -> int:
    """Poll `/jobs`, as the page does, until no job runs; give the bytes polled.

    A job's end leaves the running jobs, then emits its result, which can start another
    job, all under the session's lock. A poll takes the lock: no job running after it means
    that none will start.
    """
    polled = 0
    while True:
        _settle(main_view)
        polled += len(browser.get("/jobs").content)
        if not main_view.jobs.is_running:
            return polled


def _web_case(module: Any, clock: Clock) -> dict[str, Any]:
    from starlette.testclient import TestClient  # noqa: PLC0415

    from composeui.core.renderer import RendererContainer  # noqa: PLC0415
    from composeui.webcore.webapplication import WebModelApplication  # noqa: PLC0415

    sessions: list[Any] = []

    class App(WebModelApplication[Any, Any]):
        def setup_session(self, main_view: Any) -> None:
            sessions.append(main_view)

    app = App(
        build_main_view=module.UberPickupsMainView,
        build_model=module.UberPickupsModel,
        setup_model=module.UberPickupsMainView.connect_model,
    )
    sizes: dict[str, int] = {}
    with TestClient(
        app.create_starlette_app(), headers={"Sec-Fetch-Site": "same-origin"}
    ) as browser:

        def first_page() -> None:
            sizes["first page"] = len(browser.get("/").content)

        clock.step("first page", first_page)
        (main_view,) = sessions
        poll = functools.partial(_poll, browser, main_view)

        def load() -> None:
            # what the page's poller brings once the rows are read
            sizes["load poll"] = poll()

        clock.step("load", load)

        def full_page() -> None:
            sizes["full page"] = len(browser.get("/").content)

        clock.step("full page", full_page)
        slider = main_view.filters.hour
        assert isinstance(slider.renderer, RendererContainer)
        slider_id = cast("WebRenderer[Any]", slider.renderer.get_renderer("field")).widget_id
        hours = {}
        for hour in HOURS:

            def move(hour: int = hour) -> None:
                response = browser.post(
                    f"/widget/{slider_id}", data={"value": str(hour), "event": "change"}
                )
                sizes[f"hour {hour:02d}"] = len(response.content)
                # the map's points, when a job samples them, come with the polls
                sizes[f"hour {hour:02d} poll"] = poll()

            clock.step(f"hour {hour:02d}", move)
            hours[hour] = {
                "rows": main_view.table.row_count,
                "points": len(main_view.pickups_map.points),
            }
        checkbox_id = main_view.filters.show_raw_data.renderer.widget_id
        table_id = main_view.table.renderer.widget_id
        column, text = TABLE_COLUMN[module.__name__.rsplit(".", 1)[-1]]

        def post(name: str, widget_id: str, data: dict[str, str]) -> None:
            def action() -> None:
                sizes[name] = len(browser.post(f"/widget/{widget_id}", data=data).content)
                sizes[f"{name} poll"] = poll()

            clock.step(name, action)

        post("show table", checkbox_id, {"event": "change", "checked": "on"})
        post("sort", table_id, {"event": "sort", "column": column})
        post("scroll", table_id, {"event": "scroll", "start": "5000", "offset": "0"})
        filtered_before = main_view.table.row_count
        main_view.table.filters = {column: text}  # the filter editor's form: set directly
        filtered = main_view.table.row_count
        main_view.table.filters = {}
    measures: dict[str, Any] = {
        "total_rows": sum(main_view.pickups_chart.series[0].y),
        "hours": hours,
        "response_bytes": sizes,
        "sorted_rows": filtered_before,
        "filtered_rows": filtered,
    }
    _settle(main_view)
    return measures


def _child(args: argparse.Namespace) -> None:
    measures = run_case(args.example, args.backend, Path(args.data), memory=args.memory)
    json.dump(measures, sys.stdout)


def _cases(args: argparse.Namespace) -> Iterator[tuple[str, str, bool]]:
    for example in args.examples:
        for backend in args.backends:
            for _ in range(args.repeat):
                yield example, backend, False
            yield example, backend, True


def _summary(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Get the median of each step's time over the timed runs, and the memory run."""
    timed = [run for run in runs if not run["memory"]]
    (memory,) = [run for run in runs if run["memory"]]
    steps = {
        name: {
            "median_s": statistics.median(run["steps"][name]["seconds"] for run in timed),
            "min_s": min(run["steps"][name]["seconds"] for run in timed),
            "kept_mib": memory["steps"][name]["kept_mib"],
            "peak_mib": memory["steps"][name]["peak_mib"],
        }
        for name in timed[0]["steps"]
    }
    return {
        "steps": steps,
        "peak_rss_mib": statistics.median(run["peak_rss_mib"] or 0 for run in timed),
        "traced_peak_mib": memory["traced_peak_mib"],
        "facts": {
            key: value
            for key, value in timed[0].items()
            if key not in {"steps", "memory", "peak_rss_mib", "example", "backend"}
        },
    }


def _environment() -> dict[str, Any]:
    import composeui  # noqa: PLC0415

    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],  # noqa: S607 (git from PATH)
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    return {
        "composeui": getattr(composeui, "__version__", None),
        "commit": commit,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "processor": platform.processor() or platform.machine(),
        "cpus": os.cpu_count(),
        "data": DATA_URL,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--examples", nargs="+", choices=EXAMPLES, default=list(EXAMPLES))
    parser.add_argument("--backends", nargs="+", choices=BACKENDS, default=list(BACKENDS))
    parser.add_argument("--repeat", type=int, default=3, help="Timed runs of each case.")
    parser.add_argument("--output", type=Path, help="Where to write the JSON results.")
    # one case, in a child process
    parser.add_argument("--example", choices=EXAMPLES, help=argparse.SUPPRESS)
    parser.add_argument("--backend", choices=BACKENDS, help=argparse.SUPPRESS)
    parser.add_argument("--data", help=argparse.SUPPRESS)
    parser.add_argument("--memory", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.example is not None:
        _child(args)
        return
    data = fetch_data()
    runs: dict[str, list[dict[str, Any]]] = {}
    for example, backend, memory in _cases(args):
        command = [sys.executable, __file__, "--example", example, "--backend", backend]
        command += ["--data", str(data), *(["--memory"] if memory else [])]
        label = f"{example} on {backend}{' (memory)' if memory else ''}"
        print(f"Running {label}", file=sys.stderr)  # noqa: T201
        # the command runs this file again, with arguments that `choices` checked
        output = subprocess.run(  # noqa: S603
            command, capture_output=True, text=True, check=True
        ).stdout
        runs.setdefault(f"{example}/{backend}", []).append(json.loads(output))
    results = {
        "environment": _environment(),
        "cases": {name: _summary(case_runs) for name, case_runs in runs.items()},
        "runs": runs,
    }
    text = json.dumps(results, indent=2)
    if args.output is None:
        print(text)  # noqa: T201
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n")


if __name__ == "__main__":
    main()

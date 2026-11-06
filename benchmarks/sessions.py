"""Measure the web sessions of the two Uber pickups examples: their memory, cleanup and load.

The cleanup case runs one process that opens several sessions through Starlette's test client,
then lets them expire, and reports what each session holds and what its end gives back.

The left-during-a-load case expires a session at several moments of its load. Each run is a
process of its own, because the process can crash.

The concurrency case runs a real Uvicorn server in a process of its own, with one HTTP client
per session in another process. So the clients do not share the server's interpreter, and all
the sessions share the server's one event loop, as in a deployment.

The cases read Linux's `/proc`.

    uv run python benchmarks/sessions.py --output benchmarks/results/sessions-<commit>.json
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import importlib
import json
import os
import re
import socket
import statistics
import subprocess
import sys
import threading
import time
import tracemalloc
import weakref
from pathlib import Path
from typing import Any

from uber import EXAMPLES, HOURS, MIB, _environment, fetch_data

#: the header that the app's same-origin check reads, as a browser sends it
HEADERS = {"Sec-Fetch-Site": "same-origin"}
#: in a response, what shows that the main view's jobs still run
RUNNING = 'hx-get="/jobs"'
SLIDER = re.compile(r'type="range"[^>]*hx-post="([^"]+)"')
#: seconds between two polls during a load, as the page does (`JOBS_POLL_MS`)
LOAD_POLL = 0.3
#: seconds between two polls after a move: shorter than the page's, to time the job's end
MOVE_POLL = 0.05
#: seconds that a session has been open when it expires during its load
LEFT_AFTER = (0.1, 0.5, 1.0, 2.0, 4.0)
#: what a job logs when it fails: the app's logger writes it on the standard output
JOB_FAILED = "The job load_pickups failed"
#: seconds to wait for what a session left behind to be freed
FREE_TIMEOUT = 120.0


def _load_example(example: str, data: Path) -> Any:
    module = importlib.import_module(f"examples.{example}")
    module.DATA_URL = data.as_uri() if example == "uberpickups" else str(data)
    return module


def _new_app(module: Any, app_class: type[Any]) -> Any:
    return app_class(
        build_main_view=module.UberPickupsMainView,
        build_model=module.UberPickupsModel,
        setup_model=module.UberPickupsMainView.connect_model,
    )


def _descriptor_file(descriptor: Path) -> tuple[str, int] | None:
    """Give the path and the size of a session's file open on `descriptor`, else None."""
    try:
        target = str(descriptor.readlink())
        # by its name: the data's own folder, `composeui-bench`, also has these letters
        if not Path(target).name.startswith("composeui-"):
            return None
        # through the descriptor: it also finds a file deleted but still open
        return target.removesuffix(" (deleted)"), descriptor.stat().st_size
    except FileNotFoundError:  # the descriptor of the listing itself, or one closed since
        return None


def _session_files() -> dict[str, int]:
    """Get the files of the sessions that this process holds open, with their sizes."""
    found = map(_descriptor_file, Path("/proc/self/fd").iterdir())
    return dict(file for file in found if file is not None)


def _snapshot() -> dict[str, Any]:
    """Collect the garbage, then read what this process holds now."""
    gc.collect()
    resident_pages = int(Path("/proc/self/statm").read_text().split()[1])
    return {
        "rss_mib": resident_pages * os.sysconf("SC_PAGE_SIZE") / MIB,
        "python_mib": tracemalloc.get_traced_memory()[0] / MIB,
        "files_mib": sum(_session_files().values()) / MIB,
        "descriptors": sum(1 for _ in Path("/proc/self/fd").iterdir()),
        "threads": threading.active_count(),
    }


def _check(response: Any) -> Any:
    response.raise_for_status()
    if "HX-Refresh" in response.headers:
        msg = f"the session of {response.url} is gone"
        raise RuntimeError(msg)
    return response


def _settle(browser: Any) -> None:
    """Poll `/jobs`, as the page does, until no job runs."""
    while RUNNING in _check(browser.get("/jobs")).text:
        time.sleep(MOVE_POLL)


def _wait_freed(reference: weakref.ref[Any]) -> float | None:
    """Give the seconds until `reference`'s object is freed; None if it stays."""
    start = time.perf_counter()
    while time.perf_counter() - start < FREE_TIMEOUT:
        gc.collect()
        if reference() is None:
            return time.perf_counter() - start
        time.sleep(0.05)
    return None


def _left_case(example: str, data: Path, delay: float) -> dict[str, Any]:
    """Expire a session `delay` seconds after it opens: its load may still run."""
    from starlette.testclient import TestClient  # noqa: PLC0415

    from composeui.webcore.webapplication import WebModelApplication  # noqa: PLC0415

    module = _load_example(example, data)
    main_views: list[weakref.ref[Any]] = []

    class App(WebModelApplication[Any, Any]):
        def setup_session(self, main_view: Any) -> None:
            main_views.append(weakref.ref(main_view))

    starlette_app = _new_app(module, App).create_starlette_app()
    with TestClient(starlette_app, headers=HEADERS) as browser:
        _check(browser.get("/"))
        time.sleep(delay)
        view = main_views[0]()
        was_running = view is not None and view.jobs.is_running
        del view
        files = set(_session_files())
        starlette_app.state.sessions._ttl = 0  # noqa: SLF001 (no public way to end one now)
        start = time.perf_counter()
        browser.get("/jobs")
        expiry = time.perf_counter() - start
        freed = _wait_freed(main_views[0])
        # the last connection closed, or the job's end, can delete a file a moment later
        time.sleep(1)
        return {
            "was_running": was_running,
            "expiry_s": expiry,
            "freed_s": freed,
            "files_left": sorted(Path(path).name for path in files if Path(path).exists()),
        }


def _cleanup_case(example: str, data: Path, count: int, *, memory: bool) -> dict[str, Any]:
    """Open `count` sessions one after another, then let them all expire."""
    from starlette.testclient import TestClient  # noqa: PLC0415

    from composeui.webcore.webapplication import WebModelApplication  # noqa: PLC0415

    errors: list[str] = []
    threading.excepthook = lambda info: errors.append(repr(info.exc_value))
    if memory:
        tracemalloc.start()
    module = _load_example(example, data)
    main_views: list[weakref.ref[Any]] = []

    class App(WebModelApplication[Any, Any]):
        def setup_session(self, main_view: Any) -> None:
            main_views.append(weakref.ref(main_view))

    starlette_app = _new_app(module, App).create_starlette_app()
    store = starlette_app.state.sessions
    measures: dict[str, Any] = {"example": example, "memory": memory, "sessions": count}
    with TestClient(starlette_app, headers=HEADERS) as browser:
        measures["before"] = _snapshot()
        loads, opened = [], []
        databases: set[str] = set()
        for _ in range(count):
            start = time.perf_counter()
            browser.cookies.clear()
            page = _check(browser.get("/")).text
            _settle(browser)
            loads.append(time.perf_counter() - start)
            # one move: the table then holds the IDs of the hour's rows
            address = SLIDER.search(page)
            assert address is not None
            _check(browser.post(address.group(1), data={"value": "17", "event": "change"}))
            _settle(browser)
            opened.append(_snapshot())
            databases |= set(_session_files())
        measures["load_s"] = loads
        measures["opened"] = opened

        # a request's expiry closes them all, under the store's lock
        store._ttl = 0  # noqa: SLF001 (no public way to end a session now)
        start = time.perf_counter()
        browser.get("/jobs")
        measures["expiry_s"] = time.perf_counter() - start
        measures["after"] = _snapshot()
        measures["main_views_freed"] = sum(reference() is None for reference in main_views)
        measures["files_left"] = sum(Path(path).exists() for path in databases)

    measures["thread_errors"] = errors
    return measures


def _serve(example: str, data: Path) -> None:
    """Serve the example on a free port, and print the port for the parent."""
    import uvicorn  # noqa: PLC0415

    from composeui.webcore.webapplication import WebModelApplication  # noqa: PLC0415

    module = _load_example(example, data)
    starlette_app = _new_app(module, WebModelApplication).create_starlette_app()
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    print(listener.getsockname()[1], flush=True)  # noqa: T201
    config = uvicorn.Config(starlette_app, log_level="warning", access_log=False)
    uvicorn.Server(config).run(sockets=[listener])


def _server_memory(pid: int) -> dict[str, float]:
    """Read a process's memory and threads from `/proc`."""
    fields = dict(
        line.split(":", maxsplit=1) for line in Path(f"/proc/{pid}/status").read_text().splitlines()
    )
    return {
        "rss_mib": int(fields["VmRSS"].split()[0]) / 1024,
        "peak_rss_mib": int(fields["VmHWM"].split()[0]) / 1024,
        "threads": int(fields["Threads"]),
    }


async def _poll(client: Any, interval: float) -> None:
    while True:
        response = _check(await client.get("/jobs"))
        if RUNNING not in response.text:
            return
        await asyncio.sleep(interval)


async def _open(client: Any) -> tuple[str, float]:
    """Open a session and wait for its load; give the slider's address and the seconds."""
    start = time.perf_counter()
    response = _check(await client.get("/"))
    await _poll(client, LOAD_POLL)
    address = SLIDER.search(response.text)
    assert address is not None
    return address.group(1), time.perf_counter() - start


async def _move(client: Any, address: str, hour: int) -> tuple[float, float]:
    """Move the slider; give the seconds of its response, and until its job ends."""
    start = time.perf_counter()
    _check(await client.post(address, data={"value": str(hour), "event": "change"}))
    answered = time.perf_counter() - start
    await _poll(client, MOVE_POLL)
    return answered, time.perf_counter() - start


async def _moves(client: Any, address: str, rounds: int) -> list[tuple[float, float]]:
    return [await _move(client, address, hour) for _ in range(rounds) for hour in HOURS]


async def _concurrency_run(port: int, pid: int, count: int, rounds: int) -> dict[str, Any]:
    """Load `count` sessions together, move their sliders together, then both at once."""
    import httpx  # noqa: PLC0415

    def new_client() -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{port}", headers=HEADERS, timeout=FREE_TIMEOUT * 5
        )

    clients = [new_client() for _ in range(count)]
    late = [new_client() for _ in range(count - 1)]
    try:
        opened = await asyncio.gather(*map(_open, clients))
        addresses = [address for address, _ in opened]
        measures: dict[str, Any] = {"load_s": [seconds for _, seconds in opened]}
        measures["loaded"] = _server_memory(pid)
        start = time.perf_counter()
        moves = await asyncio.gather(*(_moves(c, a, rounds) for c, a in zip(clients, addresses)))
        wall = time.perf_counter() - start
        flat = [move for session in moves for move in session]
        measures["moves"] = {
            "response_s": [answered for answered, _ in flat],
            "done_s": [done for _, done in flat],
            "per_second": len(flat) / wall,
        }
        measures["moved"] = _server_memory(pid)
        if late:
            # one user keeps moving while other users open their sessions
            loading = asyncio.gather(*map(_open, late))
            mixed = []
            while not loading.done():
                mixed.append(await _move(clients[0], addresses[0], HOURS[len(mixed) % len(HOURS)]))
            measures["late_load_s"] = [seconds for _, seconds in await loading]
            measures["moves_during_loads"] = {
                "response_s": [answered for answered, _ in mixed],
                "done_s": [done for _, done in mixed],
            }
        measures["end"] = _server_memory(pid)
    finally:
        await asyncio.gather(*(client.aclose() for client in (*clients, *late)))
    return measures


def _concurrency_case(example: str, data: Path, count: int, rounds: int) -> dict[str, Any]:
    command = [sys.executable, __file__, "--serve", example, "--data", str(data)]
    # the command runs this file again, with an example that `choices` checked
    server = subprocess.Popen(command, stdout=subprocess.PIPE, text=True)  # noqa: S603
    try:
        assert server.stdout is not None
        port = int(server.stdout.readline())
        return asyncio.run(_concurrency_run(port, server.pid, count, rounds))
    finally:
        server.terminate()
        server.wait(timeout=60)


def _spread(samples: list[float]) -> dict[str, float]:
    ordered = sorted(samples)
    return {
        "count": len(ordered),
        "median_s": statistics.median(ordered),
        "p95_s": ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))],
        "max_s": ordered[-1],
    }


def _summary(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Pool the samples of one number of sessions over its runs."""

    def pooled(*path: str) -> list[float]:
        samples: list[float] = []
        for run in runs:
            value: Any = run
            for key in path:
                value = value.get(key, [])
            samples += value
        return samples

    summary: dict[str, Any] = {
        "load": _spread(pooled("load_s")),
        "move_response": _spread(pooled("moves", "response_s")),
        "move_done": _spread(pooled("moves", "done_s")),
        "moves_per_second": statistics.median(run["moves"]["per_second"] for run in runs),
        "peak_rss_mib": statistics.median(run["end"]["peak_rss_mib"] for run in runs),
    }
    if pooled("late_load_s"):
        summary["late_load"] = _spread(pooled("late_load_s"))
        summary["during_loads_response"] = _spread(pooled("moves_during_loads", "response_s"))
        summary["during_loads_done"] = _spread(pooled("moves_during_loads", "done_s"))
    return summary


def _cleanup_summary(run: dict[str, Any]) -> dict[str, Any]:
    """Get what each session costs: the first one also pays for what the process keeps."""
    opened = run["opened"]
    count = len(opened)
    return {
        "first_session_rss_mib": opened[0]["rss_mib"] - run["before"]["rss_mib"],
        **{
            f"per_session_{name}": (opened[-1][name] - opened[0][name]) / (count - 1)
            for name in ("rss_mib", "python_mib", "files_mib", "descriptors", "threads")
        },
        "expiry_s_per_session": run["expiry_s"] / count,
    }


def _child(command: list[str]) -> tuple[subprocess.CompletedProcess[str], dict[str, Any] | None]:
    """Run a case in a child process; its result is the last line of its standard output."""
    # the command runs this file again, with arguments that `choices` checked
    done = subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603
    lines = done.stdout.splitlines()
    return done, json.loads(lines[-1]) if done.returncode == 0 else None


def _run_cleanup(example: str, data: Path, count: int, *, memory: bool) -> dict[str, Any]:
    command = [sys.executable, __file__, "--cleanup", example, "--data", str(data)]
    command += ["--sessions", str(count), *(["--memory"] if memory else [])]
    done, run = _child(command)
    if run is None:
        msg = f"the cleanup of {example} ended with {done.returncode}: {done.stderr[-2000:]}"
        raise RuntimeError(msg)
    run["summary"] = _cleanup_summary(run)
    return run


def _run_left(example: str, data: Path, repeat: int) -> dict[str, Any]:
    """Count the crashes and the failed jobs of sessions left at each moment of a load."""
    delays: dict[str, Any] = {}
    for delay in LEFT_AFTER:
        command = [sys.executable, __file__, "--left", example, "--data", str(data)]
        runs = []
        for _ in range(repeat):
            done, run = _child([*command, "--delay", str(delay)])
            runs.append(
                {
                    "exit_code": done.returncode,
                    "job_failed": JOB_FAILED in done.stdout,
                    **(run or {}),
                }
            )
        delays[str(delay)] = runs
    return delays


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--examples", nargs="+", choices=EXAMPLES, default=list(EXAMPLES))
    parser.add_argument("--sessions", type=int, default=4, help="Sessions of the cleanup case.")
    parser.add_argument("--levels", nargs="+", type=int, default=[1, 2, 4, 8])
    parser.add_argument("--repeat", type=int, default=2, help="Runs of each concurrency level.")
    parser.add_argument("--rounds", type=int, default=3, help="Rounds of hour moves per session.")
    parser.add_argument("--left-repeat", type=int, default=3, help="Runs per moment of a load.")
    parser.add_argument("--output", type=Path, help="Where to write the JSON results.")
    # one case, in a child process
    parser.add_argument("--cleanup", choices=EXAMPLES, help=argparse.SUPPRESS)
    parser.add_argument("--left", choices=EXAMPLES, help=argparse.SUPPRESS)
    parser.add_argument("--delay", type=float, help=argparse.SUPPRESS)
    parser.add_argument("--serve", choices=EXAMPLES, help=argparse.SUPPRESS)
    parser.add_argument("--data", help=argparse.SUPPRESS)
    parser.add_argument("--memory", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.cleanup is not None:
        measures = _cleanup_case(args.cleanup, Path(args.data), args.sessions, memory=args.memory)
        # on a line of its own: the app's logger writes on the standard output too
        print(json.dumps(measures))  # noqa: T201
        return
    if args.left is not None:
        print(json.dumps(_left_case(args.left, Path(args.data), args.delay)))  # noqa: T201
        return
    if args.serve is not None:
        _serve(args.serve, Path(args.data))
        return
    data = fetch_data()
    results: dict[str, Any] = {"environment": _environment(), "cases": {}}
    for example in args.examples:
        print(f"Running the cleanup of {example}", file=sys.stderr)  # noqa: T201
        case: dict[str, Any] = {
            "cleanup": _run_cleanup(example, data, args.sessions, memory=False),
            "cleanup_memory": _run_cleanup(example, data, args.sessions, memory=True),
            "left_during_load": _run_left(example, data, args.left_repeat),
            "concurrency": {},
        }
        for level in args.levels:
            print(f"Running {level} sessions of {example}", file=sys.stderr)  # noqa: T201
            runs = [
                _concurrency_case(example, data, level, args.rounds) for _ in range(args.repeat)
            ]
            case["concurrency"][str(level)] = {"summary": _summary(runs), "runs": runs}
        results["cases"][example] = case
    text = json.dumps(results, indent=2)
    if args.output is None:
        print(text)  # noqa: T201
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n")


if __name__ == "__main__":
    main()

"""Measure a web server under a steady arrival of sessions, with and without hibernation.

Users arrive at a steady rate for the run's length. Each one opens the frameworks benchmark's
app, types in an input, opens a few pages and clicks Apply, then leaves its tab idle. Some
come back later: they reload their page, check that it and what they typed are still
there, and type again. The server runs as in a deployment: Uvicorn in a process of its own, idle
sessions saved by its own timer (`session_idle`). Every second, the run reads the server's
RSS and the size of its saved sessions.

The two modes run the same users: "kept" keeps every session in memory, "hibernated" saves
those idle for `--idle` seconds. The clients are plain HTTP clients, as htmx sends its
requests: the browser's own work is left out, and its page scripts too.

    uv run python benchmarks/hibernation_soak.py \
        --output benchmarks/results/hibernation-soak-<commit>.json
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import platform
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    import httpx

#: the header that the app's same-origin check reads, as a browser sends it
HEADERS = {"Sec-Fetch-Site": "same-origin"}
TEXT_INPUT = re.compile(r'<input[^>]*type="text"[^>]*hx-post="([^"]+)"')
APPLY = re.compile(r'<button[^>]*hx-post="([^"]+)"[^>]*>Apply')
#: seconds between two readings of the server
SAMPLE = 1.0


def _tab(page: str, number: int) -> str:
    """Give the address of the tab that opens page `number`, from a page's HTML."""
    found = re.search(rf'href="/p{number}"[^>]*hx-post="([^"]+)"', page)
    assert found is not None, number
    return found.group(1)


def serve(port: int, idle: Optional[float]) -> None:
    """Serve the app, and give the folder of its saved sessions on the first line."""
    import uvicorn  # noqa: PLC0415
    from twins.composeui_app import BenchMainView  # noqa: PLC0415

    from composeui.webcore.webapplication import WebApplication  # noqa: PLC0415

    class App(WebApplication[BenchMainView]):
        session_ttl = 24 * 3600.0
        max_sessions = 100_000
        session_idle = idle

    app = App(build_main_view=BenchMainView).create_starlette_app()
    directory = app.state.sessions._directory  # noqa: SLF001
    print("" if directory is None else directory, flush=True)  # noqa: T201
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


def _rss_mib(pid: int) -> float:
    pages = int(Path(f"/proc/{pid}/statm").read_text().split()[1])
    return pages * os.sysconf("SC_PAGE_SIZE") / (1024 * 1024)


def _disk_mib(directory: Path | None) -> float:
    if directory is None:
        return 0.0
    total = 0
    # os.walk skips a folder renamed or removed meanwhile, as the server saves and wakes
    for folder, _folders, files in os.walk(directory):
        for name in files:
            # a file removed meanwhile
            with contextlib.suppress(FileNotFoundError):
                total += (Path(folder) / name).stat().st_size
    return total / (1024 * 1024)


class _Clock:
    """Seconds since the run started."""

    def __init__(self) -> None:
        self.start = time.perf_counter()

    def __call__(self) -> float:
        return time.perf_counter() - self.start


async def _timed(timings: list[float], request: Any) -> httpx.Response:
    start = time.perf_counter()
    response: httpx.Response = await request
    timings.append((time.perf_counter() - start) * 1000)
    response.raise_for_status()
    return response


async def _user(  # noqa: PLR0913
    base: str,
    index: int,
    arrive: float,
    back: float | None,
    pages: int,
    clock: _Clock,
    timings: dict[str, list[float]],
) -> None:
    """Open a session, use it, leave it idle, and come back at `back` seconds if not None."""
    import httpx  # noqa: PLC0415

    await asyncio.sleep(max(0.0, arrive - clock()))
    async with httpx.AsyncClient(
        base_url=base, headers=HEADERS, timeout=120, follow_redirects=True
    ) as client:
        page = (await _timed(timings["open_ms"], client.get("/"))).text
        address = TEXT_INPUT.search(page)
        assert address is not None
        form = {"value": f"user-{index}", "event": "change"}
        await _timed(timings["action_ms"], client.post(address.group(1), data=form))
        number = 0
        shown = page
        for step in range(pages):
            number = (index + step) % 19 + 1
            data = {"event": "triggered"}
            # the tabs of the first page: their addresses last as long as the session
            shown = (
                await _timed(timings["action_ms"], client.post(_tab(page, number), data=data))
            ).text
        apply = APPLY.search(shown)
        assert apply is not None
        data = {"event": "click"}
        await _timed(timings["action_ms"], client.post(apply.group(1), data=data))
        cookies = client.cookies
    if back is None:
        return
    await asyncio.sleep(max(0.0, back - clock()))
    async with httpx.AsyncClient(
        base_url=base, headers=HEADERS, timeout=120, follow_redirects=True, cookies=cookies
    ) as client:
        page = (await _timed(timings["return_ms"], client.get(f"/p{number}"))).text
        assert f"Content {number}" in page, index
        # Apply's label isn't checked: a label is UI text, which a study doesn't keep
        first = (await client.get("/p0")).text
        assert f'value="user-{index}"' in first, index
        address = TEXT_INPUT.search(page)
        assert address is not None
        form = {"value": f"back-{index}", "event": "change"}
        await _timed(timings["action_ms"], client.post(address.group(1), data=form))


async def _sample(
    pid: int, directory: Path | None, clock: _Clock, until: asyncio.Event
) -> list[dict[str, float]]:
    samples = []
    while not until.is_set():
        samples.append({"t": clock(), "rss_mib": _rss_mib(pid), "disk_mib": _disk_mib(directory)})
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(until.wait(), SAMPLE)
    return samples


async def _drive(
    pid: int, port: int, directory: Path | None, args: argparse.Namespace, clock: _Clock
) -> dict[str, Any]:
    timings: dict[str, list[float]] = {"open_ms": [], "action_ms": [], "return_ms": []}
    interval = 1 / args.rate
    users = []
    returning = 0
    for index in range(args.users):
        arrive = index * interval
        # every n-th user comes back, spread over the run
        back = None
        if args.come_back and index % args.come_back == 0:
            back = arrive + args.back_after
            returning += 1
        users.append(
            _user(f"http://127.0.0.1:{port}", index, arrive, back, args.pages, clock, timings)
        )
    done = asyncio.Event()
    sampler = asyncio.ensure_future(_sample(pid, directory, clock, done))
    await asyncio.gather(*users)
    arrived = clock()
    # what the server holds once every tab is idle and the timer had time to save them
    await asyncio.sleep(args.settle)
    done.set()
    samples = await sampler
    return {
        "users": args.users,
        "returning": returning,
        "last_request_s": arrived,
        "samples": samples,
        "timings_ms": timings,
    }


def _spread(samples: list[float]) -> dict[str, float]:
    ordered = sorted(samples)
    return {
        "count": len(ordered),
        "median": statistics.median(ordered),
        "p95": ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))],
        "max": ordered[-1],
    }


def measure(python: Path, args: argparse.Namespace, idle: float | None) -> dict[str, Any]:
    import frameworks  # noqa: PLC0415

    port = frameworks._free_port()  # noqa: SLF001
    command = [str(python), __file__, "--serve", str(port)]
    if idle is not None:
        command += ["--serve-idle", str(idle)]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, text=True)  # noqa: S603
    try:
        assert process.stdout is not None
        line = process.stdout.readline().strip()
        directory = Path(line) if line else None
        _wait_ready(process, port)
        clock = _Clock()
        run = asyncio.run(_drive(process.pid, port, directory, args, clock))
    finally:
        process.terminate()
        process.wait(timeout=60)
    samples = run["samples"]
    final = samples[-1]
    # the spreads only: thousands of requests
    timings = run.pop("timings_ms")
    return {
        **run,
        "summary": {
            "start_rss_mib": samples[0]["rss_mib"],
            "peak_rss_mib": max(sample["rss_mib"] for sample in samples),
            "final_rss_mib": final["rss_mib"],
            "final_disk_mib": final["disk_mib"],
            **{name: _spread(values) for name, values in timings.items() if values},
        },
    }


def _wait_ready(process: subprocess.Popen[str], port: int) -> None:
    import socket  # noqa: PLC0415

    # TCP only: an HTTP probe would open a session
    deadline = time.monotonic() + 60
    while True:
        with socket.socket() as connection:
            connection.settimeout(1)
            if connection.connect_ex(("127.0.0.1", port)) == 0:
                return
        if process.poll() is not None or time.monotonic() > deadline:
            message = "The server did not start"
            raise RuntimeError(message)
        time.sleep(0.05)


def _environment(python: Path) -> dict[str, Any]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],  # noqa: S607 (git from PATH)
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    version = subprocess.run(  # noqa: S603 (our own interpreter)
        [str(python), "-c", "import platform; print(platform.python_version())"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return {
        "commit": commit,
        "python": version,
        "platform": platform.platform(),
        "processor": platform.processor() or platform.machine(),
        "cpus": os.cpu_count(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--users", type=int, default=600, help="Users over the run.")
    parser.add_argument("--rate", type=float, default=2.0, help="Users arriving per second.")
    parser.add_argument("--pages", type=int, default=3, help="Pages each user opens.")
    parser.add_argument("--idle", type=float, default=30.0, help="session_idle, in seconds.")
    parser.add_argument(
        "--come-back", type=int, default=4, help="One user in n comes back; 0 for none."
    )
    parser.add_argument("--back-after", type=float, default=120.0, help="Seconds until then.")
    parser.add_argument("--settle", type=float, default=90.0, help="Seconds idle at the end.")
    parser.add_argument("--output", type=Path, help="Where to write the JSON results.")
    parser.add_argument("--serve", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--serve-idle", type=float, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.serve is not None:
        serve(args.serve, args.serve_idle)
        return
    import frameworks  # noqa: PLC0415

    python = frameworks._environment_python(  # noqa: SLF001
        "composeui", "3.12", ["-e", f"{frameworks.REPOSITORY}[web]"]
    )
    modes: dict[str, float | None] = {"kept": None, "hibernated": args.idle}
    runs = {}
    for name, idle in modes.items():
        print(f"Running {args.users} users, {name}", file=sys.stderr)  # noqa: T201
        runs[name] = measure(python, args, idle)
    results = {
        "environment": _environment(python),
        "method": {
            "app": "benchmarks/twins/composeui_app.py (20 pages, 10 rows per page)",
            "command": (
                "uv run python benchmarks/hibernation_soak.py "
                "--output benchmarks/results/hibernation-soak-<commit>.json"
            ),
            "users": (
                f"{args.users} users, {args.rate} per second. Each opens the app, types in an "
                f"input, opens {args.pages} pages by their tabs and clicks Apply, then stays "
                "idle. One user in "
                f"{args.come_back} comes back {args.back_after} s after arriving: reloads its "
                "page, checks it and its input, and types again."
            ),
            "server": (
                "Uvicorn in its own process; session_ttl 24 h, so no session expires. "
                f"'hibernated' sets session_idle to {args.idle} s, and the server's own timer "
                "saves the sessions; 'kept' sets None."
            ),
            "memory": (
                f"Server RSS and the size of its saved sessions, every {SAMPLE} s, until "
                f"{args.settle} s after the last request."
            ),
            "timings": (
                "HTTP time of each request, without a browser. return_ms is the reload of "
                "a returning user: in 'hibernated', it wakes the session from disk."
            ),
        },
        "summary": {name: run["summary"] for name, run in runs.items()},
        "runs": runs,
    }
    text = json.dumps(results, indent=2)
    if args.output is None:
        print(json.dumps(results["summary"], indent=2))  # noqa: T201
    else:
        args.output.write_text(text + "\n")


if __name__ == "__main__":
    main()

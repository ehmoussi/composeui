from __future__ import annotations

import argparse
import gc
import json
import os
import socket
import statistics
import subprocess
import sys
import threading
import time
import weakref
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from playwright.sync_api import Browser, BrowserContext, Page


def serve(port: int) -> None:
    import uvicorn  # noqa: PLC0415
    from twins.composeui_app import BenchMainView  # noqa: PLC0415

    from composeui.webcore.session import Hibernation  # noqa: PLC0415
    from composeui.webcore.webapplication import WebApplication  # noqa: PLC0415

    class App(WebApplication[BenchMainView]):
        session_idle = 3600.0

    app = App(build_main_view=BenchMainView).create_starlette_app()
    store = app.state.sessions

    def snapshot() -> dict[str, Any]:
        gc.collect()
        with store._lock:  # noqa: SLF001
            places = [entry.place.name for entry in store._entries.values()]  # noqa: SLF001
        directory = store._directory  # noqa: SLF001
        files = [] if directory is None else list(directory.rglob("*"))
        return {
            "rss_mib": int(Path("/proc/self/statm").read_text().split()[1])
            * os.sysconf("SC_PAGE_SIZE")
            / (1024 * 1024),
            "live": places.count("LIVE"),
            "on_disk": places.count("ON_DISK"),
            "transitional": places.count("SAVING") + places.count("WAKING"),
            "disk_bytes": sum(path.stat().st_size for path in files if path.is_file()),
            # Python's heap, which falls after a sweep even when RSS doesn't
            "py_blocks": sys.getallocatedblocks(),
        }

    def control() -> None:
        for line in sys.stdin:
            command = line.strip()
            result: dict[str, Any]
            if command == "hibernate":
                with store._lock:  # noqa: SLF001
                    sessions = [
                        weakref.ref(entry.session)
                        for entry in store._entries.values()  # noqa: SLF001
                        if entry.session is not None
                    ]
                    views = [
                        weakref.ref(entry.session.main_view)
                        for entry in store._entries.values()  # noqa: SLF001
                        if entry.session is not None
                    ]
                # All browser work has ended. Make these sessions eligible together,
                # rather than hibernating early sessions while later ones still open.
                store.hibernation = Hibernation(0, 10000)
                start = time.perf_counter()
                try:
                    store.hibernate_idle()
                finally:
                    store.hibernation = Hibernation(3600, 10000)
                elapsed = time.perf_counter() - start
                result = snapshot()
                result.update(
                    save_s=elapsed,
                    sessions_freed=sum(reference() is None for reference in sessions),
                    views_freed=sum(reference() is None for reference in views),
                )
            else:
                assert command == "snapshot", command
                result = snapshot()
            print(json.dumps(result), flush=True)  # noqa: T201

    threading.Thread(target=control, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


def request(process: subprocess.Popen[str], command: str) -> dict[str, Any]:
    assert process.stdin is not None
    assert process.stdout is not None
    process.stdin.write(command + "\n")
    process.stdin.flush()
    line = process.stdout.readline()
    if not line:
        message = "Benchmark server ended before answering"
        raise RuntimeError(message)
    result: dict[str, Any] = json.loads(line)
    return result


def wait_ready(process: subprocess.Popen[str], port: int) -> None:
    # Probe TCP only: an HTTP readiness probe would create an extra session.
    deadline = time.monotonic() + 60
    while True:
        with socket.socket() as connection:
            connection.settimeout(1)
            if connection.connect_ex(("127.0.0.1", port)) == 0:
                return
        if process.poll() is not None or time.monotonic() > deadline:
            message = "Benchmark server did not start"
            raise RuntimeError(message)
        time.sleep(0.05)


def _open_batch(
    browser: Browser, url: str, count: int, first: int, *, explored: bool
) -> list[tuple[BrowserContext, Page]]:
    """Open `count` sessions, each with its number from `first` typed in its first textbox."""
    import frameworks  # noqa: PLC0415

    server = frameworks.Server("ComposeUI", lambda _port: [])
    opened = []
    for index in range(first, first + count):
        context, page, _seconds = frameworks._open(browser, url)  # noqa: SLF001
        opened.append((context, page))
        if explored:
            for number in range(1, frameworks.PAGES):
                frameworks._switch(page, server, number)  # noqa: SLF001
        page.get_by_role("textbox").first.fill(f"session-{index}")
        # Blur sends the input's change before the measurement barrier.
        with page.expect_response(lambda response: response.request.method == "POST"):
            page.get_by_role("textbox").first.press("Tab")
        page.wait_for_function("!document.querySelector('.htmx-request')")
    return opened


def _wake(opened: list[tuple[BrowserContext, Page]], *, explored: bool) -> list[float]:
    """Reload each page of a hibernated session, check its state, and give the times in ms."""
    import frameworks  # noqa: PLC0415

    wake_ms = []
    for index, (context, page) in enumerate(opened):
        cookies = {cookie["name"]: cookie["value"].split(".")[0] for cookie in context.cookies()}
        address = page.url
        start = time.perf_counter()
        page.reload()
        frameworks._wait_for_page(page, 19 if explored else 0)  # noqa: SLF001
        assert page.get_by_role("textbox").first.input_value() == f"session-{index}"
        assert page.url == address
        # Starlette refreshes the signature timestamp and the cookie's expiry.
        assert {
            cookie["name"]: cookie["value"].split(".")[0] for cookie in context.cookies()
        } == cookies
        wake_ms.append((time.perf_counter() - start) * 1000)
    return wake_ms


def measure(
    browser: Browser, python: Path, count: int, *, explored: bool, hibernate: bool
) -> dict[str, Any]:
    """Open two batches of `count` sessions, the first one hibernated before the second or not.

    CPython rarely gives freed memory back to the system, so RSS can't drop after a sweep.
    What hibernation saves shows in the second batch: it reuses the memory the first freed.
    """
    import frameworks  # noqa: PLC0415

    port = frameworks._free_port()  # noqa: SLF001
    process = subprocess.Popen(  # noqa: S603
        [str(python), __file__, "--serve", str(port)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    opened = []
    try:
        wait_ready(process, port)
        before = request(process, "snapshot")
        url = f"http://127.0.0.1:{port}"
        first = _open_batch(browser, url, count, 0, explored=explored)
        opened.extend(first)
        live = request(process, "snapshot")
        assert live["live"] == count, live
        assert live["on_disk"] == 0, live
        result: dict[str, Any] = {
            "sessions": count,
            "explored": explored,
            "hibernate": hibernate,
            "before": before,
            "live": live,
        }
        if hibernate:
            between = request(process, "hibernate")
            assert between["on_disk"] == count, between
            assert between["live"] == 0, between
            assert between["sessions_freed"] == between["views_freed"] == count, between
            result["save_ms_per_session"] = between["save_s"] * 1000 / count
        else:
            between = live
        result["between"] = between
        opened.extend(_open_batch(browser, url, count, count, explored=explored))
        second = request(process, "snapshot")
        assert second["live"] == (count if hibernate else 2 * count), second
        result.update(
            second=second,
            first_batch_mib=live["rss_mib"] - before["rss_mib"],
            second_batch_mib=second["rss_mib"] - between["rss_mib"],
            total_mib=second["rss_mib"] - before["rss_mib"],
            py_blocks_total=second["py_blocks"] - before["py_blocks"],
        )
        if hibernate:
            wake_ms = _wake(first, explored=explored)
            woken = request(process, "snapshot")
            assert woken["live"] == 2 * count, woken
            assert woken["on_disk"] == 0, woken
            result.update(
                woken=woken,
                wake_page_ms=wake_ms,
                state_checks_passed=count,
                wake_page_median_ms=statistics.median(wake_ms),
                wake_page_p95_ms=sorted(wake_ms)[min(count - 1, int(count * 0.95))],
            )
        return result
    finally:
        for context, _page in opened:
            context.close()
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", type=int)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--sessions", type=int, default=50)
    parser.add_argument("--explorers", type=int, default=10)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.serve is not None:
        serve(args.serve)
        return
    import frameworks  # noqa: PLC0415
    from playwright.sync_api import sync_playwright  # noqa: PLC0415

    assert args.output is not None
    python = frameworks._environment_python(  # noqa: SLF001
        "composeui", "3.12", ["-e", f"{frameworks.REPOSITORY}[web]"]
    )
    cases = {
        f"{name}_{mode}": (count, explored, mode == "hibernated")
        for name, count, explored in (
            ("first_page", args.sessions, False),
            ("all_pages", args.explorers, True),
        )
        for mode in ("kept", "hibernated")
    }
    runs: dict[str, list[dict[str, Any]]] = {name: [] for name in cases}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        environment = frameworks._environment(browser, "3.12")  # noqa: SLF001
        for repeat in range(args.repeat):
            for name, (count, explored, hibernate) in cases.items():
                print(f"Run {repeat + 1}: {name}, 2 x {count} sessions", file=sys.stderr)  # noqa: T201
                runs[name].append(
                    measure(browser, python, count, explored=explored, hibernate=hibernate)
                )
        browser.close()
    keys = (
        "first_batch_mib",
        "second_batch_mib",
        "total_mib",
        "py_blocks_total",
        "save_ms_per_session",
        "wake_page_median_ms",
        "wake_page_p95_ms",
    )
    summary = {
        name: {
            key: statistics.median(run[key] for run in samples) for key in keys if key in samples[0]
        }
        for name, samples in runs.items()
    }
    for name in ("first_page", "all_pages"):
        summary[f"{name}_hibernated"]["rss_saved_mib"] = (
            summary[f"{name}_kept"]["total_mib"] - summary[f"{name}_hibernated"]["total_mib"]
        )
    results = {
        "environment": environment,
        "method": {
            "app": "benchmarks/twins/composeui_app.py (20 pages, 10 rows per page)",
            "command": (
                "uv run --group browser python benchmarks/idle_sessions.py "
                "--output benchmarks/results/idle-sessions-<commit>.json"
            ),
            "batches": (
                "Each case opens a first batch of sessions, then a second batch of the same "
                "size. 'kept' keeps the first batch in memory; 'hibernated' saves it to disk "
                "between the batches. CPython rarely returns freed memory to the system, so RSS "
                "doesn't drop after a sweep: the second batch reuses it instead. rss_saved_mib "
                "is the kept case's total_mib minus the hibernated case's."
            ),
            "session_idle_s": 3600,
            "hibernation": (
                "After browser requests settle, set idle to 0 for one explicit hibernate_idle "
                "sweep, then restore 3600. The natural timer delay is not measured."
            ),
            "memory": (
                "Server process RSS after gc.collect at every snapshot, and Python's allocated "
                "blocks (sys.getallocatedblocks); no malloc_trim. Browser memory excluded. "
                "Fresh server for each case and repeat, no warm-up."
            ),
            "save": "Wall time of the explicit sweep, excludes the snapshot's gc.collect.",
            "wake": (
                "Sequential browser page.reload until content and persisted input are checked; "
                "includes HTTP, restore, rendering and browser work. "
                "Not the stale-action HX-Refresh path."
            ),
            "checks": (
                "All sessions/views freed after save; exact LIVE/ON_DISK counts; "
                "input value, URL and signed cookie payload preserved for every wake."
            ),
        },
        "summary": summary,
        "runs": runs,
    }
    args.output.write_text(json.dumps(results, indent=2) + "\n")


if __name__ == "__main__":
    main()

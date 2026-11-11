r"""Compare ComposeUI's web backend with Streamlit, Panel and Dash, on one app of 20 pages.

Each framework serves its twin of the app (`twins/`) from a real server, in a virtual
environment of its own on one Python, built with `uv` at pinned versions. Headless Chromium
drives it through Playwright, as a user does. The server's whole process tree is measured from
Linux's `/proc`: its memory (RSS) and its CPU time.

For each framework and repeat, on a new server:

- **start:** from its launch to its first answer;
- **first page:** a new browser context, until the page's ten Apply buttons show;
- **bytes:** what a new browser context receives for its first page, HTTP and WebSocket;
- **click:** an Apply, until its label says so;
- **page switch:** a link (a tab on Panel), until the page's buttons show;
- **bytes per interaction:** what the page sends and receives for a click, a page switch, and
  a text typed into a row's input, HTTP and WebSocket bodies;
- **per session:** the memory and CPU time of 50 sessions kept open, per session;
- **explored:** the memory of 10 sessions that opened every page, per session.

    uv run --group browser python benchmarks/frameworks.py \\
        --output benchmarks/results/frameworks-<commit>.json
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import socket
import statistics
import subprocess
import sys
import tarfile
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from playwright.sync_api import sync_playwright

if TYPE_CHECKING:
    from playwright.sync_api import Browser, BrowserContext, Page, Request, WebSocket

REPOSITORY = Path(__file__).resolve().parent.parent
TWINS = Path(__file__).resolve().parent / "twins"
CACHE = Path.home() / ".cache" / "composeui-bench" / "frameworks"
#: the versions measured: change them to measure others
PINS = {
    "Streamlit": ["streamlit==1.67.0"],
    "Panel": ["panel==1.10.0"],
    "Dash": ["dash==4.5.0", "gunicorn==27.0.0"],
}
PAGES = 20
ROWS = 10
#: the pages a session switches to, back and forth, to time a switch
SWITCHES = (5, 0, 7, 0, 12, 0, 3, 0, 19, 0)
#: interactions of each kind weighed, the median taken
INTERACTIONS = 6
#: milliseconds for the page to be quiet, before and after an interaction weighed
SETTLE = 1000
PAGE_SIZE = os.sysconf("SC_PAGE_SIZE")
TICKS = os.sysconf("SC_CLK_TCK")
MIB = 1024 * 1024


@dataclass
class Server:
    """How to start a framework's server, and how its page switches pages."""

    name: str
    command: Callable[[int], list[str]]
    path: str = "/"
    #: "link": a link named "Page <n>"; "text": a tab found by its text (Panel's have no role)
    navigation: str = "link"
    environment: dict[str, str] = field(default_factory=dict)
    versions: dict[str, str] = field(default_factory=dict)


def _run(command: list[str]) -> None:
    subprocess.run(command, check=True, capture_output=True)  # noqa: S603 (our own commands)


def _environment_python(name: str, python: str, packages: list[str]) -> Path:
    """Get the Python of a virtual environment with `packages`, made once into the cache."""
    directory = CACHE / f"{name}-py{python}"
    interpreter = directory / "bin" / "python"
    if not interpreter.exists():
        _run(["uv", "venv", "--quiet", "--python", python, str(directory)])
        _run(["uv", "pip", "install", "--quiet", "--python", str(interpreter), *packages])
    return interpreter


def _commit_sources(commit: str) -> Path:
    """Get the `src` folder of ComposeUI at `commit`, extracted once into the cache."""
    directory = CACHE / "commits" / commit
    if not (directory / "src").exists():
        directory.mkdir(parents=True, exist_ok=True)
        archive = directory / "src.tar"
        with archive.open("wb") as output:
            subprocess.run(  # noqa: S603
                ["git", "archive", commit, "src"],  # noqa: S607 (git from PATH)
                cwd=REPOSITORY,
                stdout=output,
                check=True,
            )
        with tarfile.open(archive) as tar:
            tar.extractall(directory, filter="data")
        archive.unlink()
    return directory / "src"


def _servers(python: str, commits: list[str], names: list[str]) -> list[Server]:
    """Get the servers to measure: this checkout's ComposeUI, then `commits`', then the others."""
    composeui = _environment_python("composeui", python, ["-e", f"{REPOSITORY}[web]"])
    app = str(TWINS / "composeui_app.py")
    servers = [Server("ComposeUI", lambda port: [str(composeui), app, str(port)])]
    servers.extend(
        Server(
            f"ComposeUI {commit}",
            lambda port: [str(composeui), app, str(port)],
            # first on the path: before the checkout that the environment installs
            environment={"PYTHONPATH": str(_commit_sources(commit))},
        )
        for commit in commits
    )
    if "Streamlit" in names:
        streamlit = _environment_python("streamlit", python, PINS["Streamlit"]).parent
        servers.append(
            Server(
                "Streamlit",
                lambda port: [
                    str(streamlit / "streamlit"),
                    "run",
                    str(TWINS / "streamlit_app.py"),
                    "--server.port",
                    str(port),
                    "--server.headless",
                    "true",
                    "--browser.gatherUsageStats",
                    "false",
                    "--server.fileWatcherType",
                    "none",
                ],
            )
        )
    if "Panel" in names:
        panel = _environment_python("panel", python, PINS["Panel"]).parent
        servers.append(
            Server(
                "Panel",
                lambda port: [
                    str(panel / "panel"),
                    "serve",
                    str(TWINS / "panel_app.py"),
                    "--port",
                    str(port),
                    "--address",
                    "127.0.0.1",
                    "--allow-websocket-origin",
                    f"127.0.0.1:{port}",
                ],
                path="/panel_app",
                navigation="text",
            )
        )
    if "Dash" in names:
        dash = _environment_python("dash", python, PINS["Dash"]).parent
        servers.append(
            Server(
                "Dash",
                lambda port: [
                    str(dash / "gunicorn"),
                    "-w",
                    "1",
                    "--threads",
                    "8",
                    "-b",
                    f"127.0.0.1:{port}",
                    "--chdir",
                    str(TWINS),
                    "dash_app:server",
                ],
            )
        )
    for server in servers:
        server.versions = {
            pin.split("==")[0]: pin.split("==")[1] for pin in PINS.get(server.name, [])
        }
    return servers


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _read(path: Path) -> str:
    """Read a file of `/proc`: empty if its process or task ended meanwhile."""
    try:
        return path.read_text()
    except OSError:
        return ""


def _tree(pid: int) -> list[int]:
    """Get `pid` and its descendants, e.g. gunicorn's worker."""
    pids, todo = [], [pid]
    while todo:
        current = todo.pop()
        pids.append(current)
        for children in Path(f"/proc/{current}/task").glob("*/children"):
            todo.extend(int(child) for child in _read(children).split())
    return pids


def _rss_mib(pid: int) -> float:
    pages = (_read(Path(f"/proc/{process}/statm")).split() for process in _tree(pid))
    return sum(int(fields[1]) for fields in pages if fields) * PAGE_SIZE / MIB


def _cpu_seconds(pid: int) -> float:
    # after the process's name, in parentheses: utime and stime are its 12th and 13th fields
    stats = (_read(Path(f"/proc/{process}/stat")).rpartition(")")[2] for process in _tree(pid))
    times = (fields.split()[11:13] for fields in stats if fields)
    return sum(int(user) + int(system) for user, system in times) / TICKS


class _Traffic:
    """The bytes that a page sent and received, by HTTP and WebSocket: the bodies, not headers."""

    def __init__(self, page: Page) -> None:
        self.size = 0
        self.sent = 0
        page.on("requestfinished", self._request)
        page.on("websocket", self._websocket)

    def _request(self, request: Request) -> None:
        sizes = request.sizes()
        # as on the wire: compressed, when the server compresses
        self.size += max(sizes["responseBodySize"], 0)
        self.sent += max(sizes["requestBodySize"], 0)

    def _websocket(self, websocket: WebSocket) -> None:
        websocket.on("framereceived", self._frame)
        websocket.on("framesent", self._sent)

    def _frame(self, payload: str | bytes) -> None:
        self.size += len(payload)

    def _sent(self, payload: str | bytes) -> None:
        self.sent += len(payload)


def _wait_for_page(page: Page, number: int) -> None:
    page.get_by_text(f"Content {number}", exact=True).wait_for()
    page.get_by_role("button", name="Apply", exact=True).nth(ROWS - 1).wait_for()


def _open(browser: Browser, url: str) -> tuple[BrowserContext, Page, float]:
    """Open the app in a new browser context: a new session. With the time to its first page."""
    context = browser.new_context()
    page = context.new_page()
    start = time.perf_counter()
    page.goto(url)
    _wait_for_page(page, 0)
    return context, page, time.perf_counter() - start


def _switch(page: Page, server: Server, number: int) -> None:
    name = f"Page {number}"
    if server.navigation == "link":
        page.get_by_role("link", name=name, exact=True).first.click()
    else:
        page.get_by_text(name, exact=True).first.click()
    _wait_for_page(page, number)


def _start(server: Server, port: int) -> tuple[subprocess.Popen[bytes], float]:
    environment = {**os.environ, **server.environment}
    start = time.perf_counter()
    process = subprocess.Popen(  # noqa: S603 (our own command)
        server.command(port),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=environment,
    )
    url = f"http://127.0.0.1:{port}{server.path}"
    deadline = start + 60
    while time.perf_counter() < deadline:
        try:
            urllib.request.urlopen(url, timeout=1)  # noqa: S310 (a local http URL)
            break
        except OSError:
            time.sleep(0.05)
    else:
        process.kill()
        msg = f"{server.name} did not answer within 60 s"
        raise RuntimeError(msg)
    return process, time.perf_counter() - start


def _timings(browser: Browser, server: Server, url: str) -> dict[str, float]:
    """Time a first page, a click and a page switch; weigh a first page."""
    firsts = []
    for _ in range(10):
        context, _page, seconds = _open(browser, url)
        firsts.append(seconds)
        context.close()
    context = browser.new_context()
    page = context.new_page()
    received = _Traffic(page)
    page.goto(url)
    _wait_for_page(page, 0)
    # the frames after the page shows; not `time.sleep`, which holds back the page's events
    page.wait_for_timeout(1000)
    context.close()
    context, page, _seconds = _open(browser, url)
    clicks = []
    for row in range(ROWS):
        start = time.perf_counter()
        page.get_by_role("button", name="Apply", exact=True).nth(row).click()
        page.get_by_text(f"Applied {row}", exact=True).wait_for()
        clicks.append(time.perf_counter() - start)
    switches = []
    for number in SWITCHES:
        start = time.perf_counter()
        _switch(page, server, number)
        switches.append(time.perf_counter() - start)
    context.close()
    return {
        "first_page_ms": statistics.median(firsts) * 1000,
        "first_page_kib": received.size / 1024,
        "click_ms": statistics.median(clicks) * 1000,
        "switch_ms": statistics.median(switches) * 1000,
    }


def _interaction(page: Page, traffic: _Traffic, action: Callable[[], object]) -> tuple[int, int]:
    """Give the bytes sent and received for `action`, once the page is quiet again."""
    # not `time.sleep`: Playwright gives the page's events only while it waits itself
    page.wait_for_timeout(SETTLE)
    sent, received = traffic.sent, traffic.size
    action()
    # the requests that end after the page shows the change, e.g. a second post
    page.wait_for_timeout(SETTLE)
    return traffic.sent - sent, traffic.size - received


def _traffic(browser: Browser, server: Server, url: str) -> dict[str, float]:
    """Weigh a click, a page switch and a text typed, in both directions: the medians."""
    context = browser.new_context()
    page = context.new_page()
    traffic = _Traffic(page)
    page.goto(url)
    _wait_for_page(page, 0)

    def click(row: int) -> None:
        page.get_by_role("button", name="Apply", exact=True).nth(row).click()
        page.get_by_text(f"Applied {row}", exact=True).wait_for()

    def type_text(row: int) -> None:
        field = page.get_by_role("textbox").nth(row)
        field.fill(f"Some text in row {row}")
        # the change: the frameworks that wait for it send then
        field.press("Tab")

    measured: dict[str, list[tuple[int, int]]] = {"click": [], "switch": [], "type": []}
    for row in range(INTERACTIONS):
        measured["type"].append(_interaction(page, traffic, lambda row=row: type_text(row)))
        measured["click"].append(_interaction(page, traffic, lambda row=row: click(row)))
    for number in SWITCHES[:INTERACTIONS]:
        measured["switch"].append(
            _interaction(page, traffic, lambda number=number: _switch(page, server, number))
        )
    context.close()
    return {
        f"{name}_{direction}_b": statistics.median(pair[index] for pair in pairs)
        for name, pairs in measured.items()
        for index, direction in enumerate(("sent", "received"))
    }


def _sessions(
    browser: Browser, server: Server, url: str, pid: int, counts: tuple[int, int]
) -> dict[str, float]:
    """Measure the memory and CPU time of sessions kept open, then of sessions opening each page."""
    sessions, explorers = counts
    time.sleep(2)
    before, cpu_before = _rss_mib(pid), _cpu_seconds(pid)
    opened = [_open(browser, url)[0] for _ in range(sessions)]
    time.sleep(3)
    after, cpu_after = _rss_mib(pid), _cpu_seconds(pid)
    for context in opened:
        context.close()
    time.sleep(3)
    before_exploring = _rss_mib(pid)
    exploring = []
    for _ in range(explorers):
        context, page, _seconds = _open(browser, url)
        for number in range(1, PAGES):
            _switch(page, server, number)
        exploring.append(context)
    time.sleep(3)
    after_exploring = _rss_mib(pid)
    for context in exploring:
        context.close()
    return {
        "session_kib": (after - before) / sessions * 1024,
        "session_cpu_ms": (cpu_after - cpu_before) / sessions * 1000,
        "explored_kib": (after_exploring - before_exploring) / explorers * 1024,
    }


def _measure(browser: Browser, server: Server, counts: tuple[int, int]) -> dict[str, float]:
    """Measure `server` once, on a new server."""
    port = _free_port()
    process, started = _start(server, port)
    url = f"http://127.0.0.1:{port}{server.path}"
    try:
        for _ in range(3):  # warm up: imports, caches
            _open(browser, url)[0].close()
        time.sleep(2)
        idle = _rss_mib(process.pid)
        timings = _timings(browser, server, url)
        sessions = _sessions(browser, server, url, process.pid, counts)
        # after the memory: Panel frees a closed session later, during the next measure
        traffic = _traffic(browser, server, url)
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    return {"start_s": started, "idle_mib": idle, **timings, **traffic, **sessions}


def _environment(browser: Browser, python: str) -> dict[str, Any]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],  # noqa: S607 (git from PATH)
        capture_output=True,
        text=True,
        check=False,
        cwd=REPOSITORY,
    ).stdout.strip()
    return {
        "commit": commit,
        "python": python,
        "platform": platform.platform(),
        "processor": platform.processor() or platform.machine(),
        "cpus": os.cpu_count(),
        "chromium": browser.version,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    others = ["Streamlit", "Panel", "Dash"]
    parser.add_argument("--frameworks", nargs="*", choices=others, default=others)
    parser.add_argument("--commits", nargs="*", default=[], help="Older ComposeUI commits too.")
    parser.add_argument("--python", default="3.12", help="The servers' Python, for them all.")
    parser.add_argument("--repeat", type=int, default=3, help="Runs of each, on a new server.")
    parser.add_argument("--sessions", type=int, default=50, help="Sessions kept open.")
    parser.add_argument("--explorers", type=int, default=10, help="Sessions opening each page.")
    parser.add_argument("--output", type=Path, help="Where to write the JSON results.")
    arguments = parser.parse_args()
    servers = _servers(arguments.python, arguments.commits, arguments.frameworks)
    runs: dict[str, list[dict[str, float]]] = {server.name: [] for server in servers}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        environment = _environment(browser, arguments.python)
        for repeat in range(arguments.repeat):
            for server in servers:
                print(f"Run {repeat + 1}: {server.name}", file=sys.stderr)  # noqa: T201
                counts = (arguments.sessions, arguments.explorers)
                runs[server.name].append(_measure(browser, server, counts))
        browser.close()
    summary = {
        name: {key: statistics.median(run[key] for run in measured) for key in measured[0]}
        for name, measured in runs.items()
    }
    results = {
        "environment": environment,
        "versions": {server.name: server.versions for server in servers},
        "summary": summary,
        "runs": runs,
    }
    text = json.dumps(results, indent=2)
    if arguments.output is not None:
        arguments.output.write_text(text + "\n")
    print(text)  # noqa: T201


if __name__ == "__main__":
    main()

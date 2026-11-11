"""Measure what a web session costs as an app grows: its memory, and its first page's time.

The apps are built from the frameworks benchmark's row (`twins/composeui_app.py`): a label,
a text input, an int input, a checkbox and a button. Two kinds of growth:

- **sections:** one page of N sections of 10 rows, all shown;
- **pages:** a router of N pages of 10 rows, one shown.

Each app serves its sessions through Starlette's test client, in this process: the memory of
a session is what Python allocates for it (`tracemalloc`), per session of 20.

    uv run python benchmarks/sizes.py --output benchmarks/results/sizes-<commit>.json
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import platform
import statistics
import subprocess
import sys
import time
import tracemalloc
from pathlib import Path
from typing import Any, cast

from starlette.testclient import TestClient
from twins.composeui_app import ROWS, Row

from composeui.core.view import MainView, PageView, Router, VerticalView, child, define_view
from composeui.webcore.webapplication import WebApplication

#: sessions measured together, for the memory of one
SESSIONS = 20
#: first pages timed, for their median
FIRST_PAGES = 30


def _class(name: str, base: type, fields: dict[str, Any]) -> type:
    """Define the view class `name`: each field a child view of the class given."""
    namespace: dict[str, Any] = {field: child(cls) for field, cls in fields.items()}
    namespace["__annotations__"] = dict(fields)
    return define_view(type(name, (base,), namespace))


def _rows(name: str, base: type) -> type:
    namespace: dict[str, Any] = {f"r{row}": child(Row, index=row) for row in range(ROWS)}
    namespace["__annotations__"] = dict.fromkeys(namespace, Row)
    return define_view(type(name, (base,), namespace))


def sections_app(count: int) -> type[MainView]:
    """Get a main view of one page: `count` sections of rows, all shown."""
    section = _rows(f"Section{count}", VerticalView)
    fields = {f"s{number}": section for number in range(count)}
    return _main_view(f"Sections{count}", fields)


def pages_app(count: int) -> type[MainView]:
    """Get a main view of a router of `count` pages of rows, one shown."""
    pages = {}
    for number in range(count):
        page = _rows(f"Page{count}_{number}", PageView)
        page.route = f"p{number}"
        page.page_title = f"Page {number}"
        pages[f"p{number}"] = page
    return _main_view(f"Pages{count}", {"pages": _class(f"Router{count}", Router, pages)})


def _main_view(name: str, fields: dict[str, type]) -> type[MainView]:
    main_view = cast("type[MainView]", _class(name, MainView, fields))
    main_view.app_title = name
    main_view.extension = ".bench"
    return main_view


def _count(view: Any) -> int:
    return 1 + sum(_count(child_view) for child_view in view.children_views)


def measure(main_view: type[MainView]) -> dict[str, float]:
    """Measure the sessions of `main_view`: their memory and their first page."""
    built: list[Any] = []

    class App(WebApplication[MainView]):
        def setup_session(self, view: MainView) -> None:
            built.append(view)

    starlette = App(build_main_view=main_view).create_starlette_app()
    with TestClient(starlette) as warm:
        warm.get("/")  # imports, caches
        gc.collect()
        clients = [TestClient(starlette) for _ in range(SESSIONS)]
        tracemalloc.start()
        gc.collect()
        before = tracemalloc.get_traced_memory()[0]
        for client in clients:
            page = client.get("/")
        gc.collect()
        after = tracemalloc.get_traced_memory()[0]
        tracemalloc.stop()
        firsts = []
        for _ in range(FIRST_PAGES):
            client = TestClient(starlette)
            start = time.perf_counter()
            client.get("/")
            firsts.append(time.perf_counter() - start)
    return {
        "views": _count(built[-1]),
        "session_kib": (after - before) / SESSIONS / 1024,
        "first_page_ms": statistics.median(firsts) * 1000,
        "page_kib": len(page.content) / 1024,
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
        # the checkout's: with `PYTHONPATH`, the version measured is the folder imported
        "commit": commit,
        "imported_from": str(Path(composeui.__file__).parent),
        "pythonpath": os.environ.get("PYTHONPATH", ""),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "processor": platform.processor() or platform.machine(),
        "cpus": os.cpu_count(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sections", nargs="*", type=int, default=[2, 10, 40, 65])
    parser.add_argument("--pages", nargs="*", type=int, default=[1, 5, 10, 20])
    parser.add_argument("--output", type=Path, help="Where to write the JSON results.")
    arguments = parser.parse_args()
    results: dict[str, Any] = {"environment": _environment(), "sections": {}, "pages": {}}
    for count in arguments.sections:
        print(f"{count} sections", file=sys.stderr)  # noqa: T201
        results["sections"][count] = measure(sections_app(count))
    for count in arguments.pages:
        print(f"{count} pages", file=sys.stderr)  # noqa: T201
        results["pages"][count] = measure(pages_app(count))
    text = json.dumps(results, indent=2)
    if arguments.output is not None:
        arguments.output.write_text(text + "\n")
    print(text)  # noqa: T201


if __name__ == "__main__":
    main()

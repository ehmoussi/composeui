"""Take the screenshots of the examples guide on every backend (`make screenshots`).

It also takes the screenshot of the README's quickstart, from the code in the README.

Each example is set up as a reader would leave it (a form filled in, records added, a job
run to its end) before it is rendered, so that the three backends show the same state.
The images go to `docs/images/`, as `<example>-<backend>.png`, in the light theme.

Qt renders offscreen and grabs its window, Textual exports its screen as an SVG, and
headless Chromium shows the web page and turns Textual's SVG into a PNG. It needs the
`browser` dependency group and a Chromium: `uv run --group browser playwright install
chromium` once.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime
import os
import random
import re
import socket
import sys
import threading
import time
import types
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional, cast

import attrs
import uvicorn
from playwright.sync_api import sync_playwright
from qtpy.QtWidgets import QApplication

from composeui.core.registry import RendererType
from composeui.qtcore.qtapplication import QtApplication, QtModelApplication
from composeui.textualcore.textualapplication import TextualApplication, TextualModelApplication
from composeui.webcore.webapplication import WebApplication, WebModelApplication
from examples import (
    batman,
    markdownviewer,
    pipecatalogue,
    pipechart,
    pipeform,
    pipesweep,
    taskview,
    textual_demo,
    webhello,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from playwright.sync_api import Browser
    from starlette.applications import Starlette

    from composeui.core.application import Application
    from composeui.core.model import Model
    from composeui.core.view import MainView

ROOT = Path(__file__).resolve().parent.parent
IMAGES = ROOT / "docs" / "images"
#: the window's size on Qt and the page's on the web, in pixels
WINDOW = (1200, 800)
#: the terminal's size on Textual, in columns and rows
TERMINAL = (120, 40)

Prepare = Callable[["Any", "Optional[Model]"], None]


@attrs.frozen
class Example:
    """An example of `src/examples/`, and how to set it up for its screenshots."""

    name: str
    build_main_view: Callable[[], MainView]
    prepare: Prepare = lambda _main_view, _model: None
    build_model: Optional[Callable[[], Model]] = None
    setup_model: Optional[Callable[[Any, Any], None]] = None
    backends: tuple[str, ...] = ("qt", "textual", "web")
    #: the web app's class, when the example has its own
    web_application: Optional[Callable[..., Any]] = None
    #: the window's size on Qt and the page's on the web, in pixels
    window: tuple[int, int] = WINDOW


def _quiet(main_view: MainView) -> None:
    # a status bar message stays: no timer thread clearing it while the image is taken
    main_view.status_bar.timeout = 0


def _pipeform(main_view: Any, _model: Optional[Model]) -> None:
    form = main_view.pages.inputs.pipe_form
    form.name.text = "Junction A"
    form.material.value = pipeform.Material.Copper
    form.insulated.is_checked = True
    form.insulated.toggled.emit(True)  # noqa: FBT003
    form.main_pipe.radius.value, form.main_pipe.width.value = 50.0, 10.0
    form.main_pipe.half_length.value = 200.0
    form.incident_pipe.radius.value, form.incident_pipe.width.value = 30.0, 8.0
    form.incident_pipe.half_length.value = 120.0
    form.edge_type.value = pipeform.EdgeType.Fillet
    form.edge_type.value_changed.emit(pipeform.EdgeType.Fillet)
    form.check()


def _pipecatalogue(main_view: Any, _model: Optional[Model]) -> None:
    materials = pipecatalogue.Material
    pipes = [
        ("Header", materials.STEEL, (80.0, 8.0, 12.0), datetime.date(2026, 3, 2)),
        ("Branch north", materials.STEEL, (40.0, 4.0, 6.0), datetime.date(2026, 4, 15)),
        ("Drain", materials.PVC, (55.0, 3.0, 20.0), None),
        ("Feed line", materials.COPPER, (15.0, 1.0, 9.0), datetime.date(2026, 9, 30)),
    ]
    form = main_view.add.pipe
    for name, material, (radius, thickness, length), installed in pipes:
        form.name.text = name
        form.name.text_edited.emit(name)  # as typed: its check runs
        form.material.value = material
        form.radius.value, form.thickness.value, form.length.value = radius, thickness, length
        form.installed.value = installed
        main_view.add.add_pipe.clicked.emit()
    main_view.catalogue.browser.pipes.item_views[0].is_expanded = True


def _pipechart(main_view: Any, _model: Optional[Model]) -> None:
    for diameter in (40.0, 50.0, 65.0):
        main_view.pipe.diameter.value = diameter
        main_view.add_curve()
    main_view.add_measurements()


def _pipesweep(main_view: Any, _model: Optional[Model]) -> None:
    pipesweep.SOLVE_SECONDS = 0
    form = main_view.form
    form.pressure.value, form.thickness.value = 2.0, 5.0
    form.min_radius.value, form.max_radius.value, form.steps.value = 20.0, 60.0, 12
    main_view.buttons.run.clicked.emit()
    main_view.jobs.wait()


def _taskview(main_view: Any, _model: Optional[Model]) -> None:
    # the same durations and failures on every backend, and from one run to the next
    random.seed(7)
    main_view.config.min_duration.value, main_view.config.max_duration.value = 1, 3
    # two runs: the metrics then show how each count changed since the last one
    for _ in range(2):
        main_view.buttons.run.clicked.emit()
        main_view.jobs.wait(timeout=30)


def _markdownviewer(main_view: Any, _model: Optional[Model]) -> None:
    readme = ROOT / "README.md"
    main_view.markdown_file.text = "README.md"
    main_view.open_markdown(readme)


def _webhello(main_view: Any, _model: Optional[Model]) -> None:
    main_view.form.name.text = "Ada"
    main_view.form.name.text_edited.emit("Ada")
    main_view.form.age.value = 36.0
    main_view.form.age.text_edited.emit("36")
    main_view.form.colour.value = webhello.Colour.GREEN
    main_view.form.colour.value_changed.emit(webhello.Colour.GREEN)


def _textual_demo(main_view: Any, _model: Optional[Model]) -> None:
    form = main_view.form
    form.name.text = "widget-42"
    form.name.text_edited.emit("widget-42")
    form.shape.value = "HEXAGON"
    form.shape.value_changed.emit("HEXAGON")


def _quickstart_main_view() -> Callable[[], MainView]:
    """Get the main view of the README's quickstart, run from the README's own code."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    quickstart = readme[readme.index("## Quickstart") :]
    match = re.search(r"```python\n(.*?)```", quickstart, re.DOTALL)
    if match is None:
        msg = "README.md: no Python code under its Quickstart"
        raise ValueError(msg)
    # a module of its own, for `attrs` to resolve the views' types from its globals
    module = types.ModuleType("quickstart")
    sys.modules[module.__name__] = module
    exec(compile(match.group(1), "README.md", "exec"), module.__dict__)  # noqa: S102 (the repo's own README)
    return cast("Callable[[], MainView]", module.HelloMainView)


def _quickstart(main_view: Any, _model: Optional[Model]) -> None:
    main_view.greeting.text = "Ada"
    main_view.greeting.text_edited.emit("Ada")


def _examples() -> list[Example]:
    return [
        Example(
            "quickstart",
            _quickstart_main_view(),
            _quickstart,
            backends=("web",),
            window=(900, 360),
        ),
        Example("pipeform", pipeform.PipeMainView, _pipeform),
        Example(
            "pipecatalogue",
            pipecatalogue.PipeCatalogueMainView,
            _pipecatalogue,
            pipecatalogue.PipeCatalogueModel,
            pipecatalogue.PipeCatalogueMainView.connect_model,
        ),
        Example("pipechart", pipechart.PipeChartMainView, _pipechart),
        Example(
            "pipesweep",
            pipesweep.PipeSweepMainView,
            _pipesweep,
            pipesweep.PipeSweepModel,
            pipesweep.PipeSweepMainView.connect_model,
        ),
        Example("taskview", taskview.TaskMainView, _taskview),
        Example("batman", batman.BatmanMainView),
        Example("markdownviewer", markdownviewer.MarkdownViewerMainView, _markdownviewer),
        Example(
            "webhello",
            webhello.HelloMainView,
            _webhello,
            backends=("web",),
            web_application=webhello.HelloApp,
        ),
        Example("textual_demo", textual_demo.TextualDemoMainView, _textual_demo),
    ]


def _application(example: Example, application: Any, model_application: Any) -> Application[Any]:
    """Build the app of `example` with the backend's classes, then set it up."""
    if example.build_model is None:
        app = application(build_main_view=example.build_main_view)
        model = None
    else:
        app = model_application(
            build_main_view=example.build_main_view,
            build_model=example.build_model,
            setup_model=example.setup_model,
        )
        model = app.model
    _quiet(app.main_view)
    example.prepare(app.main_view, model)
    return app


def _close(app: Any) -> None:
    model = getattr(app, "model", None)
    if model is not None:
        model.close()


def qt_screenshot(example: Example, path: Path) -> None:
    qt_app = QApplication.instance() or QApplication(sys.argv[:1])
    app = _application(example, QtApplication, QtModelApplication)
    app.render(RendererType.QT)
    window = app.main_view.renderer.qt_object
    window.resize(*example.window)
    window.show()
    # a few passes: layouts settle, and pyqtgraph draws its charts once shown
    for _ in range(10):
        qt_app.processEvents()
        time.sleep(0.05)
    window.grab().save(str(path))
    window.close()
    _close(app)


def textual_svg(example: Example) -> str:
    app = _application(example, TextualApplication, TextualModelApplication)

    async def export() -> str:
        # rendered in the event loop: on Python 3.9, a widget's lock takes the running one
        app.render(RendererType.TEXTUAL)
        textual_app = app.main_view.renderer.app
        async with textual_app.run_test(size=TERMINAL) as pilot:
            textual_app.theme = "textual-light"
            await pilot.pause(0.5)
            # the focus may have scrolled the screen: show it from the top, as it opens
            for widget in textual_app.screen.query("*"):
                if widget.is_scrollable:
                    widget.scroll_home(animate=False)
            await pilot.pause(0.2)
            return str(textual_app.export_screenshot())

    try:
        return asyncio.run(export())
    finally:
        _close(app)


def svg_to_png(browser: Browser, svg: str, path: Path) -> None:
    page = browser.new_page()
    page.set_content(f'<body style="margin:0;background:#fff">{svg}</body>')
    page.wait_for_timeout(300)
    page.locator("svg").first.screenshot(path=str(path))
    page.close()


def _web_starlette_app(example: Example) -> Starlette:
    prepare = example.prepare
    if example.build_model is None:
        base = example.web_application or WebApplication

        class PreparedApp(base):  # type: ignore[misc, valid-type]
            def setup_session(self, main_view: MainView) -> None:
                super().setup_session(main_view)
                _quiet(main_view)
                prepare(main_view, None)

        app = (
            PreparedApp()
            if example.web_application is not None
            else PreparedApp(build_main_view=example.build_main_view)
        )
    else:

        class PreparedModelApp(WebModelApplication):  # type: ignore[type-arg]
            def setup_model(self, main_view: MainView, model: Model) -> None:
                super().setup_model(main_view, model)
                _quiet(main_view)
                prepare(main_view, model)

        app = PreparedModelApp(
            build_main_view=example.build_main_view,
            build_model=example.build_model,
            setup_model=example.setup_model,
        )
    return app.create_starlette_app()


@contextlib.contextmanager
def _serve(app: Starlette) -> Iterator[str]:
    """Serve `app` on a free local port while the block runs; yield its base url."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.01)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join()


def web_screenshot(browser: Browser, example: Example, path: Path) -> None:
    with _serve(_web_starlette_app(example)) as url:
        context = browser.new_context(
            viewport={"width": example.window[0], "height": example.window[1]},
            color_scheme="light",
        )
        page = context.new_page()
        page.goto(url)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(500)
        page.screenshot(path=str(path))
        context.close()


def main() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    names = set(sys.argv[1:])
    examples = [example for example in _examples() if not names or example.name in names]
    IMAGES.mkdir(parents=True, exist_ok=True)
    # Qt and Textual first: Playwright's sync API keeps an event loop running, which
    # Textual's own can't run beside
    svgs: dict[Path, str] = {}
    for example in examples:
        if "qt" in example.backends:
            path = IMAGES / f"{example.name}-qt.png"
            qt_screenshot(example, path)
            print(path.relative_to(ROOT))  # noqa: T201
        if "textual" in example.backends:
            svgs[IMAGES / f"{example.name}-textual.png"] = textual_svg(example)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for path, svg in svgs.items():
            svg_to_png(browser, svg, path)
            print(path.relative_to(ROOT))  # noqa: T201
        for example in examples:
            if "web" in example.backends:
                path = IMAGES / f"{example.name}-web.png"
                web_screenshot(browser, example, path)
                print(path.relative_to(ROOT))  # noqa: T201
        browser.close()


if __name__ == "__main__":
    main()

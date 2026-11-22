"""Tests of the Textual labels, images, Markdown, consoles, metrics, logs, notification, status."""

from __future__ import annotations

import pytest

pytest.importorskip("textual")
pytest.importorskip("textual_fspicker")

import asyncio
import io
import os
import sys
import types
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
from attrs import Factory
from PIL import Image as PILImage
from textual.containers import VerticalScroll
from textual.geometry import Region
from textual.widgets import (
    Button,
    Label,
    Markdown,
    Static,
)
from textual.widgets.markdown import MarkdownBlock
from textual_fspicker import FileSave

from composeui.core.registry import RendererType
from composeui.core.view import (
    ImageView,
    LabelView,
    LogType,
    MainView,
    TextRole,
    define_view,
)
from composeui.textualcore._renderers.navigation import TextualMainRenderer
from composeui.textualcore.textualrenderer import TextualWidgetRenderer
from composeui.textualcore.widgets import composeimage
from composeui.textualcore.widgets.composeconsole import ComposeConsoleBox
from composeui.textualcore.widgets.composeimage import ComposeImage
from composeui.textualcore.widgets.composemarkdown import ComposeMarkdown
from composeui.textualcore.widgets.composemetric import ComposeMetric
from examples.pipeform import PipeMainView
from tests.console import MAX_LINES, ColoredRunMainView, RunMainView
from tests.markdown import HelpMainView
from tests.metrics import JobsMainView

if TYPE_CHECKING:
    from textual.message import Message
    from textual.pilot import Pilot
    from textual.widget import Widget


from tests.textualcore.support import _app_of, _field_widget, _names, _widget


@pytest.mark.asyncio
async def test_long_log_message_wraps_instead_of_being_clipped() -> None:
    """Check that a long validation message wraps instead of being clipped.

    A `Label`'s default `width: auto` sizes it to its *unwrapped* text - fine for
    a short field label, but a validation message can be long (see
    `PipeFormView._display_error_message`), and left at `auto` it silently overflows
    past the terminal width and gets clipped by the parent's `overflow: hidden`
    instead of wrapping onto more lines.
    """
    view = PipeMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None

    async with app.run_test(size=(80, 40)) as pilot:
        await pilot.pause()
        # Set up values that trip the validation directly on the view, then blur a
        # field for real (through the widget) to run `_display_error_message` via
        # its actual `editing_finished` wiring, not by calling it directly.
        view.pages.inputs.pipe_form.main_pipe.radius.value = 100.0
        view.pages.inputs.pipe_form.main_pipe.width.value = 150.0
        radius_widget = _field_widget(view.pages.inputs.pipe_form.main_pipe.radius.renderer)
        radius_widget.focus()
        await pilot.press("tab")
        await pilot.pause()

        message = view.pages.inputs.pipe_form.log_view.log_message
        assert len(message) > 80  # long enough that width:auto would overflow
        log_renderer = view.pages.inputs.pipe_form.log_view.renderer
        assert isinstance(log_renderer, TextualWidgetRenderer)
        widget = log_renderer.widget
        assert widget is not None
        assert widget.size.width <= 80  # wrapped within the screen, not clipped
        assert widget.size.height > 1  # actually wrapped onto more than one line


@pytest.mark.asyncio
async def test_a_notification_stays_above_the_scrolling_content_until_the_user_closes_it() -> None:
    view = PipeMainView()
    app = _app_of(view)
    closes: list[str] = []
    view.notification.closed.connect(lambda: closes.append(view.notification.message))

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = _widget(view.notification)
        assert not bar.display  # an empty bar takes no room

        view.notify("Can't save to a.pipe: the disk is full.", LogType.ERROR)
        await pilot.pause()

        assert bar.display
        assert "the disk is full" in str(bar.query_one(Static).render())
        content = app.screen.query_one(VerticalScroll)
        assert bar.region.bottom <= content.region.y
        shown_at = bar.region
        content.scroll_end(animate=False)
        await pilot.pause()
        assert content.scroll_y > 0
        assert bar.region == shown_at  # the content scrolls beneath it

        assert await pilot.click(bar.query_one(Button))
        await pilot.pause()

        assert not bar.display
        assert view.notification.message == ""
        assert closes == [""]


@pytest.mark.asyncio
async def test_a_metric_shows_its_change_as_a_badge_colored_by_sign() -> None:
    view = JobsMainView()
    view.summary.running.delta_format = ".1f"
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    running, failed = view.summary.running.renderer, view.summary.failed.renderer
    assert isinstance(running, TextualWidgetRenderer)
    assert isinstance(failed, TextualWidgetRenderer)
    running_metric, failed_metric = running.widget, failed.widget
    assert isinstance(running_metric, ComposeMetric)
    assert isinstance(failed_metric, ComposeMetric)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert str(running_metric.value.render()) == "3"
        assert str(running_metric.badge.render()) == "↑ 2.0 since yesterday"
        assert not failed_metric.badge.display  # no change given
        # side by side in their row
        assert failed_metric.region.x > running_metric.region.x
        rise = running_metric.badge.styles.color

        view.summary.running.delta = -2
        view.summary.failed.delta = 0
        await pilot.pause()
        assert str(running_metric.badge.render()) == "↓ 2.0 since yesterday"
        assert running_metric.badge.styles.color != rise
        assert failed_metric.badge.display

        view.summary.running.delta_format = ".2f"
        await pilot.pause()
        assert str(running_metric.badge.render()) == "↓ 2.00 since yesterday"
        view.summary.running.delta_text = ""
        view.summary.failed.delta = None
        view.summary.failed.delta_format = ".1f"
        await pilot.pause()
        assert str(running_metric.badge.render()) == "↓ 2.00"
        assert not failed_metric.badge.display

        rise_from_pandas: Any = np.float64(1.5)  # numpy 2.0's stubs don't make it a float
        view.summary.running.delta = rise_from_pandas
        await pilot.pause()
        assert str(running_metric.badge.render()) == "↑ 1.50"


def _shown_blocks(markdown: ComposeMarkdown) -> list[tuple[str, str]]:
    """Return the document's top blocks: each one's kind and Markdown."""
    return [
        (type(block).__name__, block.source or "")
        for block in markdown.children
        if isinstance(block, MarkdownBlock)
    ]


@pytest.mark.asyncio
async def test_the_markdown_shows_its_text_formatted() -> None:
    view = HelpMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    assert isinstance(view.help.renderer, TextualWidgetRenderer)
    markdown = view.help.renderer.widget
    assert isinstance(markdown, ComposeMarkdown)

    expected = [
        ("MarkdownH1", "# Help\n"),
        ("MarkdownBulletList", "- Open a study\n- Run it\n"),
    ]
    rendered = asyncio.Event()

    def document_updated(message: Message) -> None:
        if (
            isinstance(message, Markdown.TableOfContentsUpdated)
            and message.markdown is markdown
            and _shown_blocks(markdown) == expected
        ):
            rendered.set()

    async with app.run_test(message_hook=document_updated):
        await asyncio.wait_for(rendered.wait(), timeout=5)
        assert _shown_blocks(markdown) == expected
        # set twice in a row: only the last text shows, once
        expected = [
            ("MarkdownH2", "## Results\n"),
            ("MarkdownParagraph", "All done."),
        ]
        rendered.clear()
        view.help.text = "## Results"
        view.help.text = "## Results\n\nAll done."
        await asyncio.wait_for(rendered.wait(), timeout=5)
        assert _shown_blocks(markdown) == expected


@pytest.mark.asyncio
async def test_a_console_adds_its_lines_scrolled_to_its_end_unless_the_user_scrolled_up() -> None:
    view = RunMainView()
    app = _app_of(view)
    box = _widget(view.output)
    assert isinstance(box, ComposeConsoleBox)
    console = box.log_view

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        assert list(console.lines) == ["Ready <ok>", ""]

        view.run.clicked.emit()
        await pilot.pause()
        assert "\n".join(console.lines) == view.output.text
        assert console.max_scroll_y > 0
        assert console.is_vertical_scroll_end
        # the user scrolls up: the next run's lines, the oldest dropped, don't scroll down
        console.scroll_home(animate=False, immediate=True)
        view.run.clicked.emit()
        await pilot.pause()
        assert "\n".join(console.lines) == view.output.text
        assert len(console.lines) == MAX_LINES + 1
        assert not console.is_vertical_scroll_end

        view.output.text = "New run"
        await pilot.pause()
        assert list(console.lines) == ["New run"]


@pytest.mark.asyncio
async def test_a_console_s_search_highlights_its_matches_and_keeps_the_current_one() -> None:
    view = RunMainView()
    app = _app_of(view)
    box = _widget(view.output)
    assert isinstance(box, ComposeConsoleBox)
    console = box.log_view

    def matches() -> str:
        return str(box.matches.render())

    def background(y: int, x: int) -> str | None:
        """Get the background of a cell of the console, as drawn."""
        cells = [(s.style, len(s.text)) for s in console.render_line(y - int(console.scroll_y))]
        for style, width in cells:
            if x < width:
                return None if style is None or style.bgcolor is None else style.bgcolor.name
            x -= width
        return None

    async with app.run_test(size=(100, 30)) as pilot:
        view.run.clicked.emit()
        console.focus()
        await pilot.pause()
        footer = [binding.description for (_, binding, *_rest) in app.active_bindings.values()]
        assert "Search" in footer

        await pilot.press("slash")
        # the search takes focus once the app has run `/`: typed sooner, the keys go to the
        # console, whose `s` saves
        for _ in range(100):
            if app.focused is box.search:
                break
            await pilot.pause(0.05)
        await pilot.press(*"step 1")  # Step 1, then Step 10 to Step 19
        await pilot.pause()
        assert app.focused is box.search
        assert matches() == "1 of 11"
        assert (background(1, 0), background(10, 0)) == ("#f59e0b", "#fde68a")
        await pilot.press("enter")
        await pilot.pause()
        assert matches() == "2 of 11"
        assert background(10, 0) == "#f59e0b"  # Step 10, current
        console.focus()
        await pilot.press("N")
        await pilot.pause()
        assert matches() == "1 of 11"
        await pilot.press("n")
        await pilot.pause()

        # the next run drops the oldest lines, Step 10 among them: Step 11, next, is current
        view.run.clicked.emit()
        await pilot.pause()
        assert matches() == "1 of 9"
        box.search.focus()
        await pilot.press("x", "enter")  # step 1x
        await pilot.pause()
        assert matches() == "No match"

        await pilot.press("escape")
        await pilot.pause()
        assert not box.has_class("-searching")
        assert (box.search.value, matches()) == ("", "")
        assert app.focused is console


@pytest.mark.asyncio
async def test_a_console_shows_its_ansi_colors_and_drops_them_when_asked() -> None:
    view = ColoredRunMainView()
    app = _app_of(view)
    box = _widget(view.output)
    assert isinstance(box, ComposeConsoleBox)
    console = box.log_view

    def look(y: int, x: int) -> tuple[str | None, str | None, bool]:
        """Get a cell's color, background and weight, as drawn."""
        for segment in console.render_line(y - int(console.scroll_y)):
            if x < len(segment.text):
                style = segment.style
                assert style is not None
                color = None if style.color is None else style.color.name
                background = None if style.bgcolor is None else style.bgcolor.name
                return color, background, bool(style.bold)
            x -= len(segment.text)
        return None, None, False

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        assert list(console.lines) == ["ERROR <x> bg", "green"]
        plain = look(0, 4)  # "R", after the reset
        assert look(0, 0)[::2] == ("#cd3131", True)
        assert look(0, 10)[1] == "#0dbc79"
        assert look(1, 0)[0] == "#0dbc79"
        view.more.clicked.emit()  # the green line ends, a plain one comes
        await pilot.pause()
        assert (look(1, 6)[0], look(2, 0)) == ("#2472c8", plain)  # blue

        view.output.ansi_colors = False
        await pilot.pause()
        assert [look(y, 0) for y in range(3)] == [plain] * 3


@pytest.mark.asyncio
async def test_a_console_s_key_copies_its_whole_text() -> None:
    view = RunMainView()
    app = _app_of(view)
    box = _widget(view.output)
    assert isinstance(box, ComposeConsoleBox)
    console = box.log_view

    async with app.run_test(size=(100, 30)) as pilot:
        view.output.append("Progress 50%")  # the line being written too
        console.focus()
        await pilot.pause()
        footer = [binding.description for (_, binding, *_rest) in app.active_bindings.values()]
        assert "Copy all" in footer

        await pilot.press("c")
        await pilot.pause()
        assert app.clipboard == "Ready <ok>\nProgress 50%"


@pytest.mark.asyncio
@pytest.mark.parametrize("is_cancelled", [False, True])
async def test_a_console_s_key_saves_its_text_where_the_user_picks(
    tmp_path: Path, *, is_cancelled: bool
) -> None:
    view = RunMainView()
    app = _app_of(view)
    box = _widget(view.output)
    assert isinstance(box, ComposeConsoleBox)
    console = box.log_view

    async with app.run_test(size=(100, 30)) as pilot:
        console.focus()
        await pilot.pause()
        footer = [binding.description for (_, binding, *_rest) in app.active_bindings.values()]
        assert "Save output" in footer

        await pilot.press("s")
        await pilot.pause()
        assert isinstance(app.screen, FileSave)
        # as the dialog's Save button does, or Cancel
        app.screen.dismiss(None if is_cancelled else tmp_path / "run.log")
        await pilot.pause()

    if is_cancelled:
        assert _names(tmp_path) == []
    else:
        assert (tmp_path / "run.log").read_text(encoding="utf-8") == "Ready <ok>\n"


@define_view
class _LabelMainView(MainView):
    note: LabelView = Factory(lambda: LabelView(text="Plan"))


@pytest.mark.asyncio
async def test_a_label_s_role_sets_its_look_and_body_takes_it_back() -> None:
    view = _LabelMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None

    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(view.note.renderer, TextualWidgetRenderer)
        widget = view.note.renderer.widget
        assert widget is not None
        body_color = widget.styles.color

        view.note.role = TextRole.TITLE
        await pilot.pause()
        assert widget.styles.text_style.bold

        view.note.role = TextRole.ERROR
        await pilot.pause()
        assert not widget.styles.text_style.bold
        assert widget.styles.color != body_color

        view.note.role = TextRole.BODY
        await pilot.pause()
        assert widget.styles.color == body_color


@pytest.mark.asyncio
async def test_a_markdown_set_before_the_app_runs_shows_once_it_does() -> None:
    view = HelpMainView()
    app = _app_of(view)
    view.help.text = "# Other help"  # rendered, the app not running yet

    async with app.run_test() as pilot:
        await pilot.pause()
        markdown = _widget(view.help)
        assert isinstance(markdown, ComposeMarkdown)

        assert markdown.source == "# Other help"


def _picture(size: tuple[int, int]) -> bytes:
    content = io.BytesIO()
    PILImage.new("RGB", size, "red").save(content, format="PNG")
    return content.getvalue()


@define_view
class _ImageMainView(MainView):
    picture: ImageView = Factory(lambda: ImageView(description="A [b]curve"))


class _Pixels(Static):
    """Stands for a widget of `textual-image`, which only a terminal with graphics can draw."""

    image: Any = None


@pytest.fixture
def graphics(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(composeimage, "GRAPHICS", composeimage.Graphics(_Pixels, lambda: (10, 20)))


def _shown_text(image: ComposeImage) -> str:
    return image.query_one(Label).render_line(0).text.rstrip()


@pytest.mark.asyncio
async def test_a_terminal_without_graphics_shows_an_image_s_description_as_plain_text() -> None:
    view = _ImageMainView()
    view.picture.image = _picture((40, 20))
    app = _app_of(view)

    async with app.run_test(size=(40, 10)) as pilot:
        await pilot.pause()
        image = _widget(view.picture)
        assert isinstance(image, ComposeImage)
        assert _shown_text(image) == "A [b]curve"
        assert not image.query(_Pixels)

        view.picture.description = "Another curve"
        view.picture.height = 64
        await pilot.pause()
        assert _shown_text(image) == "Another curve"

        # rendered again, it keeps its widget
        assert isinstance(view.picture.renderer, TextualWidgetRenderer)
        view.picture.renderer.render()
        assert _widget(view.picture) is image


@pytest.mark.asyncio
@pytest.mark.usefixtures("graphics")
async def test_graphics_draw_an_image_at_its_size_or_shrunk_to_the_width() -> None:
    view = _ImageMainView()
    view.picture.image = _picture((400, 200))  # 40 by 10 cells of 10 by 20 pixels
    app = _app_of(view)

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        image = _widget(view.picture)
        assert isinstance(image, ComposeImage)
        pixels = image.query_one(_Pixels)
        assert pixels.display
        assert not image.query_one(Label).display
        assert pixels.image is not None
        assert pixels.image.size == (400, 200)
        assert (pixels.size.width, pixels.size.height) == (40, 10)

        await pilot.resize_terminal(20, 30)
        await pilot.pause()
        assert (pixels.size.width, pixels.size.height) == (image.size.width, image.size.width // 4)


async def _wait_for_size(pilot: Pilot[Any], widget: Widget, size: tuple[int, int]) -> None:
    """Wait for `widget`'s layout to give it `size`, or give up: a slow runner lays out later."""
    for _ in range(100):
        await pilot.pause(0.05)
        if (widget.size.width, widget.size.height) == size:
            break


@pytest.mark.asyncio
@pytest.mark.usefixtures("graphics")
async def test_graphics_draw_an_image_at_the_height_it_is_given_and_back() -> None:
    view = _ImageMainView()
    view.picture.image = _picture((40, 20))
    view.picture.height = 100  # 5 cells of 20 pixels, and so five times its width
    app = _app_of(view)

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        pixels = _widget(view.picture).query_one(_Pixels)
        await _wait_for_size(pilot, pixels, (20, 5))
        assert (pixels.size.width, pixels.size.height) == (20, 5)

        view.picture.height = None
        await _wait_for_size(pilot, pixels, (4, 1))
        assert (pixels.size.width, pixels.size.height) == (4, 1)


@pytest.mark.asyncio
@pytest.mark.usefixtures("graphics")
@pytest.mark.parametrize(
    "unreadable",
    [
        None,
        b"not an image",
        b"<svg xmlns='http://www.w3.org/2000/svg'/>",
        _picture((40, 20))[:40],  # cut short
        Path("missing.png"),
    ],
    ids=["none", "not an image", "svg", "cut short", "no file"],
)
async def test_graphics_show_the_description_for_what_pillow_cannot_read(
    unreadable: Path | bytes | None,
) -> None:
    view = _ImageMainView()
    view.picture.image = unreadable
    app = _app_of(view)

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        image = _widget(view.picture)
        assert isinstance(image, ComposeImage)
        pixels = image.query_one(_Pixels)
        assert not pixels.display
        assert _shown_text(image) == "A [b]curve"

        view.picture.image = _picture((40, 20))
        await pilot.pause()
        assert pixels.display
        assert not image.query_one(Label).display


def _fake_textual_image(drawn_by: str) -> dict[str, Any]:
    """Get the modules of `textual-image`, its renderer chosen as if it had asked the terminal."""
    renderers = {"sixel": object(), "tgp": object(), "halfcell": object()}
    renderable = types.SimpleNamespace(
        Image=renderers[drawn_by], SixelImage=renderers["sixel"], TGPImage=renderers["tgp"]
    )
    widget = types.SimpleNamespace(SixelImage="sixel", TGPImage="tgp", get_cell_size=object())
    return {"textual_image.renderable": renderable, "textual_image.widget": widget}


def _run_in_terminal(
    monkeypatch: pytest.MonkeyPatch, *, stdin: bool, stdout: bool, sized: bool = True
) -> None:
    """Make the process's stdin and stdout terminals or not, as `isatty` tells.

    Without `sized`, stdout's terminal has no size, as Windows answers for NUL.
    """

    def get_terminal_size(fd: int) -> os.terminal_size:
        assert fd == 1
        if not sized:
            raise OSError(fd)
        return os.terminal_size((80, 24))

    monkeypatch.setattr(sys, "__stdin__", types.SimpleNamespace(isatty=lambda: stdin))
    monkeypatch.setattr(
        sys, "__stdout__", types.SimpleNamespace(isatty=lambda: stdout, fileno=lambda: 1)
    )
    monkeypatch.setattr(os, "get_terminal_size", get_terminal_size)


@pytest.mark.parametrize(
    ("drawn_by", "expected"), [("sixel", "sixel"), ("tgp", "tgp"), ("halfcell", None)]
)
def test_only_a_terminal_with_pixels_uses_textual_image(
    monkeypatch: pytest.MonkeyPatch, drawn_by: str, expected: str | None
) -> None:
    """Its own fallback draws in characters: the view's description reads better."""
    _run_in_terminal(monkeypatch, stdin=True, stdout=True)
    monkeypatch.setattr(composeimage, "import_module", _fake_textual_image(drawn_by).__getitem__)

    graphics = composeimage.terminal_graphics()

    assert (None if graphics is None else graphics.widget) == expected


def test_without_textual_image_a_terminal_has_no_graphics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def not_installed(name: str) -> None:
        raise ImportError(name)

    _run_in_terminal(monkeypatch, stdin=True, stdout=True)
    monkeypatch.setattr(composeimage, "import_module", not_installed)

    assert composeimage.terminal_graphics() is None


@pytest.mark.parametrize(
    ("stdin", "stdout", "sized"), [(False, True, True), (True, False, True), (True, True, False)]
)
def test_textual_image_asks_nothing_without_a_terminal_to_answer(
    monkeypatch: pytest.MonkeyPatch, *, stdin: bool, stdout: bool, sized: bool
) -> None:
    """Its import writes a question and waits for the answer: a pipe never answers.

    Windows calls the NUL device a terminal, without a size: a Textual app with its stdin and
    stdout sent there, as in a pytest-xdist worker, waited forever as it started.
    """
    imported: list[str] = []

    def import_module(name: str) -> dict[str, Any]:
        imported.append(name)
        module: dict[str, Any] = _fake_textual_image("sixel")[name]
        return module

    _run_in_terminal(monkeypatch, stdin=stdin, stdout=stdout, sized=sized)
    monkeypatch.setattr(composeimage, "import_module", import_module)

    assert (composeimage.terminal_graphics(), imported) == (None, [])


@pytest.mark.asyncio
async def test_textual_image_s_sixel_widget_draws_an_image_in_the_view(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Its real widget, on the Textual installed: it reads the terminal's cells and its layout."""
    widget = pytest.importorskip("textual_image.widget")
    graphics = composeimage.Graphics(widget.SixelImage, lambda: (10, 20))
    monkeypatch.setattr(composeimage, "GRAPHICS", graphics)
    view = _ImageMainView()
    view.picture.image = _picture((400, 200))
    app = _app_of(view)

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        pixels = _widget(view.picture).query_one(widget.SixelImage)
        assert (pixels.size.width, pixels.size.height) == (40, 10)
        (drawing,) = pixels.children
        lines = drawing.render_lines(Region(0, 0, 40, 10))

    assert "\x1bP" in "".join(segment.text for line in lines for segment in line)

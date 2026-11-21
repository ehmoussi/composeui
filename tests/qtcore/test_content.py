"""Tests of the Qt labels, images, Markdown, consoles, metrics and status bar."""

from __future__ import annotations

import io
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pytest
from PIL import Image
from qtpy.QtCore import QSize, Qt
from qtpy.QtGui import (
    QFont,
    QPalette,
    QTextCursor,
)
from qtpy.QtWidgets import (
    QApplication,
    QFileDialog,
    QLabel,
    QMainWindow,
    QStatusBar,
    QTextBrowser,
    QWidget,
)

from composeui.core.registry import RendererType
from composeui.core.view import (
    ImageView,
    LabelView,
    TextRole,
)
from composeui.qtcore.qtrenderer import QtWidgetRenderer
from composeui.qtcore.widgets.qconsole import QConsoleBox
from composeui.qtcore.widgets.qimagelabel import QImageLabel
from composeui.qtcore.widgets.qmetric import QMetric
from examples.pipeform import PipeMainView
from tests.console import MAX_LINES, ColoredRunMainView, RunMainView
from tests.markdown import HelpMainView
from tests.metrics import JobsMainView

if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot


from tests.qtcore.support import _widget


def test_label_renderer_pushes_view_state_to_the_widget(qtbot: QtBot) -> None:
    view = LabelView()
    view.render(RendererType.QT)
    assert isinstance(view.renderer, QtWidgetRenderer)
    widget = view.renderer.qt_object
    assert isinstance(widget, QLabel)

    view.text = "hello"
    assert widget.text() == "hello"


def test_a_label_s_role_sets_its_look_and_body_takes_it_back(qtbot: QtBot) -> None:
    view = LabelView(text="Plan")
    view.render(RendererType.QT)
    assert isinstance(view.renderer, QtWidgetRenderer)
    widget = view.renderer.qt_object
    assert isinstance(widget, QLabel)
    qtbot.addWidget(widget)
    body_font, body_color_role = QFont(widget.font()), widget.foregroundRole()

    view.role = TextRole.TITLE
    assert widget.font().bold()
    assert widget.font().pointSizeF() > body_font.pointSizeF()

    view.role = TextRole.CAPTION
    assert not widget.font().bold()
    assert widget.font().pointSizeF() < body_font.pointSizeF()
    assert widget.foregroundRole() == QPalette.ColorRole.PlaceholderText

    view.role = TextRole.ERROR
    assert widget.font() == body_font
    assert widget.foregroundRole() == body_color_role
    assert "red" in widget.styleSheet()

    view.role = TextRole.BODY
    assert widget.styleSheet() == ""


def test_a_label_s_role_scales_an_app_font_set_in_pixels(qtbot: QtBot) -> None:
    app_font = QApplication.font()
    pixel_font = QFont(app_font)
    pixel_font.setPixelSize(20)
    QApplication.setFont(pixel_font)
    try:
        view = LabelView(text="Plan")
        view.render(RendererType.QT)
        assert isinstance(view.renderer, QtWidgetRenderer)
        widget = view.renderer.qt_object
        assert isinstance(widget, QLabel)
        qtbot.addWidget(widget)

        view.role = TextRole.TITLE

        assert widget.font().pixelSize() == 30
    finally:
        QApplication.setFont(app_font)


def _blocks(browser: QTextBrowser) -> list[tuple[str, int, bool]]:
    """Each paragraph of `browser`: its text, its heading level and whether it's listed."""
    blocks = []
    block = browser.document().firstBlock()
    while block.isValid():
        blocks.append(
            (block.text(), block.blockFormat().headingLevel(), block.textList() is not None)
        )
        block = block.next()
    return blocks


def test_markdown_renderer_shows_the_text_formatted(qtbot: QtBot) -> None:
    view = HelpMainView()
    view.render(RendererType.QT)
    renderer = view.help.renderer
    assert isinstance(renderer, QtWidgetRenderer)
    browser = renderer.qt_object
    assert isinstance(browser, QTextBrowser)
    assert browser.isReadOnly()
    assert browser.openExternalLinks()
    assert _blocks(browser) == [
        ("Help", 1, False),
        ("Open a study", 0, True),
        ("Run it", 0, True),
    ]

    view.help.text = "## Results\n\nAll [done](https://example.com)."
    assert _blocks(browser) == [("Results", 2, False), ("All done.", 0, False)]


def test_a_console_adds_its_lines_scrolled_to_its_end_unless_the_user_scrolled_up(
    qtbot: QtBot,
) -> None:
    view = RunMainView()
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.resize(800, 400)  # shorter than a run's lines
    window.show()
    qtbot.waitExposed(window)
    box = _widget(view.output)
    assert isinstance(box, QConsoleBox)
    console = box.text
    assert console.isReadOnly()
    # it scrolls within itself: down to the status bar, as Markdown does
    assert isinstance(window, QMainWindow)
    bottom = console.mapTo(window, console.rect().bottomLeft()).y()
    assert window.statusBar().geometry().top() - bottom < 30
    bar = console.verticalScrollBar()
    assert console.toPlainText() == "Ready <ok>\n"

    view.run.clicked.emit()
    assert console.toPlainText() == view.output.text
    assert bar.value() == bar.maximum() > 0
    # the user scrolls up: the next run's lines, the oldest dropped, don't scroll down
    bar.setValue(0)
    view.run.clicked.emit()
    assert console.toPlainText() == view.output.text
    assert console.blockCount() == MAX_LINES + 1
    assert bar.value() < bar.maximum()

    view.output.text = "New run"
    assert console.toPlainText() == "New run"


def test_a_console_s_search_highlights_its_matches_and_keeps_the_current_one(
    qtbot: QtBot,
) -> None:
    view = RunMainView()
    view.render(RendererType.QT)
    qtbot.addWidget(_widget(view))
    box = _widget(view.output)
    assert isinstance(box, QConsoleBox)
    view.run.clicked.emit()
    assert box.search.placeholderText() == "Search"

    def current() -> str:
        return box.text.textCursor().block().text()

    qtbot.keyClicks(box.search, "step 1")  # Step 1, then Step 10 to Step 19
    assert (box.matches.text(), current()) == ("1 of 11", "Step 1")
    assert len(box.text.extraSelections()) == 11
    qtbot.keyClick(box.search, Qt.Key.Key_Return)
    assert (box.matches.text(), current()) == ("2 of 11", "Step 10")
    qtbot.keyClick(box.search, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    qtbot.keyClick(box.search, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert (box.matches.text(), current()) == ("11 of 11", "Step 19")
    for _ in range(4):  # around the end, to Step 12
        qtbot.keyClick(box.search, Qt.Key.Key_Return)
    assert (box.matches.text(), current()) == ("4 of 11", "Step 12")

    # the next run drops the oldest lines, Step 1 to Step 10 among them: Step 12 stays current
    view.run.clicked.emit()
    assert box.matches.text() == "2 of 9"  # Step 11, then Step 12

    qtbot.keyClicks(box.search, "x")  # step 1x
    qtbot.keyClick(box.search, Qt.Key.Key_Return)
    assert (box.matches.text(), box.text.extraSelections()) == ("No match", [])
    qtbot.keyClick(box.search, Qt.Key.Key_Escape)
    assert (box.search.text(), box.matches.text(), box.text.extraSelections()) == ("", "", [])


def test_a_console_shows_its_ansi_colors_and_drops_them_when_asked(qtbot: QtBot) -> None:
    view = ColoredRunMainView()
    view.render(RendererType.QT)
    qtbot.addWidget(_widget(view))
    box = _widget(view.output)
    assert isinstance(box, QConsoleBox)
    document = box.text.document()

    def look(line: int, column: int) -> tuple[str, str, bool]:
        """Get a character's color, background and weight: bold or not."""
        block = document.findBlockByNumber(line)
        cursor = QTextCursor(block)
        cursor.setPosition(block.position() + column + 1)  # the format before the cursor
        text_format = cursor.charFormat()
        background = text_format.background()
        return (
            text_format.foreground().color().name(),
            background.color().name() if background.style() != Qt.BrushStyle.NoBrush else "",
            text_format.fontWeight() == QFont.Weight.Bold,
        )

    assert box.text.toPlainText() == "ERROR <x> bg\ngreen"
    plain = look(0, 4)  # "R", after the reset
    assert look(0, 0) == ("#cd3131", "", True)
    assert look(0, 10)[1] == "#0dbc79"
    assert look(1, 0)[0] == "#0dbc79"
    view.more.clicked.emit()  # the green line ends, a plain one comes
    assert (look(1, 6)[0], look(2, 0)) == ("#2472c8", plain)  # blue

    view.output.ansi_colors = False
    assert [look(line, 0) for line in range(3)] == [plain] * 3


def test_a_console_s_copy_button_copies_its_whole_text(qtbot: QtBot) -> None:
    view = RunMainView()
    view.render(RendererType.QT)
    qtbot.addWidget(_widget(view))
    box = _widget(view.output)
    assert isinstance(box, QConsoleBox)
    view.output.append("Progress 50%")  # the line being written too
    assert box.copy.text() == "Copy all"

    qtbot.mouseClick(box.copy, Qt.MouseButton.LeftButton)

    assert QApplication.clipboard().text() == "Ready <ok>\nProgress 50%"


@pytest.mark.parametrize("picked", ["run.log", ""])
def test_a_console_s_save_button_saves_its_text_where_the_user_picks(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, picked: str
) -> None:
    view = RunMainView()
    view.render(RendererType.QT)
    qtbot.addWidget(_widget(view))
    box = _widget(view.output)
    assert isinstance(box, QConsoleBox)
    asked: list[tuple[str, str]] = []

    def get_save_file_name(_parent: QWidget, caption: str, name: str) -> tuple[str, str]:
        asked.append((caption, name))
        return (str(tmp_path / picked) if picked else ""), ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", get_save_file_name)
    assert box.save.text() == "Save output…"

    qtbot.mouseClick(box.save, Qt.MouseButton.LeftButton)

    assert asked == [("Save output", "output.txt")]
    if picked:
        assert (tmp_path / picked).read_text(encoding="utf-8") == "Ready <ok>\n"
    else:  # cancelled
        assert list(tmp_path.iterdir()) == []


def test_status_bar_renderer_shows_a_message_on_the_widget(qtbot: QtBot) -> None:
    view = PipeMainView()
    # timeout=0, set before render(): `StatusBar` has no refresh handler for
    # "timeout" itself (only "message" is dispatched), so setting it once a
    # renderer is bound would raise `MissingRefreshAttributeFunctionError` via
    # `notify_renderer`. Zero also means no auto-dismiss `threading.Timer` is left
    # running past this test - it would otherwise eventually fire against an
    # already-deleted `QStatusBar` from a later test's own window (see
    # `tests/test_statusbar_thread_safety.py` for that timer's actual coverage).
    view.status_bar.timeout = 0
    view.render(RendererType.QT)
    renderer = view.status_bar.renderer
    assert isinstance(renderer, QtWidgetRenderer)
    widget = renderer.qt_object
    assert isinstance(widget, QStatusBar)

    view.status_bar.show_message("hi there")
    assert widget.currentMessage() == "hi there"


def test_a_metric_shows_its_value_large_and_its_change_as_a_badge_colored_by_sign(
    qtbot: QtBot,
) -> None:
    view = JobsMainView()
    view.summary.running.delta_format = ".1f"
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    running, failed = _widget(view.summary.running), _widget(view.summary.failed)
    assert isinstance(running, QMetric)
    assert isinstance(failed, QMetric)
    assert (running.label.text(), running.value.text()) == ("Running", "3")
    assert running.value.font().pointSizeF() > running.label.font().pointSizeF()
    assert running.badge.text() == "↑ 2.0 since yesterday"
    assert not failed.badge.isVisibleTo(window)  # no change given

    window.show()
    rise = running.badge.palette().color(running.badge.foregroundRole())
    view.summary.running.delta = -2
    running.badge.ensurePolished()
    fall = running.badge.palette().color(running.badge.foregroundRole())
    assert running.badge.text() == "↓ 2.0 since yesterday"
    assert rise != fall
    view.summary.running.delta_format = ".2f"
    assert running.badge.text() == "↓ 2.00 since yesterday"
    view.summary.running.delta_text = ""
    assert running.badge.text() == "↓ 2.00"
    view.summary.failed.delta_format = ".1f"
    assert not failed.badge.isVisibleTo(window)
    view.summary.failed.delta = 1
    assert failed.badge.isVisibleTo(window)
    assert failed.badge.text() == "↑ 1.0"
    fall_from_pandas: Any = np.float64(-1.5)  # numpy 2.0's stubs don't make it a float
    view.summary.failed.delta = fall_from_pandas
    assert failed.badge.text() == "↓ 1.5"


def _png(size: tuple[int, int], color: str = "red") -> bytes:
    content = io.BytesIO()
    Image.new("RGB", size, color).save(content, format="PNG")
    return content.getvalue()


def _image_label(qtbot: QtBot, view: ImageView) -> QImageLabel:
    view.render(RendererType.QT)
    assert isinstance(view.renderer, QtWidgetRenderer)
    label = view.renderer.qt_object
    assert isinstance(label, QImageLabel)
    qtbot.addWidget(label)
    return label


def test_an_image_shrinks_in_its_proportions_and_never_grows(qtbot: QtBot) -> None:
    label = _image_label(qtbot, ImageView(image=_png((40, 20))))

    assert label.sizeHint() == QSize(40, 20)
    assert label.minimumSizeHint().width() < 40  # a narrow column can shrink it
    assert label.heightForWidth(20) == 10
    assert label.heightForWidth(80) == 20

    label.resize(20, 100)
    drawn = label.grab().toImage()
    assert drawn.pixelColor(19, 9).name() == "#ff0000"
    assert drawn.pixelColor(19, 12).name() != "#ff0000"
    label.resize(100, 100)
    drawn = label.grab().toImage()
    assert drawn.pixelColor(39, 19).name() == "#ff0000"
    assert drawn.pixelColor(41, 19).name() != "#ff0000"


def test_an_image_grows_to_the_height_it_is_given_and_back(qtbot: QtBot) -> None:
    view = ImageView(image=_png((40, 20)), height=60)
    label = _image_label(qtbot, view)

    assert label.sizeHint() == QSize(120, 60)
    assert (label.minimumHeight(), label.maximumHeight()) == (60, 60)
    label.resize(200, 60)
    assert label.grab().toImage().pixelColor(119, 59).name() == "#ff0000"

    view.height = None

    assert label.sizeHint() == QSize(40, 20)
    assert label.minimumHeight() == 0


@pytest.mark.parametrize(
    "image", [None, b"not an image", Path("missing.png")], ids=["none", "unreadable", "no file"]
)
def test_an_image_it_cannot_draw_shows_its_description(
    qtbot: QtBot, image: Path | bytes | None
) -> None:
    label = _image_label(qtbot, ImageView(image=image, description="A <b>curve"))

    assert label.text() == "A <b>curve"
    assert label.accessibleName() == "A <b>curve"
    assert label.textFormat() == Qt.TextFormat.PlainText
    assert label.sizeHint().width() > 1  # the text's size, not an image's
    assert label.minimumSizeHint().width() > 1
    assert label.heightForWidth(200) > 0
    label.resize(200, 40)
    assert not label.grab().toImage().isNull()


def test_a_file_shows_as_an_image_and_a_new_image_replaces_it(qtbot: QtBot, tmp_path: Path) -> None:
    path = tmp_path / "logo.png"
    path.write_bytes(_png((10, 10)))
    view = ImageView(image=path, description="Logo")
    label = _image_label(qtbot, view)
    assert label.sizeHint() == QSize(10, 10)

    view.image = _png((30, 10), "blue")

    assert label.sizeHint() == QSize(30, 10)
    label.resize(30, 10)
    assert label.grab().toImage().pixelColor(29, 9).name() == "#0000ff"

    # rendered again, it keeps its widget
    assert isinstance(view.renderer, QtWidgetRenderer)
    view.renderer.render()
    assert view.renderer.qt_object is label

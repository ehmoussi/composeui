"""Tests of the example markdownviewer: a Markdown file shown, picked or named first."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("qtpy")
from qtpy.QtWidgets import QFileDialog, QMainWindow, QTextBrowser

from composeui.core.application import Application
from composeui.core.registry import RendererType
from composeui.qtcore.qtrenderer import QtWidgetRenderer
from examples.markdownviewer import MarkdownViewerMainView

if TYPE_CHECKING:
    from pathlib import Path

    from pytestqt.qtbot import QtBot


@pytest.fixture
def markdown_file(tmp_path: Path) -> Path:
    path = tmp_path / "notes.md"
    path.write_text("# Notes\n\n- été\n", encoding="utf-8")
    return path


def test_opening_a_file_shows_it_and_a_missing_one_says_why(
    markdown_file: Path, tmp_path: Path
) -> None:
    main_view = MarkdownViewerMainView()
    main_view.status_bar.timeout = 0
    main_view.open_markdown(markdown_file)
    assert main_view.document.text == "# Notes\n\n- été\n"
    assert main_view.status_bar.message == "notes.md"

    main_view.open_markdown(tmp_path / "missing.md")
    assert main_view.document.text == "# Notes\n\n- été\n"  # still the last file
    assert main_view.status_bar.message.startswith("Can't open 'missing.md': ")


def test_the_picked_file_fills_the_window(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, markdown_file: Path
) -> None:
    main_view = Application(build_main_view=MarkdownViewerMainView).main_view
    main_view.status_bar.timeout = 0
    main_view.render(RendererType.QT)
    assert isinstance(main_view.renderer, QtWidgetRenderer)
    window = main_view.renderer.qt_object
    assert isinstance(window, QMainWindow)
    qtbot.addWidget(window)
    window.resize(800, 600)
    window.show()
    qtbot.waitExposed(window)
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        staticmethod(lambda *_args: (str(markdown_file), "Markdown (*.md *.markdown)")),
    )
    action = main_view.markdown_menu.open_markdown.renderer
    assert isinstance(action, QtWidgetRenderer)
    action.qt_object.trigger()

    document = main_view.document.renderer
    assert isinstance(document, QtWidgetRenderer)
    browser = document.qt_object
    assert isinstance(browser, QTextBrowser)
    assert browser.toPlainText() == "Notes\nété"
    # it scrolls within itself: down to the status bar, no empty space under it
    status_bar_top = window.statusBar().geometry().top()
    browser_bottom = browser.mapTo(window, browser.rect().bottomLeft()).y()
    assert status_bar_top - browser_bottom < 30


def test_the_file_on_the_command_line_is_shown(
    monkeypatch: pytest.MonkeyPatch, markdown_file: Path
) -> None:
    monkeypatch.setattr(sys, "argv", ["markdownviewer", "--markdown", str(markdown_file)])
    app = Application(build_main_view=MarkdownViewerMainView)
    app.main_view.status_bar.timeout = 0
    app.run()
    assert app.main_view.document.text == "# Notes\n\n- été\n"

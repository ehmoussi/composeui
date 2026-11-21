"""Tests of the Qt actions, menus and toolbars."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from qtpy.QtCore import Qt
from qtpy.QtGui import (
    QAction,
    QColor,
    QPixmap,
)
from qtpy.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QLineEdit,
    QMainWindow,
    QMenu,
    QToolBar,
)

from composeui.core.application import _add_reference_to_signals
from composeui.core.registry import RendererType
from composeui.core.renderer import MainRenderer
from composeui.core.view import (
    ActionView,
)
from composeui.qtcore._renderers.actions import QtActionRenderer
from composeui.qtcore.qtrenderer import QtWidgetRenderer
from examples.pipeform import PipeMainView
from tests.markdown import HelpMainView, HelpViewerMainView
from tests.pages import (
    InputsPage,
)
from tests.toolbar import ToolBarMainView

if TYPE_CHECKING:
    from pathlib import Path

    import pytest
    from pytestqt.qtbot import QtBot


from tests.qtcore.support import _field_widget, _widget


def test_pick_file_action_hands_the_picked_file_over(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    view = HelpMainView()
    _add_reference_to_signals(view, None)  # `main_view` for the action, as an app does
    view.render(RendererType.QT)
    qtbot.addWidget(_widget(view))
    path = tmp_path / "notes.md"
    path.write_text("# Notes", encoding="utf-8")
    offered: list[str] = []

    def pick(*args: object) -> tuple[str, str]:
        offered.append(str(args[3]))
        return answer

    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(pick))
    renderer = view.help_menu.open_help.renderer
    assert isinstance(renderer, QtActionRenderer)
    action = renderer.qt_object
    assert isinstance(action, QAction)

    answer = ("", "")  # cancelled: nothing picked
    action.trigger()
    assert view.help.text.startswith("# Help")
    answer = (str(path), "Markdown (*.md *.markdown)")
    action.trigger()
    assert view.help.text == "# Notes"
    assert offered == ["Markdown (*.md *.markdown)"] * 2


def test_an_app_without_studies_has_no_file_menu(qtbot: QtBot) -> None:
    view = HelpViewerMainView()
    view.render(RendererType.QT)
    window = _widget(view)
    assert isinstance(window, QMainWindow)
    qtbot.addWidget(window)
    menus = [action.text() for action in window.menuBar().actions()]
    assert menus == ["Help"]
    # nor Ctrl+O, Ctrl+S... anywhere in the window
    shortcuts = [
        action.shortcut().toString()
        for action in window.findChildren(QAction)
        if not action.shortcut().isEmpty()
    ]
    assert shortcuts == ["Ctrl+H"]


def test_menu_renderer_builds_a_real_qmenu_with_actions_and_shortcuts(qtbot: QtBot) -> None:
    view = PipeMainView()
    view.render(RendererType.QT)
    assert isinstance(view.renderer, QtWidgetRenderer)
    window = view.renderer.qt_object
    assert isinstance(window, QMainWindow)

    menus = []
    for action in window.menuBar().actions():
        menu = action.menu()
        assert isinstance(menu, QMenu)
        menus.append(menu)
    assert [menu.title() for menu in menus] == ["File", "Pipe", "Language"]
    file_menu = menus[0]
    action_texts = [a.text() for a in file_menu.actions()]
    assert action_texts == ["New", "Open", "Save", "Save As", "", "Exit"]
    open_action = next(a for a in file_menu.actions() if a.text() == "Open")
    assert open_action.shortcut().toString() == "Ctrl+O"
    assert any(a.isSeparator() for a in file_menu.actions())


def test_a_checkable_action_and_its_qaction_toggle_together(qtbot: QtBot) -> None:
    window = QMainWindow()
    qtbot.addWidget(window)
    action = ActionView(text="Wrap", is_checkable=True)
    action.render(RendererType.QT)
    assert isinstance(action.renderer, QtActionRenderer)
    action.renderer.set_parent_rendered_object(window)
    action.renderer.render()
    qaction = action.renderer.qt_object
    assert isinstance(qaction, QAction)

    qaction.trigger()  # `QAction` checks itself before emitting `triggered`

    assert action.is_checked is True
    assert qaction.isChecked() is True

    qaction.trigger()

    assert action.is_checked is False
    assert qaction.isChecked() is False


def test_open_file_action_runs_the_native_dialog_and_loads_state(
    qtbot: QtBot,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    donor = PipeMainView()
    donor.pages.inputs.pipe_form.name.text = "loaded_name"
    filepath = tmp_path / "state.pipe"
    donor.save_state(filepath)

    view = PipeMainView()
    _add_reference_to_signals(view, None)  # OpenFileAction._load_state needs `main_view`
    view.render(RendererType.QT)
    assert isinstance(view.renderer, MainRenderer)

    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        staticmethod(lambda *args, **kwargs: (str(filepath), ".pipe (*.pipe)")),  # noqa: ARG005
    )

    open_action_renderer = view.file_menu.open_file.renderer
    assert isinstance(open_action_renderer, QtWidgetRenderer)
    action = open_action_renderer.qt_object
    assert action is not None
    action.trigger()

    assert view.file_view.filepath == filepath
    assert view.pages.inputs.pipe_form.name.text == "loaded_name"
    name_widget = _field_widget(view.pages.inputs.pipe_form.name)
    assert isinstance(name_widget, QLineEdit)
    assert name_widget.text() == "loaded_name"


def test_save_file_action_runs_the_native_dialog_and_saves_state(
    qtbot: QtBot,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    view = PipeMainView()
    _add_reference_to_signals(view, None)
    view.render(RendererType.QT)
    assert isinstance(view.renderer, MainRenderer)

    view.pages.inputs.pipe_form.name.text = "saved_name"
    target = tmp_path / "out"  # no extension - the renderer must add one
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *args, **kwargs: (str(target), ".pipe (*.pipe)")),  # noqa: ARG005
    )

    save_action_renderer = view.file_menu.save.renderer
    assert isinstance(save_action_renderer, QtWidgetRenderer)
    action = save_action_renderer.qt_object
    assert action is not None
    action.trigger()

    saved_path = target.with_suffix(".pipe")
    assert saved_path.exists()
    assert view.file_view.filepath == saved_path
    data = json.loads(saved_path.read_text())["views"]
    assert data["pages"]["inputs"]["pipe_form"]["name"]["text"] == "saved_name"


def test_a_toolbar_docks_its_actions_beside_the_pages(qtbot: QtBot) -> None:
    view = ToolBarMainView()
    _add_reference_to_signals(view, None)
    view.render(RendererType.QT)
    assert isinstance(view.renderer, QtWidgetRenderer)
    window = view.renderer.qt_object
    assert isinstance(window, QMainWindow)
    qtbot.addWidget(window)
    window.show()
    toolbar, pages = window.findChildren(QToolBar)
    assert window.toolBarArea(toolbar) == Qt.ToolBarArea.TopToolBarArea
    assert toolbar.windowTitle() == "Edit"
    assert [(action.text(), action.isSeparator()) for action in toolbar.actions()] == [
        ("Open", False),
        ("", True),
        ("Run", False),
        ("Wrap", False),
    ]
    assert [action.text() for action in pages.actions()] == ["Inputs", "Results"]
    _, _, run, wrap = toolbar.actions()

    qtbot.mouseClick(toolbar.widgetForAction(run), Qt.MouseButton.LeftButton)
    assert view.router.results.total.text == "Ran"
    qtbot.mouseClick(toolbar.widgetForAction(wrap), Qt.MouseButton.LeftButton)
    assert view.toolbar.wrap.is_checked
    view.toolbar.wrap.is_checked = False
    assert not wrap.isChecked()
    view.toolbar.is_enabled = False
    assert not toolbar.widgetForAction(run).isEnabled()


def test_an_action_without_a_qaction_ignores_changes_until_rendered(qtbot: QtBot) -> None:
    # a page outside a router: its entry, showing its title, has no toolbar to be in
    page = InputsPage()
    page.render(RendererType.QT)
    assert isinstance(page.action.renderer, QtActionRenderer)
    assert page.action.renderer.qt_object is None

    page.title = "Entrées"

    window = QMainWindow()
    qtbot.addWidget(window)
    page.action.renderer.set_parent_rendered_object(window)
    page.action.renderer.render()
    qaction = page.action.renderer.qt_object
    assert isinstance(qaction, QAction)
    assert qaction.text() == "Entrées"


def test_the_language_menu_relabels_the_window(qtbot: QtBot) -> None:
    view = PipeMainView()
    view.render(RendererType.QT)
    assert isinstance(view.renderer, QtWidgetRenderer)
    window = view.renderer.qt_object
    assert isinstance(window, QMainWindow)
    language_menu = window.menuBar().actions()[2].menu()
    assert isinstance(language_menu, QMenu)
    english, french = language_menu.actions()
    assert (english.isChecked(), french.isChecked()) == (True, False)

    french.trigger()

    assert window.windowTitle() == "Formulaire de conduite"
    assert [action.text() for action in window.menuBar().actions()] == [
        "Fichier",
        "Conduite",
        "Langue",
    ]
    assert (english.isChecked(), french.isChecked()) == (False, True)
    main_pipe = view.pages.inputs.pipe_form.main_pipe.renderer
    assert isinstance(main_pipe, QtWidgetRenderer)
    assert isinstance(main_pipe.qt_object, QGroupBox)
    assert main_pipe.qt_object.title() == "Conduite principale"


def test_an_action_shows_its_icon_until_it_has_none(qtbot: QtBot, tmp_path: Path) -> None:
    icon = tmp_path / "run.png"
    pixmap = QPixmap(16, 16)
    pixmap.fill(QColor("#2563eb"))
    assert pixmap.save(str(icon))
    view = ToolBarMainView()
    view.render(RendererType.QT)
    qtbot.addWidget(_widget(view))
    run = view.toolbar.run
    assert isinstance(run.renderer, QtActionRenderer)
    action = run.renderer.qt_object
    assert isinstance(action, QAction)

    run.icon = str(icon)
    shown = not action.icon().isNull()
    run.icon = None

    assert (shown, action.icon().isNull()) == (True, True)


def test_exit_closes_the_window(qtbot: QtBot) -> None:
    view = HelpMainView()
    _add_reference_to_signals(view, None)  # `main_view` for the action, as an app does
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)

    view.file_menu.exit_app.triggered.emit()

    assert not window.isVisible()

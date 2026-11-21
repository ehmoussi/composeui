"""Tests of the Qt dialogs."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest
from qtpy.QtCore import Qt
from qtpy.QtWidgets import (
    QApplication,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
)

from composeui.core.registry import RendererType
from composeui.core.view import (
    DialogKind,
)
from composeui.qtcore.qtrenderer import QtWidgetRenderer
from composeui.qtcore.widgets.qformdialog import QFormDialog
from composeui.qtcore.widgets.qwindowrelease import release_when_hidden
from tests.dialogs import DialogsMainView
from tests.formdialog import PipeMainView as EditedPipeMainView
from tests.latepages import LatePagesMainView
from tests.settingsdialog import NO_FOLDER, SettingsMainView
from tests.studydialog import StudyDialogMainView

if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot


from tests.qtcore.support import (
    _dialog_window,
    _field_widget,
    _late_pages_window,
    _qt_widget,
    _shown_buttons,
    _table,
    _widget,
)


def test_the_dialogs_of_pages_and_tabs_opened_before_the_window_show_over_it(
    qtbot: QtBot,
) -> None:
    view = LatePagesMainView()
    page = view.router.dialogs
    page.confirm.open()  # e.g. a question as the app starts
    page.tabs.tools.tool.open()
    view.render(RendererType.QT)
    window = _widget(view)
    assert isinstance(window, QMainWindow)
    qtbot.addWidget(window)
    window.show()

    for dialog in (page.confirm, page.tabs.tools.tool):
        box = _widget(dialog)
        assert isinstance(box, QMessageBox)
        assert box.isVisible()
        parent = box.parentWidget()
        assert parent is not None
        assert parent.window() is window


def test_the_dialogs_of_pages_and_tabs_not_built_open_over_the_window(qtbot: QtBot) -> None:
    view, window = _late_pages_window(qtbot)
    page = view.router.dialogs
    assert page.renderer is None
    answers: list[str] = []
    page.confirm.accepted.connect(lambda: answers.append("confirm"))
    page.tabs.tools.tool.accepted.connect(lambda: answers.append("tool"))

    for dialog in (page.confirm, page.tabs.tools.tool):
        dialog.open()
        box = _widget(dialog)
        assert isinstance(box, QMessageBox)
        assert box.isVisible()
        parent = box.parentWidget()
        assert parent is not None
        assert parent.window() is window
        _shown_buttons(box)["OK"].click()
        assert not box.isVisible()
    assert answers == ["confirm", "tool"]

    # open as its page and its tab view are built: they stay open, over the window
    page.rename.content.name.text = "Ada"
    page.rename.open()
    page.tabs.tools.tool.open()
    rename, tool = _widget(page.rename), _widget(page.tabs.tools.tool)
    name = _field_widget(page.rename.content.name)
    assert isinstance(name, QLineEdit)
    assert name.text() == "Ada"
    view.router.navigate("dialogs")
    for box in (rename, tool):
        assert box.isVisible()
        parent = box.parentWidget()
        assert parent is not None
        assert parent.window() is window
    page.rename.is_visible = False
    page.tabs.tools.tool.is_visible = False
    page.tabs.current_index = 1
    page.tabs.tools.tool.open()
    assert tool.isVisible()


def test_a_form_dialog_s_ok_follows_its_form_s_checks(qtbot: QtBot) -> None:
    view = EditedPipeMainView()
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.show()
    dialog = _widget(view.edit_dialog)
    assert isinstance(dialog, QFormDialog)
    parent = dialog.parentWidget()
    assert parent is not None
    assert parent.window() is window  # modal over the window
    name = _field_widget(view.edit_dialog.form.name)
    assert isinstance(name, QLineEdit)
    assert dialog.isAncestorOf(name)

    qtbot.mouseClick(_widget(view.edit), Qt.MouseButton.LeftButton)
    assert dialog.isVisible()
    assert dialog.windowTitle() == "Edit the pipe"
    assert dialog.ok_button.isEnabled()
    name.selectAll()
    qtbot.keyClick(name, Qt.Key.Key_Delete)
    assert not dialog.ok_button.isEnabled()  # a name is mandatory
    qtbot.keyClicks(name, "Return")
    assert dialog.ok_button.isEnabled()
    qtbot.mouseClick(dialog.ok_button, Qt.MouseButton.LeftButton)
    assert not dialog.isVisible()
    assert view.pipe.text == "Return, 12 m"

    qtbot.mouseClick(_widget(view.edit), Qt.MouseButton.LeftButton)
    qtbot.keyClicks(name, "!")
    qtbot.keyClick(dialog, Qt.Key.Key_Escape)  # Cancel
    assert not dialog.isVisible()
    assert view.pipe.text == "Return, 12 m"
    # its native window released (see the confirmation's), its form kept for next time
    qtbot.waitUntil(lambda: not dialog.testAttribute(Qt.WidgetAttribute.WA_WState_Created))
    qtbot.mouseClick(_widget(view.edit), Qt.MouseButton.LeftButton)
    assert dialog.isVisible()
    assert dialog.isAncestorOf(name)

    qtbot.keyClicks(name, "?")
    dialog.close()  # the title bar's button: as Cancel
    assert not dialog.isVisible()
    assert view.pipe.text == "Return, 12 m"


def test_a_content_dialog_shows_its_view_whose_buttons_leave_it_open(qtbot: QtBot) -> None:
    view = StudyDialogMainView()
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.show()
    dialog = _widget(view.open_dialog)
    assert isinstance(dialog, QFormDialog)
    content = view.open_dialog.content
    up, table = _widget(content.up), _table(content.entries)

    qtbot.mouseClick(_widget(view.open), Qt.MouseButton.LeftButton)
    assert dialog.isVisible()
    assert dialog.windowTitle() == "Open a study"
    assert all(dialog.isAncestorOf(widget) for widget in (_widget(content.folder), up, table))
    assert not dialog.ok_button.isEnabled()  # nothing selected yet
    qtbot.mouseClick(up, Qt.MouseButton.LeftButton)
    assert dialog.isVisible()
    assert table.model().index(0, 0).data() == "beam"

    beam = table.visualRect(table.model().index(0, 0)).center()
    qtbot.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=beam)
    assert dialog.ok_button.isEnabled()
    qtbot.mouseClick(dialog.ok_button, Qt.MouseButton.LeftButton)

    assert dialog.isVisible()  # a folder: shown, not opened
    assert table.model().index(0, 0).data() == "beam.export"
    assert not dialog.ok_button.isEnabled()


def test_a_dialog_s_own_buttons_and_check_show_in_qt_and_act_on_their_clicks(
    qtbot: QtBot,
) -> None:
    view = SettingsMainView()
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.show()
    settings = view.settings
    dialog = _widget(settings)
    assert isinstance(dialog, QFormDialog)
    apply, discard = _widget(settings.apply), _widget(settings.discard)
    folder, log = _widget(settings.content.folder), _widget(settings.log_view)
    assert isinstance(folder, QLineEdit)
    assert isinstance(log, QLabel)
    settings.open()
    assert {apply, discard} <= set(dialog.buttons.buttons())
    assert not log.isVisible()

    folder.selectAll()
    qtbot.keyClick(folder, Qt.Key.Key_Backspace)
    assert log.isVisible()
    assert dialog.isAncestorOf(log)
    assert NO_FOLDER in log.text()
    assert not dialog.ok_button.isEnabled()
    assert not apply.isEnabled()
    assert discard.isEnabled()

    qtbot.keyClicks(folder, "out")
    assert dialog.ok_button.isEnabled()
    qtbot.mouseClick(apply, Qt.MouseButton.LeftButton)
    assert dialog.isVisible()
    qtbot.mouseClick(discard, Qt.MouseButton.LeftButton)
    assert not dialog.isVisible()
    assert view.answers == ["apply", "discard"]


def test_escape_closes_the_restore_question_and_keeps_the_work_for_later(qtbot: QtBot) -> None:
    view = DialogsMainView()  # every main view has the question
    answers: list[str] = []
    view.restore_work.ask_restore(
        "2026-11-16 10:00",
        restore=lambda: answers.append("restore"),
        discard=lambda: answers.append("discard"),
        later=lambda: answers.append("later"),
    )
    view.render(RendererType.QT)
    assert isinstance(view.renderer, QtWidgetRenderer)
    window = view.renderer.qt_object
    assert isinstance(window, QMainWindow)
    qtbot.addWidget(window)
    window.show()
    box = _qt_widget(view.restore_work)
    assert isinstance(box, QMessageBox)
    assert list(_shown_buttons(box)) == ["Restore", "Discard"]

    qtbot.keyClick(box, Qt.Key.Key_Escape)
    # macOS clicks the Escape button with an animation, later
    qtbot.waitUntil(lambda: not box.isVisible())

    assert answers == ["later"]  # not Discard: the work isn't lost


def test_a_dialog_opened_before_the_window_is_built_shows_over_it(qtbot: QtBot) -> None:
    view = DialogsMainView()
    view.confirm_clear.open()  # e.g. a question as the app starts
    view.render(RendererType.QT)
    assert isinstance(view.renderer, QtWidgetRenderer)
    window = view.renderer.qt_object
    assert isinstance(window, QMainWindow)
    qtbot.addWidget(window)
    window.show()
    box = _qt_widget(view.confirm_clear)
    assert isinstance(box, QMessageBox)

    assert box.isVisible()
    assert box.parentWidget() is window.centralWidget()
    _shown_buttons(box)["Clear"].click()
    assert not view.confirm_clear.is_visible


def test_a_confirmation_opens_over_the_window_and_answers_with_its_buttons(
    qtbot: QtBot,
) -> None:
    view, window, box = _dialog_window(qtbot)
    assert not box.isVisible()

    view.edit_menu.clear.triggered.emit()
    assert box.isVisible()
    assert box.isModal()
    assert box.window() is not window
    parent = box.parentWidget()
    assert parent is not None
    assert parent.window() is window
    # macOS shows no title on a message box: its bold text is the title there
    shown = (
        (box.text(), box.informativeText())
        if sys.platform == "darwin"
        else (box.windowTitle(), box.text())
    )
    assert shown == ("Clear the name", "The name will be lost.")
    buttons = _shown_buttons(box)
    assert list(buttons) == ["Clear", "Cancel"]

    qtbot.keyClick(box, Qt.Key.Key_Escape)
    # macOS clicks the Escape button with an animation, later
    qtbot.waitUntil(lambda: not box.isVisible())
    assert not view.confirm_clear.is_visible
    assert view.name.text == "Ada"

    view.confirm_clear.open()
    view.confirm_clear.is_visible = False  # closed by the app, not by the box itself
    # its native window released, which WSLg's compositor could otherwise keep drawing
    qtbot.waitUntil(lambda: not box.testAttribute(Qt.WidgetAttribute.WA_WState_Created))
    view.confirm_clear.open()
    assert box.isVisible()  # in a native window of its own again
    qtbot.mouseClick(buttons["Clear"], Qt.MouseButton.LeftButton)
    assert not box.isVisible()
    assert view.name.text == ""


def test_a_dialog_s_title_is_its_bold_text_where_a_message_box_has_no_title(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("composeui.qtcore._renderers.dialogs._TITLE_AS_TEXT", True)  # as on macOS
    view, _window, box = _dialog_window(qtbot)

    view.confirm_clear.open()
    assert (box.text(), box.informativeText()) == ("Clear the name", "The name will be lost.")

    view.confirm_clear.title = ""  # then the message is the bold text
    assert (box.text(), box.informativeText()) == ("The name will be lost.", "")


def test_a_message_has_one_button_and_escape_or_closing_accepts_it(qtbot: QtBot) -> None:
    view, _window, box = _dialog_window(qtbot)
    dialog = view.confirm_clear
    dialog.kind = DialogKind.MESSAGE

    dialog.open()
    assert list(_shown_buttons(box)) == ["Clear"]
    qtbot.keyClick(box, Qt.Key.Key_Escape)
    qtbot.waitUntil(lambda: view.name.text == "")  # at once, or after macOS's animation

    view.name.text = "Ada"
    dialog.open()
    box.close()  # from its window's title bar
    assert not dialog.is_visible
    assert view.name.text == ""


@pytest.mark.parametrize("is_destructive", [True, False])
def test_enter_rejects_a_destructive_confirmation_and_accepts_another(
    qtbot: QtBot, *, is_destructive: bool
) -> None:
    view, _window, box = _dialog_window(qtbot)
    dialog = view.confirm_clear
    dialog.is_destructive = is_destructive

    dialog.open()
    qtbot.keyClick(box, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: not dialog.is_visible)
    assert view.name.text == ("Ada" if is_destructive else "")


def test_a_dialog_shown_again_at_once_keeps_its_native_window(qtbot: QtBot) -> None:
    dialog = QMessageBox()
    qtbot.addWidget(dialog)
    release_when_hidden(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)

    dialog.hide()
    dialog.show()
    QApplication.processEvents()  # the release the hide queued

    assert dialog.testAttribute(Qt.WidgetAttribute.WA_WState_Created)

"""The Qt driver: keys typed into the field's line edit, in an active window."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from qtpy.QtCore import Qt
from qtpy.QtWidgets import QLineEdit

from composeui.core.registry import RendererType
from tests.qtcore.support import _widget

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from pytestqt.qtbot import QtBot

    from composeui.core.view import MainView, View


class QtDriver:
    def __init__(self, qtbot: QtBot) -> None:
        self._qtbot = qtbot

    @asynccontextmanager
    async def open(self, main_view: MainView) -> AsyncGenerator[None, None]:
        main_view.render(RendererType.QT)
        window = _widget(main_view)
        self._qtbot.addWidget(window)
        window.show()
        # active, for a field to take the focus and lose it
        with self._qtbot.waitActive(window):
            window.activateWindow()
        yield

    async def type(self, view: View, text: str) -> None:
        line_edit = _line_edit(view)
        line_edit.setFocus()
        self._qtbot.waitUntil(line_edit.hasFocus)
        line_edit.selectAll()
        self._qtbot.keyClicks(line_edit, text)

    async def leave(self, view: View) -> None:
        line_edit = _line_edit(view)
        self._qtbot.keyClick(line_edit, Qt.Key.Key_Tab)
        assert not line_edit.hasFocus()

    def shown_text(self, view: View) -> str:
        return _line_edit(view).text()


def _line_edit(view: View) -> QLineEdit:
    """Find the line edit that the user types in: the field, or its own (a spin box's, a date's)."""
    field = _widget(view)
    if isinstance(field, QLineEdit):
        return field
    # its own, not one of a popup's, such as a calendar's year
    line_edit = field.findChild(QLineEdit, options=Qt.FindChildOption.FindDirectChildrenOnly)
    assert isinstance(line_edit, QLineEdit)
    return line_edit

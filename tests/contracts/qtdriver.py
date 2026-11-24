"""The Qt driver: keys and clicks on the real widgets, in an active window."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Literal

from qtpy.QtCore import Qt
from qtpy.QtWidgets import QAbstractButton, QLineEdit

from composeui.core.registry import RendererType
from composeui.qtcore.widgets.qrangeslider import QRangeSlider
from composeui.qtcore.widgets.qvalueslider import QValueSlider
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

    async def toggle(self, view: View) -> None:
        button = _button(view)
        button.setFocus()
        self._qtbot.waitUntil(button.hasFocus)
        self._qtbot.keyClick(button, Qt.Key.Key_Space)

    def is_checked(self, view: View) -> bool:
        return _button(view).isChecked()

    async def slide(self, view: View, end: Literal["start", "end"]) -> None:
        slider = _slider(view)
        slider.setFocus()
        self._qtbot.waitUntil(slider.hasFocus)
        self._qtbot.keyClick(slider, Qt.Key.Key_Home if end == "start" else Qt.Key.Key_End)

    def slider_text(self, view: View) -> str:
        return _slider(view).shown_text()


def _line_edit(view: View) -> QLineEdit:
    """Find the line edit that the user types in: the field, or its own (a spin box's, a date's)."""
    field = _widget(view)
    if isinstance(field, QLineEdit):
        return field
    # its own, not one of a popup's, such as a calendar's year
    line_edit = field.findChild(QLineEdit, options=Qt.FindChildOption.FindDirectChildrenOnly)
    assert isinstance(line_edit, QLineEdit)
    return line_edit


def _button(view: View) -> QAbstractButton:
    button = _widget(view)
    assert isinstance(button, QAbstractButton)
    return button


def _slider(view: View) -> QValueSlider | QRangeSlider:
    slider = _widget(view)
    assert isinstance(slider, (QValueSlider, QRangeSlider))
    return slider

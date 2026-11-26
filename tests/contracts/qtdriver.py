"""The Qt driver: keys and clicks on the real widgets, in an active window."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Literal, TypeVar

from qtpy.QtCore import QCoreApplication, QLocale, Qt
from qtpy.QtWidgets import QAbstractButton, QLineEdit, QPlainTextEdit, QWidget

from composeui.core.registry import RendererType
from composeui.qtcore.widgets.qrangeslider import QRangeSlider
from composeui.qtcore.widgets.qvalueslider import QValueSlider
from tests.qtcore.support import _widget

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from pytestqt.qtbot import QtBot

    from composeui.core.view import MainView, View

TWidget = TypeVar("TWidget", bound=QWidget)


class QtDriver:
    def __init__(self, qtbot: QtBot) -> None:
        self._qtbot = qtbot

    @asynccontextmanager
    async def open(self, main_view: MainView) -> AsyncGenerator[None, None]:
        # the same keys on every machine: a decimal field's validator follows the default
        # locale, and rejects the `.` typed in `7.5` under `fr_FR`
        machine = QLocale()
        QLocale.setDefault(QLocale.c())
        try:
            main_view.render(RendererType.QT)
            window = _widget(main_view)
            self._qtbot.addWidget(window)
            window.show()
            # active, for a field to take the focus and lose it
            with self._qtbot.waitActive(window):
                window.activateWindow()
            yield
        finally:
            QLocale.setDefault(machine)

    @asynccontextmanager
    async def by_code(self) -> AsyncGenerator[None, None]:
        yield
        QCoreApplication.processEvents()

    async def type(self, view: View, text: str, *, part: int = 0) -> None:
        box = self._focus(_text_boxes(view)[part])
        box.selectAll()
        for index, line in enumerate(text.split("\n")):
            if index > 0:
                self._qtbot.keyClick(box, Qt.Key.Key_Return)
            self._qtbot.keyClicks(box, line)

    async def leave(self, view: View) -> None:
        box = next(box for box in _text_boxes(view) if box.hasFocus())
        self._qtbot.keyClick(box, Qt.Key.Key_Tab)  # a text area's too: it goes to the next field
        assert not box.hasFocus()

    def shown_text(self, view: View, *, part: int = 0) -> str:
        box = _text_boxes(view)[part]
        return box.toPlainText() if isinstance(box, QPlainTextEdit) else box.text()

    def edits(self, text: str) -> list[str]:
        return [text[:end] for end in range(1, len(text) + 1)]  # a report per key

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

    def _focus(self, widget: TWidget) -> TWidget:
        widget.setFocus()
        self._qtbot.waitUntil(widget.hasFocus)
        return widget


def _text_boxes(view: View) -> list[QLineEdit | QPlainTextEdit]:
    """Find the boxes that the user types in, in order.

    The field, or its own: a spin box's, a date's, a date range's two.
    """
    boxes = _boxes_in(_widget(view))
    assert boxes
    return boxes


def _boxes_in(widget: QWidget) -> list[QLineEdit | QPlainTextEdit]:
    if isinstance(widget, (QLineEdit, QPlainTextEdit)):
        return [widget]
    children = widget.findChildren(QWidget, options=Qt.FindChildOption.FindDirectChildrenOnly)
    # not a popup's, such as a calendar's year
    return [box for child in children if not child.isWindow() for box in _boxes_in(child)]


def _button(view: View) -> QAbstractButton:
    button = _widget(view)
    assert isinstance(button, QAbstractButton)
    return button


def _slider(view: View) -> QValueSlider | QRangeSlider:
    slider = _widget(view)
    assert isinstance(slider, (QValueSlider, QRangeSlider))
    return slider

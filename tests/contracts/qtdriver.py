"""The Qt driver: keys and clicks on the real widgets, in an active window."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Literal, Optional, TypeVar

from qtpy.QtCore import QCoreApplication, QLocale, QPoint, Qt
from qtpy.QtWidgets import (
    QAbstractButton,
    QComboBox,
    QLineEdit,
    QPlainTextEdit,
    QRadioButton,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from composeui.core.registry import RendererType
from composeui.qtcore.widgets.qchecklist import QCheckList, QMultiComboBox
from composeui.qtcore.widgets.qconsole import QSearchField
from composeui.qtcore.widgets.qrangeslider import QRangeSlider
from composeui.qtcore.widgets.qtexteditor import QTextEditor
from composeui.qtcore.widgets.qvalueslider import QValueSlider
from tests.qtcore.support import _widget

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable

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

    async def wait_until(self, condition: Callable[[], bool]) -> None:
        self._qtbot.waitUntil(condition, timeout=10_000)

    async def type(self, view: View, text: str, *, part: int = 0) -> None:
        box = self._focus(_text_boxes(view)[part])
        box.selectAll()
        for index, line in enumerate(text.split("\n")):
            if index > 0:
                self._qtbot.keyClick(box, Qt.Key.Key_Return)
            self._qtbot.keyClicks(box, line)

    async def leave(self, view: View) -> None:
        box = next(box for box in _text_boxes(view) if box.hasFocus())
        # a text area's Tab too goes to the next field; a text editor's indents, Escape leaves
        # a read-only one's Tab leaves, as it types nothing
        is_indenting = isinstance(box, QTextEditor) and not box.isReadOnly()
        key = Qt.Key.Key_Escape if is_indenting else Qt.Key.Key_Tab
        self._qtbot.keyClick(box, key)
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

    async def pick(self, view: View, label: str) -> None:
        field = _widget(view)
        if isinstance(field, QComboBox):
            # by the arrow keys from the choice shown, its list closed
            moves = field.findText(label) - field.currentIndex()
            key = Qt.Key.Key_Down if moves > 0 else Qt.Key.Key_Up
            box = self._focus(field)
            for _ in range(abs(moves)):
                self._qtbot.keyClick(box, key)
        else:
            (button,) = [b for b in field.findChildren(QRadioButton) if b.text() == label]
            self._qtbot.mouseClick(button, Qt.MouseButton.LeftButton)

    def chosen(self, view: View) -> Optional[str]:
        field = _widget(view)
        if isinstance(field, QComboBox):
            return None if field.currentIndex() == -1 else field.currentText()
        checked = [b.text() for b in field.findChildren(QRadioButton) if b.isChecked()]
        assert len(checked) <= 1
        return checked[0] if checked else None

    async def search(self, view: View, text: str) -> None:
        search_field = self._focus(_check_list(view).search_field)
        search_field.selectAll()
        if text == "":
            self._qtbot.keyClick(search_field, Qt.Key.Key_Backspace)
        self._qtbot.keyClicks(search_field, text)

    async def check(self, view: View, label: str) -> None:
        field = _widget(view)
        menu = field.menu() if isinstance(field, QMultiComboBox) else None
        if menu is not None:
            menu.popup(field.mapToGlobal(field.rect().bottomLeft()))  # as a click does
            self._qtbot.waitUntil(menu.isVisible)
        (box,) = [box for box in _check_list(view).boxes if box.text() == label]
        # on its row, past its text, which checks it too
        self._qtbot.mouseClick(
            box, Qt.MouseButton.LeftButton, pos=QPoint(box.width() - 4, box.height() // 2)
        )
        if menu is not None:
            menu.close()

    def checks(self, view: View) -> list[tuple[str, bool]]:
        return [(box.text(), box.isChecked()) for box in _check_list(view).boxes]

    def check_all_state(self, view: View) -> Optional[bool]:
        return _CHECK_STATES[_check_list(view).check_all.checkState()]

    async def select_node(self, view: View, labels: tuple[str, ...]) -> None:
        tree = _tree(view)
        center = tree.visualItemRect(_tree_item(tree, labels)).center()
        self._qtbot.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=center)

    async def toggle_node(self, view: View, labels: tuple[str, ...]) -> None:
        tree = _tree(view)
        rect = tree.visualItemRect(_tree_item(tree, labels))
        # its arrow, in the indentation before it
        arrow = QPoint(rect.left() - tree.indentation() // 2, rect.center().y())
        self._qtbot.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=arrow)

    def selected_node(self, view: View) -> Optional[tuple[str, ...]]:
        selected = [_labels(item) for item in _tree(view).selectedItems()]
        assert len(selected) <= 1
        return selected[0] if selected else None

    def expanded_nodes(self, view: View) -> list[tuple[str, ...]]:
        return [_labels(item) for item in _tree_items(_tree(view)) if item.isExpanded()]

    def _focus(self, widget: TWidget) -> TWidget:
        widget.setFocus()
        self._qtbot.waitUntil(widget.hasFocus)
        return widget


def _text_boxes(view: View) -> list[QLineEdit | QPlainTextEdit]:
    """Find the boxes that the user types in, in order.

    The field, or its own: a spin box's, a date's, a date range's two; not a search's.
    """
    boxes = _boxes_in(_widget(view))
    assert boxes
    return boxes


def _boxes_in(widget: QWidget) -> list[QLineEdit | QPlainTextEdit]:
    if isinstance(widget, QSearchField):
        return []
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


_CHECK_STATES = {
    Qt.CheckState.Checked: True,
    Qt.CheckState.Unchecked: False,
    Qt.CheckState.PartiallyChecked: None,
}


def _check_list(view: View) -> QCheckList:
    """Find the list of `view`'s boxes: the field, or a drop-down list's."""
    field = _widget(view)
    if isinstance(field, QMultiComboBox):
        return field.check_list
    assert isinstance(field, QCheckList)
    return field


def _tree(view: View) -> QTreeWidget:
    tree = _widget(view)
    assert isinstance(tree, QTreeWidget)
    return tree


def _tree_items(tree: QTreeWidget) -> list[QTreeWidgetItem]:
    """Get the tree's items, depth first."""
    items: list[QTreeWidgetItem] = []

    def add(item: Optional[QTreeWidgetItem]) -> None:
        assert item is not None
        items.append(item)
        for index in range(item.childCount()):
            add(item.child(index))

    for index in range(tree.topLevelItemCount()):
        add(tree.topLevelItem(index))
    return items


def _tree_item(tree: QTreeWidget, labels: tuple[str, ...]) -> QTreeWidgetItem:
    (item,) = [item for item in _tree_items(tree) if _labels(item) == labels]
    return item


def _labels(item: QTreeWidgetItem) -> tuple[str, ...]:
    """Get the labels down to `item`, from its top-level item."""
    parent: Optional[QTreeWidgetItem] = item.parent()
    return (*(() if parent is None else _labels(parent)), item.text(0))

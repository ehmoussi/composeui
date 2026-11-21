"""Helpers shared by the Qt tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

from qtpy.QtCore import QEvent, QPoint, QPointF, Qt
from qtpy.QtGui import (
    QMouseEvent,
)
from qtpy.QtWidgets import (
    QAbstractButton,
    QApplication,
    QMainWindow,
    QMessageBox,
    QWidget,
)

from composeui.core.application import _add_reference_to_signals
from composeui.core.registry import RendererType
from composeui.core.renderer import RendererContainer
from composeui.qtcore.qtrenderer import QtWidgetRenderer
from composeui.qtcore.widgets.qfiltertable import QFilterTable
from tests.dialogs import DialogsMainView
from tests.latepages import LatePagesMainView

if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot

    from composeui.core.view import View
    from composeui.qtcore.widgets.qtexttable import QTextTableView


def _field_widget(view: View) -> QWidget:
    renderer = view.renderer
    assert isinstance(renderer, RendererContainer)
    field_renderer = renderer.get_renderer("field")
    assert isinstance(field_renderer, QtWidgetRenderer)
    widget = field_renderer.qt_object
    assert isinstance(widget, QWidget)
    return widget


def _widget(view: View) -> QWidget:
    assert isinstance(view.renderer, QtWidgetRenderer)
    widget = view.renderer.qt_object
    assert isinstance(widget, QWidget)
    return widget


def _table(view: View) -> QTextTableView:
    box = _widget(view)
    assert isinstance(box, QFilterTable)
    return box.table


def _late_pages_window(qtbot: QtBot) -> tuple[LatePagesMainView, QMainWindow]:
    view = LatePagesMainView()
    view.render(RendererType.QT)
    _add_reference_to_signals(view, None)  # as the app does: the tables find the jobs
    window = _widget(view)
    assert isinstance(window, QMainWindow)
    qtbot.addWidget(window)
    window.show()
    return view, window


def _mouse(widget: QWidget, kind: QEvent.Type, position: QPoint, *, is_held: bool) -> None:
    """Send `widget` a mouse event of the left button at `position`, held after it or not."""
    left, no_button = Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton
    event = QMouseEvent(
        kind,
        QPointF(position),
        QPointF(widget.mapToGlobal(position)),
        no_button if kind == QEvent.Type.MouseMove else left,
        left if is_held else no_button,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(widget, event)


def _press(widget: QWidget, position: QPoint) -> None:
    _mouse(widget, QEvent.Type.MouseButtonPress, position, is_held=True)


def _move_pressed(widget: QWidget, position: QPoint) -> None:
    """Move the mouse to `position` in `widget`, its left button held: QTest's moves hold none."""
    _mouse(widget, QEvent.Type.MouseMove, position, is_held=True)


def _release(widget: QWidget, position: QPoint) -> None:
    _mouse(widget, QEvent.Type.MouseButtonRelease, position, is_held=False)


def _dialog_window(qtbot: QtBot) -> tuple[DialogsMainView, QMainWindow, QMessageBox]:
    view = DialogsMainView()
    view.render(RendererType.QT)
    assert isinstance(view.renderer, QtWidgetRenderer)
    window = view.renderer.qt_object
    assert isinstance(window, QMainWindow)
    qtbot.addWidget(window)
    window.show()
    box = _qt_widget(view.confirm_clear)  # not the main view's own question
    assert isinstance(box, QMessageBox)
    return view, window, box


def _shown_buttons(box: QMessageBox) -> dict[str, QAbstractButton]:
    return {button.text(): button for button in box.buttons() if button.isVisibleTo(box)}


def _qt_widget(view: View) -> QWidget:
    assert isinstance(view.renderer, QtWidgetRenderer)
    widget = view.renderer.qt_object
    assert isinstance(widget, QWidget)
    return widget

"""Qt action, menu, separator and toolbar renderers."""

from __future__ import annotations

from typing import Any

from qtpy.QtGui import QAction, QIcon, QKeySequence
from qtpy.QtWidgets import QMenu, QToolBar, QWidget
from typing_extensions import override

from composeui.core.view import ActionView, Menu, PickFileAction, SeparatorAction, ToolBar
from composeui.qtcore.qtrenderer import QtWidgetRenderer
from composeui.qtcore.widgets.qplaintext import plain_tool_tip


class QtActionRenderer(QtWidgetRenderer[ActionView, QAction]):
    def __init__(self, view: ActionView) -> None:
        super().__init__(view)
        self._parent_rendered_object: QWidget | None = None
        self._refresh_dispatcher.update(
            {
                "text": self._refresh_text,
                "icon": self._refresh_icon,
                "data": self._refresh_data,
                "shortcut": self._refresh_shortcut,
                "is_checkable": self._refresh_is_checkable,
                "is_checked": self._refresh_is_checked,
            }
        )
        if isinstance(view, PickFileAction):
            # read by the picker each time it opens
            self._refresh_dispatcher["extensions"] = lambda _view, _action, _value: None

    def set_parent_rendered_object(self, parent: QWidget) -> None:
        self._parent_rendered_object = parent

    @override
    def render(self) -> None:
        if self._rendered_object is None and self._parent_rendered_object:
            self._rendered_object = QAction(self._parent_rendered_object)
            self._relay(self._view.triggered, self._rendered_object.triggered)
            self.refresh()

    @override
    def refresh_attribute(self, attr_name: str, value: Any) -> None:
        # no `QAction` without a parent to show it, e.g. the entry of a page outside a
        # router: nothing to update, and `render` shows the view as it is then
        if self._rendered_object is not None:
            super().refresh_attribute(attr_name, value)

    @staticmethod
    def _refresh_text(_view: ActionView, rendered_object: QAction, text: str) -> None:
        rendered_object.setText(text)
        rendered_object.setToolTip("")  # back to Qt's own, the text without its "&"
        rendered_object.setToolTip(plain_tool_tip(rendered_object.toolTip()))

    @staticmethod
    def _refresh_icon(_view: ActionView, rendered_object: QAction, icon: str | None) -> None:
        if icon is None:
            rendered_object.setIcon(QIcon())
        else:
            rendered_object.setIcon(QIcon(icon))

    @staticmethod
    def _refresh_data(_view: ActionView, rendered_object: QAction, data: Any) -> None:
        rendered_object.setData(data)

    @staticmethod
    def _refresh_shortcut(
        _view: ActionView, rendered_object: QAction, shortcut: str | None
    ) -> None:
        if shortcut is None:
            rendered_object.setShortcut(QKeySequence())
        else:
            rendered_object.setShortcut(QKeySequence(shortcut))

    @staticmethod
    def _refresh_is_checkable(
        _view: ActionView, rendered_object: QAction, is_checkable: bool
    ) -> None:
        rendered_object.setCheckable(is_checkable)

    @staticmethod
    def _refresh_is_checked(_view: ActionView, rendered_object: QAction, is_checked: bool) -> None:
        rendered_object.setChecked(is_checked)


class QtSeparatorRenderer(QtWidgetRenderer[SeparatorAction, QAction]):
    def __init__(self, view: SeparatorAction) -> None:
        super().__init__(view)
        self._parent_rendered_object: QWidget | None = None

    def set_parent_rendered_object(self, parent: QWidget) -> None:
        self._parent_rendered_object = parent

    @override
    def render(self) -> None:
        if self._rendered_object is None and self._parent_rendered_object is not None:
            self._rendered_object = QAction(self._parent_rendered_object)
            self._rendered_object.setSeparator(True)
            self.refresh()


class QtMenuRenderer(QtWidgetRenderer[Menu, QMenu]):
    def __init__(self, view: Menu) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update({"title": self._refresh_title})
        self._parent_rendered_object: QWidget | None = None

    def set_parent_rendered_object(self, parent: QWidget) -> None:
        self._parent_rendered_object = parent

    @override
    def render(self) -> None:
        if self._rendered_object is None and self._parent_rendered_object is not None:
            self._rendered_object = QMenu(self._parent_rendered_object)
            for child_view in self._view.children_views:
                if isinstance(child_view, (ActionView, SeparatorAction)) and isinstance(
                    child_view.renderer, (QtActionRenderer, QtSeparatorRenderer)
                ):
                    child_view.renderer.set_parent_rendered_object(self._rendered_object)
                    child_view.renderer.render()
                    action = child_view.renderer.qt_object
                    assert action is not None
                    self._rendered_object.addAction(action)
            self.refresh()

    @staticmethod
    def _refresh_title(_view: Menu, rendered_object: QMenu, title: str) -> None:
        rendered_object.setTitle(title)


class QtToolBarRenderer(QtWidgetRenderer[ToolBar, QToolBar]):
    """A toolbar of its actions, docked at the top by the main window."""

    def __init__(self, view: ToolBar) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update({"title": self._refresh_title})

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QToolBar()
            self._rendered_object.setMovable(False)
            self._rendered_object.toggleViewAction().setVisible(False)  # no way to close it
            for child_view in self._view.children_views:
                if isinstance(child_view.renderer, (QtActionRenderer, QtSeparatorRenderer)):
                    child_view.renderer.set_parent_rendered_object(self._rendered_object)
                    child_view.renderer.render()
                    action = child_view.renderer.qt_object
                    assert action is not None
                    self._rendered_object.addAction(action)
            self.refresh()

    @staticmethod
    def _refresh_title(_view: ToolBar, rendered_object: QToolBar, title: str) -> None:
        rendered_object.setWindowTitle(title)

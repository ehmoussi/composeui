r"""Button with a menu of checkable actions."""

from qtpy.QtCore import Signal  # type: ignore[attr-defined]
from qtpy.QtCore import Slot  # type: ignore[attr-defined]
from qtpy.QtGui import QMouseEvent
from qtpy.QtWidgets import QAction, QMenu, QPushButton

from typing import Any, Sequence, Tuple


class _Menu(QMenu):
    r"""Menu which doesn't close after the click on an action."""

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        action = self.activeAction()
        # activeAction -> QAction but it can be None the stubs are wrong
        # TODO: write an issue on github
        if action is not None and action.isEnabled():  # type: ignore[redundant-expr]
            action.setEnabled(False)
            super().mouseReleaseEvent(event)
            action.setEnabled(True)
            action.trigger()


class CheckableMenuButton(QPushButton):
    r"""Button with a checkable menu."""

    selection_changed = Signal()

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._menu = _Menu()
        self.setMenu(self._menu)
        self._all_action = self._add_action("All")
        self._menu.addSeparator()
        self._all_action.toggled.connect(self._check_all_actions)
        self._all_action.setChecked(True)

    @property
    def checked_indices(self) -> Tuple[int, ...]:
        r"""Get the checked indices."""
        return tuple(
            index
            for index, action in enumerate(self._menu.actions()[2:])
            if action.isChecked()
        )

    def set_items(self, items: Sequence[str]) -> None:
        r"""Set the items"""
        all_items = ("All", "", *items)
        actions = self._menu.actions()
        nb_actions = len(actions)
        nb_items = len(all_items)
        if nb_actions > nb_items:
            for index in range(nb_actions - 1, nb_items - 1, -1):
                self._menu.removeAction(actions[index])
        for index, item in enumerate(all_items[:nb_actions]):
            actions[index].setText(item)
        for item in all_items[nb_actions:]:
            self._add_action(item)

    @Slot(bool)
    def _check_all_actions(self, is_checked: bool) -> None:
        r"""Check/Uncheck all the actions according to the status of the 'All' action."""
        for action in self._menu.actions()[2:]:
            self._set_checked_without_signals(action, is_checked)
        self.selection_changed.emit()

    @Slot()
    def _check_all_action(self) -> None:
        r"""Check/Uncheck the 'All' action acording to the status of the other actions."""
        self._set_checked_without_signals(
            self._all_action, all(action.isChecked() for action in self._menu.actions()[2:])
        )

    def _set_checked_without_signals(self, action: QAction, is_checked: bool) -> None:
        r"""Check/Uncheck the given action without triggering the signals."""
        action.blockSignals(True)
        action.setChecked(is_checked)
        action.blockSignals(False)

    def _add_action(self, text: str) -> QAction:
        r"""Add an a checkable action to the menu and assign its signals."""
        action = QAction(self._menu)
        action.setText(text)
        action.setCheckable(True)
        if hasattr(self, "_all_action"):
            action.setChecked(self._all_action.isChecked())
            action.toggled.connect(self.selection_changed)
            action.toggled.connect(self._check_all_action)
        self._menu.addAction(action)
        return action

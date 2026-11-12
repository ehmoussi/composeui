"""A list of check boxes for a choice of several values: a search, a check-all box, the list."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from qtpy.QtCore import QSignalBlocker, Qt, Signal, Slot
from qtpy.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFrame,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

if TYPE_CHECKING:
    from qtpy.QtCore import QPoint
    from qtpy.QtGui import QMouseEvent

    from composeui.core.view import ChoicesShown

#: the rows a check list shows before it scrolls
_MAX_ROWS = 10


class _RowCheckBox(QCheckBox):
    """A choice's check box, which a click anywhere on its row toggles, as a list's row."""

    def hitButton(self, pos: QPoint) -> bool:  # noqa: N802
        return self.rect().contains(pos)


class QCheckList(QWidget):
    """A list of check boxes, with a search field and a check-all box above it.

    Each choice is a `QCheckBox`, which a click on its text toggles too. One group reports
    the clicks of them all, as a long list would take a connection per box otherwise. Its
    signals report only what the user does: `toggled` a choice's key and its new state,
    `all_clicked` the check-all box's new state, `searched` the search's text.
    """

    toggled = Signal(str, bool)
    all_clicked = Signal(bool)
    searched = Signal(str)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.search_field = QLineEdit()
        self.search_field.setClearButtonEnabled(True)
        self.check_all = QCheckBox()
        self._group = QButtonGroup(self)
        self._group.setExclusive(False)
        self._rows_layout = QVBoxLayout()
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        rows = QWidget()
        rows.setLayout(self._rows_layout)
        self._scroll = QScrollArea()
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setWidget(rows)
        # the background of what holds it, e.g. a menu's
        self._scroll.viewport().setAutoFillBackground(False)
        rows.setAutoFillBackground(False)
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.search_field)
        layout.addWidget(self.check_all)
        layout.addWidget(self._scroll)
        self.setLayout(layout)
        self._rows: list[tuple[str, str]] = []
        #: the box of each choice shown, in order
        self.boxes: list[QCheckBox] = []
        self._group.idClicked.connect(self._emit_toggled)
        self.check_all.clicked.connect(self.all_clicked)
        self.search_field.textEdited.connect(self.searched)

    def show_choices(self, shown: ChoicesShown) -> None:
        """Show the choices that the search shows, and which are checked."""
        # the labels too: an int's key is its position, which new values keep
        rows = [(key, label) for key, label, _is_checked in shown.options]
        if rows != self._rows:
            self._rows = rows
            self._build_boxes()
        for box, (_key, _label, is_checked) in zip(self.boxes, shown.options):
            with QSignalBlocker(box):
                box.setChecked(is_checked)
        self.set_all_checked(shown.all_checked)

    def _build_boxes(self) -> None:
        """Make a box per row, the old ones gone."""
        for box in self.boxes:
            self._group.removeButton(box)
            self._rows_layout.removeWidget(box)
            box.deleteLater()
        self.boxes = []
        for index, (_key, label) in enumerate(self._rows):
            box = _RowCheckBox(label)
            self._group.addButton(box, index)
            self._rows_layout.addWidget(box)
            self.boxes.append(box)
        # as high as its rows, up to `_MAX_ROWS` of them, then it scrolls
        spacing = self._rows_layout.spacing()
        heights = [box.sizeHint().height() + spacing for box in self.boxes[:_MAX_ROWS]]
        self._scroll.setFixedHeight(max(sum(heights) - spacing, 0))

    def set_all_checked(self, is_checked: Optional[bool]) -> None:
        """Show the check-all box checked, unchecked, or partly (None)."""
        state = {
            True: Qt.CheckState.Checked,
            False: Qt.CheckState.Unchecked,
            None: Qt.CheckState.PartiallyChecked,
        }[is_checked]
        with QSignalBlocker(self.check_all):
            # a click then goes from partly checked to checked, never back to partly: a
            # partly checked box's click checks them all
            self.check_all.setTristate(is_checked is None)
            self.check_all.setCheckState(state)

    def set_search(self, text: str) -> None:
        if self.search_field.text() != text:
            self.search_field.setText(text)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        # kept here: in a menu, a click that reaches the menu picks its entry, closing it
        event.accept()

    @Slot(int)
    def _emit_toggled(self, index: int) -> None:
        self.toggled.emit(self._rows[index][0], self.boxes[index].isChecked())


class QMultiComboBox(QPushButton):
    """A drop-down list of check boxes: a button showing the choice, its menu the list.

    The menu stays open while the user checks the choices, as they are in a widget of
    its own.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.check_list = QCheckList()
        self.check_list.setContentsMargins(6, 6, 6, 6)
        self._menu = menu = QMenu(self)
        action = QWidgetAction(menu)
        action.setDefaultWidget(self.check_list)
        menu.addAction(action)
        self.setMenu(menu)
        menu.aboutToShow.connect(self._fit_menu)

    @Slot()
    def _fit_menu(self) -> None:
        """Open the menu at least as wide as the button, as a combobox's list."""
        self._menu.setMinimumWidth(self.width())

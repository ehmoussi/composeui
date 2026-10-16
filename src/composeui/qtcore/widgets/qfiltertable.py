from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from qtpy.QtCore import QMargins, QPoint, QRect, QSize, Qt, Signal
from qtpy.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetItem,
)

from composeui.qtcore.widgets.qtexttable import QTextTableView

if TYPE_CHECKING:
    from qtpy.QtGui import QKeyEvent
    from qtpy.QtWidgets import QLayoutItem

#: a chip's remove button: a multiplication sign, as a close button often is
REMOVE = "\u00d7"
#: the value field's style while what it holds can't filter, as a form's invalid field
_INVALID_STYLE = "QLineEdit { border: 1px solid red; }"


class QFlowLayout(QLayout):
    """Lays its widgets out in a row, wrapping onto the next when the row is full.

    Qt has none built in: the Qt documentation's Flow Layout example.
    """

    def __init__(self, parent: QWidget | None = None, spacing: int = 4) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._spacing = spacing
        self.setContentsMargins(QMargins(0, 0, 0, 0))

    def addItem(self, item: QLayoutItem) -> None:  # noqa: N802
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def insert_widget(self, index: int, widget: QWidget) -> None:
        self.addChildWidget(widget)
        self._items.insert(index, QWidgetItem(widget))
        self.invalidate()

    def itemAt(self, index: int) -> QLayoutItem | None:  # noqa: N802
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> QLayoutItem | None:  # noqa: N802
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self) -> Qt.Orientation:  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._lay_out(QRect(0, 0, width, 0), move=False)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._lay_out(rect, move=True)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(), margins.top() + margins.bottom())

    def _lay_out(self, rect: QRect, *, move: bool) -> int:
        """Place the items in `rect`'s width (if `move`); return the height they take."""
        x, y, line_height = rect.x(), rect.y(), 0
        for item in self._items:
            widget = item.widget()
            if widget is not None and not widget.isVisible() and move:
                continue
            hint = item.sizeHint()
            if x + hint.width() > rect.right() + 1 and line_height > 0:
                x, y, line_height = rect.x(), y + line_height + self._spacing, 0
            if move:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._spacing
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y()


class _ValueEdit(QLineEdit):
    """The filter editor's value field: Escape closes the editor."""

    escaped = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.escaped.emit()
            return
        super().keyPressEvent(event)


class QFilterChip(QWidget):
    """A filter, as its column's header then its text, opening it, and a button removing it."""

    def __init__(self, text: str, remove_text: str) -> None:
        super().__init__()
        self.open_button = QToolButton()
        self.open_button.setText(text)
        self.open_button.setAutoRaise(True)
        self.remove_button = QToolButton()
        self.remove_button.setText(REMOVE)
        self.remove_button.setAutoRaise(True)
        self.remove_button.setToolTip(remove_text)
        self.remove_button.setAccessibleName(remove_text)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.open_button)
        layout.addWidget(self.remove_button)
        self.setObjectName("chip")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setStyleSheet("#chip { border: 1px solid palette(mid); border-radius: 10px; }")


class QTableFilterBar(QWidget):
    """A table's filter bar: a search, the filters as chips and the count of rows shown.

    "+ Filter" opens an editor in the bar, of a column, a value and an Add button: Enter
    or Add adds the filter, unless `check` says why its value can't filter, marking the
    value field invalid; Escape closes it. Clicking a chip opens the editor on its
    filter, its remove button removes it. The signals emit only for the user: `search_edited` the
    text typed, `filter_added` a column and its text, `filter_removed` a column, and
    `filters_cleared`.
    """

    search_edited = Signal(str)
    filter_added = Signal(int, str)
    filter_removed = Signal(int)
    filters_cleared = Signal()

    def __init__(self) -> None:
        super().__init__()
        #: why a column's text can't filter it, or None if it can
        self.check: Callable[[int, str], str | None] = lambda _column, _text: None
        #: a hint at what filters a column
        self.placeholder: Callable[[int], str] = lambda _column: ""
        self._texts: dict[str, str] = {}
        self._filters: list[tuple[int, str, str]] = []
        self.search = QLineEdit()
        self.search.setClearButtonEnabled(True)
        icon = self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogContentsView)
        self.search.addAction(icon, QLineEdit.ActionPosition.LeadingPosition)
        self.search.textEdited.connect(self.search_edited)
        self.add_filter = QToolButton()
        self.add_filter.clicked.connect(self._open_new_editor)
        self.column = QComboBox()
        self.column.currentIndexChanged.connect(self._show_placeholder)
        self.value = _ValueEdit()
        self.value.returnPressed.connect(self._add)
        self.value.escaped.connect(self.close_editor)
        self.value.textEdited.connect(lambda _text: self._mark_invalid(None))
        self.add = QPushButton()
        self.add.clicked.connect(self._add)
        self.clear = QToolButton()
        self.clear.clicked.connect(self.filters_cleared)
        self.count = QLabel()
        self._chips: list[QFilterChip] = []
        self._layout = QFlowLayout(self)
        for widget in (self.search, self.add_filter, self.column, self.value, self.add):
            self._layout.addWidget(widget)
        self._layout.addWidget(self.clear)
        self._layout.addWidget(self.count)
        self.search.setMinimumWidth(160)
        self.value.setMinimumWidth(120)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self.close_editor()

    def set_texts(self, texts: dict[str, str]) -> None:
        self._texts = texts
        self.search.setPlaceholderText(texts.get("search", ""))
        self.add_filter.setText(texts.get("add_filter", ""))
        self.add.setText(texts.get("add", ""))
        self.clear.setText(texts.get("clear", ""))
        self.column.setAccessibleName(texts.get("column", ""))
        self.value.setAccessibleName(texts.get("value", ""))
        self.set_filters(self._filters)

    def set_columns(self, columns: list[tuple[int, str]]) -> None:
        """Offer `columns`, each its index and its header, in the editor."""
        column = self.column.currentData()
        self.column.blockSignals(True)  # noqa: FBT003
        self.column.clear()
        for index, header in columns:
            self.column.addItem(header, index)
        found = self.column.findData(column)
        self.column.setCurrentIndex(max(found, 0))
        self.column.blockSignals(False)  # noqa: FBT003
        self._show_placeholder()

    def set_search(self, text: str) -> None:
        if self.search.text() != text:
            self.search.setText(text)

    def set_filters(self, filters: list[tuple[int, str, str]]) -> None:
        """Show each filter as a chip: its column, its chip's text and the text typed."""
        self._filters = filters
        for chip in self._chips:
            self._layout.removeWidget(chip)
            chip.deleteLater()
        self._chips = []
        position = self._layout.indexOf(self.clear)
        for column, text, typed in filters:
            header = text[: len(text) - len(typed)].strip()
            chip = QFilterChip(text, self._texts.get("remove", "{header}").format(header=header))
            chip.open_button.clicked.connect(
                lambda _checked=False, c=column, t=typed: self.open_editor(c, t)
            )
            chip.remove_button.clicked.connect(
                lambda _checked=False, c=column: self.filter_removed.emit(c)
            )
            self._layout.insert_widget(position, chip)
            position += 1
            self._chips.append(chip)
        self.clear.setVisible(len(filters) >= 2)  # noqa: PLR2004

    @property
    def chips(self) -> list[QFilterChip]:
        return list(self._chips)

    def set_count(self, text: str) -> None:
        self.count.setText(text)
        self.count.setVisible(text != "")

    def open_editor(self, column: int | None = None, text: str = "") -> None:
        if column is not None:
            self.column.setCurrentIndex(max(self.column.findData(column), 0))
        self.value.setText(text)
        self._mark_invalid(None)
        for widget in (self.column, self.value, self.add):
            widget.setVisible(True)
        self.add_filter.setVisible(False)
        self.value.setFocus()

    def _open_new_editor(self) -> None:
        self.open_editor()

    def close_editor(self) -> None:
        had_focus = self.value.hasFocus()
        for widget in (self.column, self.value, self.add):
            widget.setVisible(False)
        self.add_filter.setVisible(True)
        if had_focus:
            self.add_filter.setFocus()

    def is_editing(self) -> bool:
        return not self.value.isHidden()

    def _add(self) -> None:
        column = self.column.currentData()
        if not isinstance(column, int):
            return
        text = self.value.text()
        reason = self.check(column, text)
        if reason is not None:
            self._mark_invalid(reason)
            return
        self.close_editor()
        self.filter_added.emit(column, text)

    def _mark_invalid(self, reason: str | None) -> None:
        self.value.setStyleSheet(_INVALID_STYLE if reason is not None else "")
        self.value.setToolTip(reason or "")
        self.value.setProperty("invalid", reason is not None)

    def _show_placeholder(self) -> None:
        column = self.column.currentData()
        self.value.setPlaceholderText(self.placeholder(column) if isinstance(column, int) else "")


class QFilterTable(QWidget):
    """A table of text under its filter bar, which shows only while a column filters.

    When the filters hide every row, `empty` says so under the headers.
    """

    def __init__(self) -> None:
        super().__init__()
        self.bar = QTableFilterBar()
        self.table = QTextTableView()
        self.empty = QLabel()
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setVisible(False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.bar)
        layout.addWidget(self.table)
        layout.addWidget(self.empty)
        self.bar.setVisible(False)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

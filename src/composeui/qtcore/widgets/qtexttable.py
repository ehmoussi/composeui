from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional, Union

from qtpy.QtCore import (
    QAbstractTableModel,
    QEvent,
    QItemSelection,
    QItemSelectionModel,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QRect,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from qtpy.QtGui import QColor, QIcon, QMouseEvent, QPainter, QPalette, QPixmap
from qtpy.QtWidgets import (
    QAbstractItemDelegate,
    QAbstractItemView,
    QAbstractScrollArea,
    QApplication,
    QComboBox,
    QHeaderView,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionButton,
    QStyleOptionComboBox,
    QStyleOptionHeader,
    QStyleOptionViewItem,
    QTableView,
    QWidget,
)

from composeui.core.view import (
    CHECKED_TEXTS,
    PLAIN_CELL,
    CellKind,
    CellStyle,
    CellWidget,
    HeaderGroup,
    NodeMark,
    replace_cell,
)
from composeui.qtcore.widgets.qmarkicon import mark_icon
from composeui.qtcore.widgets.qplaintext import plain_tool_tip

if TYPE_CHECKING:
    from qtpy.QtCore import QAbstractItemModel
    from qtpy.QtGui import QKeyEvent

_Index = Union[QModelIndex, QPersistentModelIndex]
#: the roles a cell's `CellStyle` answers
_STYLE_ROLES = (
    Qt.ItemDataRole.BackgroundRole,
    Qt.ItemDataRole.ForegroundRole,
    Qt.ItemDataRole.DecorationRole,
    Qt.ItemDataRole.ToolTipRole,
)
#: the cells `QCellDelegate` draws a widget in, rather than Qt
_DRAWN_KINDS = (CellKind.BUTTON, CellKind.COMBOBOX, CellKind.FILE_PATH)


class QTextTableModel(QAbstractTableModel):
    """A table of text over the view's own lists, without a copy per cell.

    Qt asks only for the cells it draws, so a long table costs no more than a short one.
    The cells of `editable_columns` are editable: an edit changing a cell replaces its
    row (the view's lists aren't changed in place), then `cell_edited` emits it.

    A check box column of `cell_widgets` holds checkable cells without text, toggled when
    editable; a link column's text looks like a link. Neither is typed in, nor is a
    button column; a combobox column is, through `QCellDelegate`'s editor, and a file path
    column is, as a plain one.

    A cell of `styles` has its background, its text black or white on it, and its mark
    before its text, named by its tooltip; a disabled one is never edited. The rows have
    `row_headers`, if any.
    """

    cell_edited = Signal(int, int, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._headers: list[str] = []
        self._rows: list[list[str]] = []
        self.editable_columns: list[int] = []
        self.cell_widgets: dict[int, CellWidget] = {}
        #: a check box drawn before a header, by column
        self.header_icons: dict[int, QIcon] = {}
        #: how the cells look, by row and column
        self.styles: dict[tuple[int, int], CellStyle] = {}
        self._row_headers: list[str] = []
        #: each mark's name, its tooltip
        self.mark_texts: dict[NodeMark, str] = {}

    def kind(self, column: int) -> CellKind | None:
        widget = self.cell_widgets.get(column)
        return None if widget is None else widget.kind

    def set_header_icons(self, icons: dict[int, QIcon]) -> None:
        self.header_icons = icons
        if len(self._headers) > 0:
            self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, len(self._headers) - 1)

    def set_table(
        self,
        headers: list[str],
        rows: list[list[str]],
        styles: dict[tuple[int, int], CellStyle],
        row_headers: list[str],
    ) -> None:
        self.beginResetModel()
        self._headers = headers
        self._rows = rows
        self.styles = styles
        self._row_headers = row_headers
        self.endResetModel()

    def style(self, row: int, column: int) -> CellStyle:
        return self.styles.get((row, column), PLAIN_CELL)

    def rowCount(self, parent: _Index = QModelIndex()) -> int:  # noqa: B008, N802
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: _Index = QModelIndex()) -> int:  # noqa: B008, N802
        return 0 if parent.isValid() else len(self._headers)

    def text(self, row: int, column: int) -> str:
        cells = self._rows[row]
        # a row short of a cell shows it empty
        return cells[column] if column < len(cells) else ""

    def data(self, index: _Index, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        kind = self.kind(index.column())
        if kind is CellKind.LINK and role in (
            Qt.ItemDataRole.FontRole,
            Qt.ItemDataRole.ForegroundRole,
        ):
            return self._link_look(role)
        if role in _STYLE_ROLES:
            return self._style_data(self.style(index.row(), index.column()), role)
        text = self.text(index.row(), index.column())
        if kind is CellKind.CHECK_BOX:
            is_checked = text.casefold() == "true"
            state = Qt.CheckState.Checked if is_checked else Qt.CheckState.Unchecked
            return state if role == Qt.ItemDataRole.CheckStateRole else None
        if role not in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return None
        return text if index.column() < len(self._rows[index.row()]) else None

    def _style_data(self, style: CellStyle, role: int) -> Any:
        """Get a role of the cell's look: its background, text color, mark or tooltip."""
        if role == Qt.ItemDataRole.BackgroundRole:
            return None if style.background is None else QColor(style.background)
        if role == Qt.ItemDataRole.ForegroundRole:
            # grayed by `QCellDelegate` when disabled, unless on a background
            return None if style.text_color is None else QColor(style.text_color)
        if style.mark is None:
            return None
        if role == Qt.ItemDataRole.DecorationRole:
            return mark_icon(style.mark)
        text = self.mark_texts.get(style.mark)
        return None if text is None else plain_tool_tip(text)

    @staticmethod
    def _link_look(role: int) -> Any:
        """Get a link's font, underlined, or its color."""
        if role == Qt.ItemDataRole.ForegroundRole:
            return QApplication.palette().link()
        font = QApplication.font()
        font.setUnderline(True)
        return font

    def flags(self, index: _Index) -> Qt.ItemFlag:
        flags = super().flags(index)
        if (
            not index.isValid()
            or index.column() not in self.editable_columns
            or not self.style(index.row(), index.column()).is_enabled
        ):
            return flags
        kind = self.kind(index.column())
        if kind is CellKind.CHECK_BOX:
            flags |= Qt.ItemFlag.ItemIsUserCheckable
        elif kind in (None, CellKind.COMBOBOX, CellKind.FILE_PATH):
            flags |= Qt.ItemFlag.ItemIsEditable
        return flags

    def setData(  # noqa: N802
        self, index: _Index, value: Any, role: int = Qt.ItemDataRole.EditRole
    ) -> bool:
        if role == Qt.ItemDataRole.CheckStateRole and index.isValid():
            is_checked = value in (Qt.CheckState.Checked, Qt.CheckState.Checked.value)
            value, role = CHECKED_TEXTS[is_checked], Qt.ItemDataRole.EditRole
        if role != Qt.ItemDataRole.EditRole or not index.isValid():
            return False
        row, column, text = index.row(), index.column(), str(value)
        if text == self.text(row, column):
            return False
        self._rows = replace_cell(self._rows, row, column, text)
        self.dataChanged.emit(index, index)
        self.cell_edited.emit(row, column, text)
        return True

    def headerData(  # noqa: N802
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if orientation != Qt.Orientation.Horizontal:
            is_shown = role == Qt.ItemDataRole.DisplayRole and section < len(self._row_headers)
            return self._row_headers[section] if is_shown else None
        if role == Qt.ItemDataRole.DisplayRole:
            return self._headers[section]
        if role == Qt.ItemDataRole.DecorationRole:
            return self.header_icons.get(section)
        return None


class QCellDelegate(QStyledItemDelegate):
    """Draws a button or a combobox cell, and reports a click on a button or a link.

    A button cell shows its text, then the button, a square as tall as the cell unless
    its text is wider; `cell_clicked` emits a click on it, or anywhere on a link cell.
    A file path cell shows its path, then a "…" button, enabled in an editable column,
    whose click `browse_clicked` emits. A combobox cell is a combobox's frame around its
    text: a click on it, or editing it, opens a combobox of its options, the cell taking
    the one picked. A disabled cell is drawn grayed, its button or link not clicked.
    """

    cell_clicked = Signal(int, int)
    browse_clicked = Signal(int, int)
    editor_created = Signal()

    def __init__(self, model: QTextTableModel, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._model = model
        self._pressed: tuple[int, int] | None = None
        self._closed: set[QWidget] = set()

    def _widget(self, index: _Index) -> CellWidget | None:
        return self._model.cell_widgets.get(index.column())

    @staticmethod
    def button_text(widget: CellWidget) -> str:
        """Get the text a button shows: a file path's is "…", its `text` naming it."""
        return "\u2026" if widget.kind is CellKind.FILE_PATH else widget.text

    @staticmethod
    def button_rect(rect: QRect, option: QStyleOptionViewItem, text: str) -> QRect:
        width = max(rect.height(), option.fontMetrics.horizontalAdvance(text) + 12)
        return QRect(rect.right() - width + 1, rect.top(), width, rect.height()).adjusted(
            1, 1, -1, -1
        )

    def _is_disabled(self, index: _Index) -> bool:
        return not self._model.style(index.row(), index.column()).is_enabled

    def initStyleOption(self, option: QStyleOptionViewItem, index: _Index) -> None:  # noqa: N802
        super().initStyleOption(option, index)
        if self._is_disabled(index):
            option.state &= ~QStyle.StateFlag.State_Enabled
        widget = self._widget(index)
        if (
            widget is not None
            and widget.kind is CellKind.LINK
            and option.state & QStyle.StateFlag.State_Selected
        ):
            # the link's color would be lost on the selection's
            option.palette.setBrush(QPalette.ColorRole.Text, option.palette.highlightedText())

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: _Index) -> None:
        widget = self._widget(index)
        if widget is None or widget.kind not in _DRAWN_KINDS:
            super().paint(painter, option, index)
            return
        view = option.widget
        style = view.style() if view is not None else QApplication.style()
        item = QStyleOptionViewItem(option)
        self.initStyleOption(item, index)
        text, item.text = item.text, ""
        # the row's background and selection, then the widget over it
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, item, painter, view)
        is_enabled = bool(item.state & QStyle.StateFlag.State_Enabled)
        if widget.kind is CellKind.COMBOBOX:
            combobox = QStyleOptionComboBox()
            combobox.rect = option.rect.adjusted(2, 2, -2, -2)
            combobox.currentText = text
            combobox.palette = option.palette
            combobox.fontMetrics = option.fontMetrics
            is_editable = index.column() in self._model.editable_columns
            if is_enabled and is_editable:  # a disabled cell isn't
                combobox.state = QStyle.StateFlag.State_Enabled
            style.drawComplexControl(QStyle.ComplexControl.CC_ComboBox, combobox, painter, view)
            style.drawControl(QStyle.ControlElement.CE_ComboBoxLabel, combobox, painter, view)
            return
        button_text = self.button_text(widget)
        button_rect = self.button_rect(option.rect, option, button_text)
        item.text = text
        item.rect = option.rect.adjusted(0, 0, -button_rect.width() - 2, 0)
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, item, painter, view)
        button = QStyleOptionButton()
        button.rect = button_rect
        button.text = button_text
        button.palette = option.palette
        button.fontMetrics = option.fontMetrics
        button.state = QStyle.StateFlag.State_Raised
        if widget.kind is CellKind.FILE_PATH:
            # it edits the cell: enabled only where the cell is
            is_enabled = is_enabled and index.column() in self._model.editable_columns
        if is_enabled:
            button.state |= QStyle.StateFlag.State_Enabled
        style.drawControl(QStyle.ControlElement.CE_PushButton, button, painter, view)

    def editorEvent(  # noqa: N802
        self,
        event: QEvent,
        model: QAbstractItemModel,
        option: QStyleOptionViewItem,
        index: _Index,
    ) -> bool:
        widget = self._widget(index)
        if event.type() == QEvent.Type.MouseButtonPress:
            self._pressed = (index.row(), index.column())
        if (
            widget is not None
            and not self._is_disabled(index)
            and isinstance(event, QMouseEvent)
            and event.type() == QEvent.Type.MouseButtonRelease
            and event.button() == Qt.MouseButton.LeftButton
        ):
            position = event.position().toPoint()
            if widget.kind is CellKind.LINK or (
                widget.kind is CellKind.BUTTON
                and self.button_rect(option.rect, option, widget.text).contains(position)
            ):
                self.cell_clicked.emit(index.row(), index.column())
            elif (
                widget.kind is CellKind.FILE_PATH
                and index.column() in self._model.editable_columns
                and self.button_rect(option.rect, option, "\u2026").contains(position)
            ):
                self.browse_clicked.emit(index.row(), index.column())
                return True
            elif (
                widget.kind is CellKind.COMBOBOX
                and index.column() in self._model.editable_columns
                # not the release of a click that closed the popup
                and self._pressed == (index.row(), index.column())
                and isinstance(view := self.parent(), QAbstractItemView)
            ):
                # like a check box, a combobox answers one click, not Qt's double click
                # (opened once the release is done: the view then resets its state, which
                # must say the editor is open when the edit is answered)
                handled = super().editorEvent(event, model, option, index)
                cell = QPersistentModelIndex(index)
                QTimer.singleShot(
                    0, lambda: view.edit(self._model.index(cell.row(), cell.column()))
                )
                return handled
        return super().editorEvent(event, model, option, index)

    def createEditor(  # noqa: N802
        self, parent: QWidget, option: QStyleOptionViewItem, index: _Index
    ) -> QWidget:
        self.editor_created.emit()
        widget = self._widget(index)
        if widget is None or widget.kind is not CellKind.COMBOBOX:
            return super().createEditor(parent, option, index)
        editor = QComboBox(parent)
        text = self._model.text(index.row(), index.column())
        # a text the options lack still shows, picked
        editor.addItems([*widget.options, *([] if text in widget.options else [text])])
        editor.setCurrentText(text)

        def commit() -> None:
            self._closed.add(editor)
            self.commitData.emit(editor)
            self.closeEditor.emit(editor)

        editor.activated.connect(commit)
        editor.destroyed.connect(lambda: self._closed.discard(editor))
        QTimer.singleShot(0, editor.showPopup)
        return editor

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802
        # the focus lost by an editor already committed would commit it again, to a view
        # that no longer has it
        if isinstance(obj, QWidget) and obj in self._closed:
            # Qt sends it on some runs only, as the focus moves: no test can count on it
            return False  # pragma: no cover
        return super().eventFilter(obj, event)

    def setEditorData(self, editor: QWidget, index: _Index) -> None:  # noqa: N802
        if not isinstance(editor, QComboBox):
            super().setEditorData(editor, index)

    def setModelData(  # noqa: N802
        self, editor: QWidget, model: QAbstractItemModel, index: _Index
    ) -> None:
        if isinstance(editor, QComboBox):
            model.setData(index, editor.currentText())
        else:
            super().setModelData(editor, model, index)


class QCheckHeader(QHeaderView):
    """A horizontal header whose check-all columns start with a check box.

    A click on a column's box emits `check_clicked` instead of `sectionClicked`.

    With `groups`, it is twice as tall: a group's text over its columns' headers, and
    the header of a column without a group the whole height. A click on a group does
    nothing.
    """

    check_clicked = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.checkable_columns: list[int] = []
        self._groups: list[HeaderGroup] = []

    def set_groups(self, groups: list[HeaderGroup]) -> None:
        self._groups = groups
        self.updateGeometry()
        self.viewport().update()

    def _group(self, column: int) -> HeaderGroup | None:
        return next((group for group in self._groups if group.covers(column)), None)

    def sizeHint(self) -> QSize:  # noqa: N802
        size = super().sizeHint()
        if len(self._groups) > 0:
            size.setHeight(2 * size.height())
        return size

    def paintSection(self, painter: QPainter, rect: QRect, logicalIndex: int) -> None:  # noqa: N802, N803
        group = self._group(logicalIndex)
        if group is None:
            super().paintSection(painter, rect, logicalIndex)
            return
        half = rect.height() // 2
        # the group over its columns, drawn again with each, then the column's own header
        last = min(group.column + group.column_count, self.count()) - 1
        left = self.sectionViewportPosition(group.column)
        right = self.sectionViewportPosition(last) + self.sectionSize(last)
        option = QStyleOptionHeader()
        self.initStyleOption(option)
        option.rect = QRect(left, rect.top(), right - left, half)
        option.text = group.text
        option.textAlignment = Qt.AlignmentFlag.AlignCenter
        option.position = QStyleOptionHeader.SectionPosition.OnlyOneSection
        painter.save()
        painter.setClipRect(option.rect)
        self.style().drawControl(QStyle.ControlElement.CE_Header, option, painter, self)
        painter.restore()
        super().paintSection(painter, rect.adjusted(0, half, 0, 0), logicalIndex)

    def _is_on_group(self, event: QMouseEvent) -> bool:
        point = event.position().toPoint()
        return (
            self._group(self.logicalIndexAt(point.x())) is not None
            and point.y() < self.height() // 2
        )

    def box_width(self) -> int:
        """Get the width at a section's start a click checks in: its margins and box."""
        margin = self.style().pixelMetric(QStyle.PixelMetric.PM_HeaderMargin, None, self)
        indicator = self.style().pixelMetric(QStyle.PixelMetric.PM_IndicatorWidth, None, self)
        return 2 * margin + indicator

    def _checked_column(self, event: QMouseEvent) -> int | None:
        x = event.position().toPoint().x()
        column = self.logicalIndexAt(x)
        if column not in self.checkable_columns or self._is_on_group(event):
            return None
        return column if x - self.sectionViewportPosition(column) <= self.box_width() else None

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._checked_column(event) is None and not self._is_on_group(event):
            super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        column = self._checked_column(event)
        if self._is_on_group(event):
            return
        if column is None:
            super().mouseReleaseEvent(event)
        elif event.button() == Qt.MouseButton.LeftButton:
            self.check_clicked.emit(column)


class QTextTableView(QTableView):
    """A table of text, with no row numbers, where the user selects rows.

    `set_table` gives the rows how their cells look (see `QTextTableModel`), a cell
    spanning the rows under it by its `row_span`, and the rows' headers, shown on the
    left unless there are none. `set_header_groups` puts headers over the columns'.

    One row at most by default; with `set_multiple_selection`, each click adds or removes
    a row, as Qt's `MultiSelection`. `selected_rows_changed` emits the selected rows'
    indexes, in order, only when the user changes them: setting them or the table from
    code stays silent. The user edits a cell of `set_editable_columns` with a double click
    or F2, and `cell_edited` emits its row, column and new text once the editor has closed.
    Enter emits `activated` with the current cell, as a double click that edits nothing does,
    also on macOS, whose Enter would edit the cell instead.
    `header_clicked` emits the column whose header the user clicked; the header shows the
    order `set_sort_indicator` gives, the table never sorting its rows itself.

    The columns of `set_cell_widgets` show widgets (see `QCellDelegate`): a click or
    Space toggles an editable check box at once, `cell_edited` emitting it; a click on a
    button or a link, or Space on its cell, emits `cell_clicked`. A click on an editable
    file path's button, or Space on its cell, emits `browse_clicked`, and `set_text`
    gives the cell the file picked, as the user's edit. A check-all column's
    header starts with the box `set_checked_columns` shows, whose click emits
    `check_all_clicked`.
    """

    selected_rows_changed = Signal(list)
    cell_edited = Signal(int, int, str)
    header_clicked = Signal(int)
    cell_clicked = Signal(int, int)
    browse_clicked = Signal(int, int)
    check_all_clicked = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self._model = QTextTableModel(self)
        self.setModel(self._model)
        header = QCheckHeader(self)
        self.setHorizontalHeader(header)
        header.check_clicked.connect(self.check_all_clicked)
        delegate = QCellDelegate(self._model, self)
        self.setItemDelegate(delegate)
        delegate.cell_clicked.connect(self.cell_clicked)
        delegate.browse_clicked.connect(self.browse_clicked)
        # the view's state can't say it: Qt resets it after some of the ways to open an editor
        self._has_editor = False
        delegate.editor_created.connect(self._note_editor)
        self._is_setting = False
        self.verticalHeader().setVisible(False)
        # as tall as its rows, not Qt's default height, which leaves an empty block
        self.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustToContents)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        # the columns share the width; light rows instead of a box around each cell
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.horizontalHeader().setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.verticalHeader().setDefaultSectionSize(self.fontMetrics().height() + 10)
        self.setShowGrid(False)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.selectionModel().selectionChanged.connect(self._emit_selected_rows_changed)
        self._edits: list[tuple[int, int, str]] = []
        self._model.cell_edited.connect(self._hold_edit)
        self._sort: tuple[int, bool] | None = None
        self.horizontalHeader().sectionClicked.connect(self._header_clicked)

    def _hold_edit(self, row: int, column: int, text: str) -> None:
        # Qt commits the editor's text before closing it: a callback answering the edit with
        # new rows would reset the model under the open editor, which Qt then commits again
        # ("commitData called with an editor that does not belong to this view")
        if self._has_editor or self.state() is QAbstractItemView.State.EditingState:
            self._edits.append((row, column, text))
        else:  # a check box toggled, no editor open
            self.cell_edited.emit(row, column, text)

    def _note_editor(self) -> None:
        self._has_editor = True

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        index = self.currentIndex()
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and index.isValid():
            # as Qt does on the other platforms: activated, then passed on (e.g. to a dialog)
            self.activated.emit(index)
            event.ignore()
            return
        kind = self._model.kind(index.column()) if index.isValid() else None
        if event.key() == Qt.Key.Key_Space and (
            index.isValid() and self._model.style(index.row(), index.column()).is_enabled
        ):
            if kind in (CellKind.BUTTON, CellKind.LINK):
                self.cell_clicked.emit(index.row(), index.column())
                return
            if kind is CellKind.FILE_PATH and index.column() in self._model.editable_columns:
                self.browse_clicked.emit(index.row(), index.column())
                return
        super().keyPressEvent(event)

    def set_text(self, row: int, column: int, text: str) -> None:
        """Give a cell the text the user picked, emitted by `cell_edited` if it changed."""
        self._model.setData(self._model.index(row, column), text)

    def set_cell_widgets(self, widgets: dict[int, CellWidget]) -> None:
        self._model.cell_widgets = widgets
        header = self.horizontalHeader()
        assert isinstance(header, QCheckHeader)
        header.checkable_columns = [
            column
            for column, widget in widgets.items()
            if widget.kind is CellKind.CHECK_BOX and widget.check_all
        ]
        self.viewport().update()

    def set_checked_columns(self, states: dict[int, tuple[Optional[bool], bool]]) -> None:
        """Show each check-all column's box: checked, unchecked or partly (None), enabled."""
        self._model.set_header_icons(
            {
                column: self._check_icon(is_checked, is_enabled=is_enabled)
                for column, (is_checked, is_enabled) in states.items()
            }
        )

    def _check_icon(self, is_checked: Optional[bool], *, is_enabled: bool) -> QIcon:
        style = self.style()
        width = style.pixelMetric(QStyle.PixelMetric.PM_IndicatorWidth, None, self)
        height = style.pixelMetric(QStyle.PixelMetric.PM_IndicatorHeight, None, self)
        ratio = self.devicePixelRatio()
        pixmap = QPixmap(round(width * ratio), round(height * ratio))
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(Qt.GlobalColor.transparent)
        option = QStyleOptionButton()
        option.rect = QRect(0, 0, width, height)
        option.palette = self.palette()
        states = {
            True: QStyle.StateFlag.State_On,
            False: QStyle.StateFlag.State_Off,
            None: QStyle.StateFlag.State_NoChange,
        }
        option.state = states[is_checked]
        if is_enabled:
            option.state |= QStyle.StateFlag.State_Enabled
        else:
            # Fusion draws the box in the palette's colors, whatever its state
            option.palette.setCurrentColorGroup(QPalette.ColorGroup.Disabled)
        painter = QPainter(pixmap)
        try:
            style.drawPrimitive(QStyle.PrimitiveElement.PE_IndicatorCheckBox, option, painter, self)
        finally:
            painter.end()
        return QIcon(pixmap)

    def closeEditor(  # noqa: N802
        self, editor: QWidget, hint: QAbstractItemDelegate.EndEditHint
    ) -> None:
        if len(self._edits) > 0:
            # the cell to edit next may not stay where it is once the edit is answered
            hint = QAbstractItemDelegate.EndEditHint.NoHint
        super().closeEditor(editor, hint)
        self._has_editor = False
        edits, self._edits = self._edits, []
        for edit in edits:
            self.cell_edited.emit(*edit)

    def set_sort_indicator(self, sort: tuple[int, bool] | None, *, is_shown: bool) -> None:
        """Show the order: by a column, descending or not; None for the rows' own."""
        self._sort = sort
        header = self.horizontalHeader()
        header.setSortIndicatorShown(is_shown and sort is not None)
        header.setSectionsClickable(is_shown)
        if sort is not None:
            column, is_descending = sort
            order = Qt.SortOrder.DescendingOrder if is_descending else Qt.SortOrder.AscendingOrder
            header.setSortIndicator(column, order)

    def _header_clicked(self, column: int) -> None:
        # the header flips its indicator on a click: the order is the view's to say
        self.set_sort_indicator(self._sort, is_shown=self.horizontalHeader().sectionsClickable())
        self.header_clicked.emit(column)

    def set_table(
        self,
        headers: list[str],
        rows: list[list[str]],
        styles: dict[tuple[int, int], CellStyle] | None = None,
        row_headers: list[str] | None = None,
    ) -> None:
        styles, row_headers = styles or {}, row_headers or []
        self._is_setting = True
        try:
            self._model.set_table(headers, rows, styles, row_headers)
            self.clearSpans()
            for (row, column), style in styles.items():
                if style.row_span > 1:
                    self.setSpan(row, column, style.row_span, 1)
        finally:
            self._is_setting = False
        self.verticalHeader().setVisible(len(row_headers) > 0)

    def set_header_groups(self, groups: list[HeaderGroup]) -> None:
        header = self.horizontalHeader()
        assert isinstance(header, QCheckHeader)
        header.set_groups(groups)

    def set_mark_text(self, mark: NodeMark, text: str) -> None:
        """Name `mark` in its cells' tooltips."""
        self._model.mark_texts[mark] = text

    def set_editable_columns(self, columns: list[int]) -> None:
        self._model.editable_columns = columns

    def set_multiple_selection(self, *, is_multiple: bool) -> None:
        self.setSelectionMode(
            QAbstractItemView.SelectionMode.MultiSelection
            if is_multiple
            else QAbstractItemView.SelectionMode.SingleSelection
        )

    def selected_rows(self) -> list[int]:
        return sorted(index.row() for index in self.selectionModel().selectedRows())

    def set_selected_rows(self, rows: list[int]) -> None:
        self._is_setting = True
        try:
            selection = QItemSelection()
            for row in rows:
                index = self._model.index(row, 0)
                selection.select(index, index)
            self.selectionModel().select(
                selection,
                QItemSelectionModel.SelectionFlag.ClearAndSelect
                | QItemSelectionModel.SelectionFlag.Rows,
            )
        finally:
            self._is_setting = False

    def _emit_selected_rows_changed(
        self, _selected: QItemSelection, _deselected: QItemSelection
    ) -> None:
        if not self._is_setting:
            self.selected_rows_changed.emit(self.selected_rows())

"""Qt layout renderers and their shared content and dialog-parent helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypeVar

from qtpy.QtCore import Qt
from qtpy.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStyle,
    QTabWidget,
    QTextBrowser,
    QTreeWidget,
    QVBoxLayout,
    QWidget,
)
from typing_extensions import override

from composeui.core._views.dialogs import dialogs_in
from composeui.core.registry import RendererType
from composeui.core.view import (
    Align,
    DialogView,
    ExpanderView,
    FormView,
    GridView,
    GroupFormView,
    HorizontalView,
    ListView,
    Orientation,
    PageView,
    SplitterView,
    TabPage,
    TabView,
    VerticalView,
    View,
)
from composeui.qtcore._renderers.forms import _widget_of
from composeui.qtcore.qtrenderer import QtWidgetRenderer
from composeui.qtcore.widgets.qcolumnlayout import QColumnLayout
from composeui.qtcore.widgets.qconsole import QConsoleBox
from composeui.qtcore.widgets.qexpander import QExpander
from composeui.qtcore.widgets.qflowlayout import QFlowLayout
from composeui.qtcore.widgets.qpagearea import QPageArea
from composeui.qtcore.widgets.qsourcetable import QDataFilterTable
from composeui.qtcore.widgets.qsplitter import QComposeSplitter

if TYPE_CHECKING:
    from qtpy.QtWidgets import QLayout

    from composeui.core.view import Frame

TLayout = TypeVar("TLayout", bound="HorizontalView | VerticalView | GridView")

#: widgets scrolling within themselves: as tall as the room they're given, rather than
#: their content, so they take a column's spare height, and a row's whole height; a
#: splitter too, its panes as tall as it
_SCROLLING_WIDGETS = (
    QTextBrowser,
    QConsoleBox,
    QScrollArea,
    QTreeWidget,
    QSplitter,
    QDataFilterTable,
)


def _adopt_dialogs(view: View, parent: QWidget) -> None:
    """Make `parent` the parent of the dialogs under `view` with none: they open over its window.

    A dialog with a parent already keeps it: another one would hide it, maybe open.
    """
    for dialog in dialogs_in(view):
        widget = _widget_of(dialog)
        assert widget is not None  # Qt renders every dialog of the core
        if widget.parentWidget() is None:
            _set_dialog_parent(dialog, widget, parent)


def _set_dialog_parent(dialog: View, widget: QWidget, parent: QWidget | None) -> None:
    """Make `parent` the parent of a dialog's window, which then opens over `parent`'s."""
    widget.setParent(parent, widget.windowFlags())
    # `setParent` hides it: a dialog opened before the window was built shows now
    widget.setVisible(dialog.is_visible)


def _add_content_widget(layout: QColumnLayout, view: View) -> None:
    """Add `view`'s widget to a column of content: a window's, a page's, a tab's or a sidebar's.

    A view that grows taller, such as one scrolling within itself or a row or a column
    holding one, takes the column's height to spare (see `QColumnLayout`).
    """
    widget = _widget_of(view)
    if widget is None:
        return
    if isinstance(view, DialogView):
        # a window of its own, over the column's window; a page's built late already has
        # its router's, maybe while open, which another parent would hide
        if widget.parentWidget() is None:
            _set_dialog_parent(view, widget, layout.parentWidget())
    elif isinstance(view, (PageView, FormView)) and not isinstance(view, GroupFormView):
        # a page insets its own views, and a plain form its rows, with its layout's margins
        layout.addWidget(widget)
    else:
        # inset like a plain form's rows
        inset = QVBoxLayout()
        style = widget.style()
        left = style.pixelMetric(QStyle.PixelMetric.PM_LayoutLeftMargin)
        right = style.pixelMetric(QStyle.PixelMetric.PM_LayoutRightMargin)
        inset.setContentsMargins(left, 0, right, 0)
        if isinstance(widget, QPushButton):
            # as wide as its text, like a form's own buttons, not the whole column
            inset.addWidget(widget, alignment=Qt.AlignmentFlag.AlignLeft)
        else:
            inset.addWidget(widget)
        layout.addLayout(inset)


class QtPageRenderer(QtWidgetRenderer[PageView, QPageArea]):
    """A page's views in a column, laid out like the window's own, scrolling if too big."""

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            column = QWidget()
            layout = QColumnLayout(column)
            # the window's layout already insets the page
            layout.setContentsMargins(0, 0, 0, 0)
            for view in self._view.content_views:
                _add_content_widget(layout, view)
            layout.add_spare_space()
            self._rendered_object = QPageArea(column)
            self.refresh()


class _QtLayoutRenderer(QtWidgetRenderer[TLayout, QWidget]):
    def __init__(self, view: TLayout) -> None:
        super().__init__(view)
        if view.frame is not None:
            self._refresh_dispatcher["frame"] = self._refresh_frame

    def _layout_widget(self) -> QWidget:
        return QWidget() if self._view.frame is None else QGroupBox()

    def _set_layout_margins(self, layout: QLayout) -> None:
        # A plain layout needs no inset of its own. In a group box, use the Qt style's inset.
        margin = 0 if self._view.frame is None else -1
        layout.setContentsMargins(margin, margin, margin, margin)

    @staticmethod
    def _refresh_frame(_view: TLayout, widget: QWidget, frame: Frame) -> None:
        assert isinstance(widget, QGroupBox)
        widget.setTitle(frame.title)


class QtHorizontalRenderer(_QtLayoutRenderer[HorizontalView]):
    """Views side by side, each as wide as its share of the row.

    When none has a share (e.g. buttons), each keeps its own width, and the views that
    don't fit the row's width go on the next line.
    """

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = self._layout_widget()
            widgets = [
                (widget, stretch)
                for view, stretch in self._view.stretched_views
                if (widget := _widget_of(view)) is not None
            ]
            if any(stretch > 0 for _, stretch in widgets):
                layout = QHBoxLayout(self._rendered_object)
                self._set_layout_margins(layout)
                # a spacer with no share: it takes the free width only while the views
                # with a share are hidden, ahead of views (e.g. buttons) that would grow
                if self._view.align is Align.END:
                    layout.addStretch(0)
                for widget, stretch in widgets:
                    # at the top: Qt centres a view shorter than the row (e.g. a table
                    # as tall as its rows, beside a taller one) as the window grows; one
                    # scrolling within itself, as tall as the row
                    alignment = (
                        Qt.AlignmentFlag(0)
                        if isinstance(widget, _SCROLLING_WIDGETS)
                        else Qt.AlignmentFlag.AlignTop
                    )
                    layout.addWidget(widget, stretch, alignment)
                if self._view.align is Align.START:
                    layout.addStretch(0)
            else:
                # as wide as all its views on one line: the window opens wide enough for them
                flow = QFlowLayout(
                    self._rendered_object,
                    align_end=self._view.align is Align.END,
                    one_line_hint=True,
                )
                self._set_layout_margins(flow)
                for widget, _ in widgets:
                    flow.addWidget(widget)
            self.refresh()


class QtVerticalRenderer(_QtLayoutRenderer[VerticalView]):
    """Views one above the other, at the top of the column."""

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = self._layout_widget()
            layout = QColumnLayout(self._rendered_object)
            self._set_layout_margins(layout)
            for view in self._view.children_views:
                widget = _widget_of(view)
                if widget is not None:
                    layout.addWidget(widget)
            # height to spare, next to a taller view, goes below the views, not between them
            layout.add_spare_space()
            self.refresh()


class QtSplitterRenderer(QtWidgetRenderer[SplitterView, QComposeSplitter]):
    """A splitter: the panes in a row or a column, a handle between two the user drags."""

    def __init__(self, view: SplitterView) -> None:
        super().__init__(view)
        self._refresh_dispatcher["sizes"] = self._refresh_sizes
        # names a border on the web only
        self._refresh_dispatcher["border_text"] = lambda _view, _splitter, _value: None

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QComposeSplitter(
                Qt.Orientation.Vertical
                if self._view.orientation is Orientation.VERTICAL
                else Qt.Orientation.Horizontal
            )
            # a pane dragged to nothing would be lost to the user
            self._rendered_object.setChildrenCollapsible(False)
            for view in self._view.panes:
                widget = _widget_of(view)
                if widget is not None:
                    self._rendered_object.addWidget(widget)
            self._connect(self._rendered_object.moved_by_user, self._update_sizes)
            self.refresh()

    @staticmethod
    def _refresh_sizes(
        _view: SplitterView, rendered_object: QComposeSplitter, value: list[int]
    ) -> None:
        # in pixels, but Qt shares any width more or less than theirs in their proportions:
        # well over any screen's, the panes' minimum widths don't skew those
        rendered_object.setSizes([size * 10_000 for size in value])

    def _update_sizes(self) -> None:
        assert self._rendered_object is not None
        sizes = self._view.shares_of(self._rendered_object.sizes())
        if sizes == self._view.sizes:  # a click, or a move against a pane's minimum
            return
        with self.stop_refresh():
            self._view.sizes = sizes
        self._view.resized.emit(sizes)


class QtExpanderRenderer(QtWidgetRenderer[ExpanderView, QExpander]):
    """A header button with an arrow, then the views one above the other while expanded."""

    def __init__(self, view: ExpanderView) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {"title": self._refresh_title, "is_expanded": self._refresh_is_expanded}
        )

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QExpander()
            for view in self._view.children_views:
                widget = _widget_of(view)
                if widget is not None:
                    # a button as wide as its text, as in a window's column, not the section
                    alignment = (
                        Qt.AlignmentFlag.AlignLeft
                        if isinstance(widget, QPushButton)
                        else Qt.AlignmentFlag(0)
                    )
                    self._rendered_object.content_layout.addWidget(widget, 0, alignment)
            # first, so the view's callbacks see the new state
            self._connect(
                self._rendered_object.expanded_changed,
                self._update_expanded,
                self._view.toggled.call_callbacks,
            )
            self.refresh()

    @staticmethod
    def _refresh_title(_view: ExpanderView, rendered_object: QExpander, value: str) -> None:
        rendered_object.header.setText(value)

    @staticmethod
    def _refresh_is_expanded(_view: ExpanderView, rendered_object: QExpander, value: bool) -> None:
        rendered_object.set_expanded(value)

    def _update_expanded(self, is_expanded: bool) -> None:
        with self.stop_refresh():
            self._view.is_expanded = is_expanded


class QtListRenderer(QtWidgetRenderer["ListView[Any]", QScrollArea]):
    """The records' views one above the other, added, moved and removed as they change.

    In a scroll area taking the column's spare height (see `QColumnLayout`): the
    window keeps its height however many records there are.
    """

    def __init__(self, view: ListView[Any]) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update({"item_views": self._refresh_item_views})

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QScrollArea()
            self._rendered_object.setWidgetResizable(True)
            self._rendered_object.setFrameShape(QScrollArea.Shape.NoFrame)
            column = QWidget()
            layout = QVBoxLayout(column)
            # the column holding the list already insets it
            layout.setContentsMargins(0, 0, 0, 0)
            # height to spare goes below the views, not between them
            layout.addStretch()
            self._rendered_object.setWidget(column)
            self.refresh()

    @staticmethod
    def _refresh_item_views(
        _view: ListView[Any], rendered_object: QScrollArea, value: list[View]
    ) -> None:
        widgets: list[QWidget] = []
        for item_view in value:
            if item_view.renderer is None:
                item_view.render(RendererType.QT)  # a record's view built since
            widget = _widget_of(item_view)
            if widget is not None:
                widgets.append(widget)
        column = rendered_object.widget()
        layout = None if column is None else column.layout()
        assert isinstance(layout, QVBoxLayout)
        # the views, ahead of the stretch under them
        while layout.count() > 1:
            item = layout.takeAt(0)
            widget = None if item is None else item.widget()
            if widget is not None and widget not in widgets:
                # its record is gone
                widget.setParent(None)
                widget.deleteLater()
        for index, widget in enumerate(widgets):
            layout.insertWidget(index, widget)


def _tab_of(widget: QWidget) -> tuple[QTabWidget, int] | None:
    """Get the tab widget showing `widget` as a tab, and its tab's index; None outside one."""
    parent = widget.parentWidget()
    while parent is not None and not isinstance(parent, QTabWidget):
        parent = parent.parentWidget()
    if parent is None:
        return None
    index = parent.indexOf(widget)
    return None if index < 0 else (parent, index)


class QtTabPageRenderer(QtWidgetRenderer[TabPage, QWidget]):
    """A tab's views in a column; its title, visibility and enabled state are its tab's."""

    def __init__(self, view: TabPage) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "title": self._refresh_title,
                "is_visible": self._refresh_tab_visible,
                "is_enabled": self._refresh_tab_enabled,
            }
        )

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QWidget()
            QVBoxLayout(self._rendered_object).setContentsMargins(0, 0, 0, 0)
            # its dialogs, rendered already, open over the window before its views are built
            _adopt_dialogs(self._view, self._rendered_object)
            self.refresh()

    def build(self) -> None:
        """Build the tab's views, once: the first time the tab is shown."""
        assert self._rendered_object is not None
        layout = self._rendered_object.layout()
        assert isinstance(layout, QVBoxLayout)
        if layout.count() > 0:
            return
        # built apart, then shown with the tab: added to the tab, maybe on screen already,
        # each view would only show at the event loop's next turn
        content = QWidget()
        content_layout = QColumnLayout(content)
        for view in self._view.children_views:
            view.render(RendererType.QT)
            _add_content_widget(content_layout, view)
        # height to spare goes below the views, not between them
        content_layout.add_spare_space()
        layout.addWidget(content)
        content.show()

    @staticmethod
    def _refresh_title(_view: TabPage, rendered_object: QWidget, value: str) -> None:
        tab = _tab_of(rendered_object)
        if tab is not None:
            tab[0].setTabText(tab[1], value)

    @staticmethod
    def _refresh_tab_visible(_view: TabPage, rendered_object: QWidget, value: bool) -> None:
        # not the widget's own: only the current tab's shows
        tab = _tab_of(rendered_object)
        if tab is not None:
            tab[0].setTabVisible(tab[1], value)

    @staticmethod
    def _refresh_tab_enabled(_view: TabPage, rendered_object: QWidget, value: bool) -> None:
        rendered_object.setEnabled(value)
        tab = _tab_of(rendered_object)
        if tab is not None:
            tab[0].setTabEnabled(tab[1], value)


class QtTabsRenderer(QtWidgetRenderer[TabView, QTabWidget]):
    """A tab widget: the tabs in a row, the current one's views under them.

    A tab's views are built the first time it's shown, so many tabs don't slow the start.
    """

    #: read by `TabView`: it renders only the tab shown, and this renderer the others' views
    renders_on_demand = True

    def __init__(self, view: TabView) -> None:
        super().__init__(view)
        self._refresh_dispatcher["current_index"] = self._refresh_current_index

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QTabWidget()
            for tab in self._view.tabs:
                assert isinstance(tab.renderer, QtTabPageRenderer)
                assert tab.renderer.qt_object is not None
                self._rendered_object.addTab(tab.renderer.qt_object, tab.title)
                tab.renderer.refresh()  # its tab's state, now that it has one
            # once the tabs are in: adding the first one makes it current
            self._connect(
                self._rendered_object.currentChanged,
                self._update_current_index,
                self._view.current_changed.call_callbacks,
            )
            self.refresh()

    def _refresh_current_index(
        self, _view: TabView, rendered_object: QTabWidget, value: int
    ) -> None:
        self._build_tab(value)
        rendered_object.setCurrentIndex(value)

    def _update_current_index(self, index: int) -> None:
        self._build_tab(index)
        with self.stop_refresh():
            self._view.current_index = index

    def _build_tab(self, index: int) -> None:
        tabs = self._view.tabs
        if 0 <= index < len(tabs):
            renderer = tabs[index].renderer
            assert isinstance(renderer, QtTabPageRenderer)
            renderer.build()


class QtGridRenderer(_QtLayoutRenderer[GridView]):
    """Views in a grid's cells: equally wide columns, rows as tall as their views."""

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = self._layout_widget()
            layout = QGridLayout(self._rendered_object)
            self._set_layout_margins(layout)
            for view, position in self._view.positioned_views:
                widget = _widget_of(view)
                if widget is not None:
                    # at the top, as in a row; with no share of a row, as wide as its content
                    alignment = Qt.AlignmentFlag.AlignTop
                    if view.default_stretch == 0:
                        alignment |= Qt.AlignmentFlag.AlignLeft
                    layout.addWidget(widget, *position, alignment)
            for column in range(self._view.column_count):
                layout.setColumnStretch(column, 1)
            # height to spare, next to a taller view, goes below the rows, not between them
            layout.setRowStretch(self._view.row_count, 1)
            self.refresh()

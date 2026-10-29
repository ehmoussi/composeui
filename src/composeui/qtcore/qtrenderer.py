from __future__ import annotations

import functools
import sys
import weakref
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Generic, TypeVar

from qtpy.QtCore import QObject, QSignalBlocker, Qt
from qtpy.QtCore import Signal as QtSignal
from qtpy.QtGui import (
    QAction,
    QDoubleValidator,
    QIcon,
    QKeySequence,
    QTextDocument,
)
from qtpy.QtWidgets import (
    QAbstractButton,
    QAbstractSpinBox,
    QApplication,
    QCheckBox,
    QDockWidget,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMenuBar,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QStyle,
    QTabWidget,
    QTextBrowser,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from typing_extensions import Protocol

from composeui.core import chartimage
from composeui.core.registry import RendererType
from composeui.core.renderer import (
    MainRenderer,
    NoRenderedObjectError,
    Renderer,
    RendererContainer,
    ViewLike,
)
from composeui.core.view import (
    ActionView,
    Align,
    ButtonVariant,
    CellKind,
    ChartKind,
    ChartView,
    DialogKind,
    DialogView,
    ExpanderView,
    FormLabelRowView,
    FormRowView,
    FormView,
    GridView,
    GroupFormView,
    HorizontalView,
    ListView,
    LogType,
    MainView,
    Menu,
    MetricView,
    NodeMark,
    OkCancelDialogView,
    Orientation,
    PageView,
    PickFileAction,
    ProgressBarView,
    Router,
    SelectionMode,
    SeparatorAction,
    SidebarView,
    SliderMixin,
    SourceTableByPosition,
    SplitterView,
    StatusBar,
    TabPage,
    TabView,
    ToolBar,
    TreeView,
    VerticalView,
    View,
    date_hint,
    replace_cell,
    walk_tree,
)
from composeui.qtcore.widgets.qchart import QChart
from composeui.qtcore.widgets.qdatefield import QDateField
from composeui.qtcore.widgets.qexpander import QExpander
from composeui.qtcore.widgets.qfilepathfield import QFilePathField
from composeui.qtcore.widgets.qfiltertable import QFilterTable
from composeui.qtcore.widgets.qformdialog import QFormDialog
from composeui.qtcore.widgets.qformlabel import QFormLabel
from composeui.qtcore.widgets.qmarkicon import mark_icon
from composeui.qtcore.widgets.qmetric import QMetric
from composeui.qtcore.widgets.qplaintext import plain_label, plain_tool_tip
from composeui.qtcore.widgets.qradiogroup import QRadioGroup
from composeui.qtcore.widgets.qsidebar import QSidebar
from composeui.qtcore.widgets.qsourcetable import QDataFilterTable
from composeui.qtcore.widgets.qsplitter import QComposeSplitter
from composeui.qtcore.widgets.qvaluecombobox import QValueComboBox
from composeui.qtcore.widgets.qvalueslider import QValueSlider
from composeui.qtcore.widgets.qwindowrelease import release_when_hidden

if TYPE_CHECKING:
    import datetime
    from collections.abc import Callable, Iterable

    from composeui.core.signal import Signal, SignalNoArgs
    from composeui.core.view import (
        CellStyle,
        CellWidget,
        HeaderGroup,
        ReferenceLine,
        Series,
        TreeNode,
        TreePath,
    )

TView = TypeVar("TView", bound=ViewLike)
TWidget = TypeVar("TWidget", bound="QWidget | QAction")


class _MainThreadInvoker(QObject):
    """Bridges a call from any thread onto the thread that owns this `QObject`."""

    _invoke = QtSignal(object)

    def __init__(self) -> None:
        super().__init__()
        self._invoke.connect(self._run, Qt.ConnectionType.QueuedConnection)

    def call(self, callback: Callable[[], None]) -> None:
        self._invoke.emit(callback)

    @staticmethod
    def _run(callback: Callable[[], None]) -> None:
        callback()


class QtWidgetRenderer(Renderer[TView, TWidget]):
    #: a field renderer's style sheet while its form row is invalid (see
    #: `FormRowView.is_invalid`); None for a widget that is never a row's field
    _invalid_style: ClassVar[str | None] = None

    def __init__(self, view: TView) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "is_visible": self._refresh_visible,
                "is_enabled": self._refresh_enabled,
            }
        )
        if self._invalid_style is not None and isinstance(view, FormRowView):
            # only a row has these: the same renderer also draws a standalone field
            self._refresh_dispatcher.update(
                {
                    name: self._invalid_refresher(name)
                    for name in ("log_message", "log_type", "has_form_error")
                }
            )
        self._main_thread_invoker = _MainThreadInvoker()

    def call_on_main_thread(self, callback: Callable[[], None]) -> None:
        self._main_thread_invoker.call(callback)

    @property
    def qt_object(self) -> TWidget | None:
        return self._rendered_object

    def refresh(self) -> None:
        if self._rendered_object is None:
            raise NoRenderedObjectError
        self._rendered_object.blockSignals(True)  # noqa: FBT003
        super().refresh()
        self._rendered_object.blockSignals(False)  # noqa: FBT003

    def refresh_attribute(self, attr_name: str, value: Any) -> None:
        """Show `value`, the new value of `attr_name`, without the widget emitting signals."""
        if self._rendered_object is None:
            raise NoRenderedObjectError
        self._rendered_object.blockSignals(True)  # noqa: FBT003
        super().refresh_attribute(attr_name, value)
        self._rendered_object.blockSignals(False)  # noqa: FBT003

    @staticmethod
    def _refresh_visible(_view: TView, renderer_object: TWidget, value: bool) -> None:
        renderer_object.setVisible(value)

    @staticmethod
    def _refresh_enabled(_view: TView, renderer_object: TWidget, value: bool) -> None:
        renderer_object.setEnabled(value)

    def _invalid_refresher(self, name: str) -> Callable[[TView, TWidget, Any], None]:
        """Restyle the field once the row's attribute `name` changes to the given value."""

        def refresh(view: TView, renderer_object: TWidget, value: Any) -> None:
            is_invalid = isinstance(view, FormRowView) and view.is_invalid_once(name, value)
            assert isinstance(renderer_object, QWidget)  # a field renderer's
            renderer_object.setStyleSheet((self._invalid_style if is_invalid else None) or "")

        return refresh


class _InputViewLike(ViewLike, Protocol):
    placeholder: str
    text_changed: Signal[str]
    text_edited: Signal[str]
    editing_finished: SignalNoArgs


class InputViewLike(_InputViewLike, Protocol):
    text: str


class QtInputRenderer(QtWidgetRenderer[InputViewLike, QLineEdit]):
    _invalid_style = "QLineEdit { border: 1px solid red; }"

    def __init__(self, view: InputViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "text": self._refresh_text,
                "placeholder": self._refresh_placeholder,
            }
        )

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QLineEdit()
            self._rendered_object.textChanged.connect(self._update_text)
            # Qt reports an edit before the change: the view has the text first
            self._rendered_object.textEdited.connect(self._update_text)
            self._view.editing_finished.add_qt_signal(self._rendered_object.editingFinished)
            self._view.text_changed.add_qt_signal(self._rendered_object.textChanged)
            self._view.text_edited.add_qt_signal(self._rendered_object.textEdited)
            self.refresh()

    @staticmethod
    def _refresh_text(_view: InputViewLike, rendered_object: QLineEdit, value: str) -> None:
        rendered_object.setText(value)

    @staticmethod
    def _refresh_placeholder(_view: InputViewLike, rendered_object: QLineEdit, value: str) -> None:
        rendered_object.setPlaceholderText(value)

    def _update_text(self, text: str) -> None:
        with self.stop_refresh():
            self._view.text = text


class FloatInputViewLike(_InputViewLike, Protocol):
    value: float | None
    minimum: float | None
    maximum: float | None
    decimals: int | None

    def shown_text(self, value: float | None, decimals: int | None) -> str: ...


class QtFloatInputRenderer(QtWidgetRenderer[FloatInputViewLike, QLineEdit]):
    _invalid_style = "QLineEdit { border: 1px solid red; }"

    def __init__(self, view: FloatInputViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "value": self._refresh_value,
                "placeholder": self._refresh_placeholder,
                "minimum": self._refresh_minimum,
                "maximum": self._refresh_maximum,
                "decimals": self._refresh_decimals,
            }
        )

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QLineEdit()
            validator = QDoubleValidator()
            self._rendered_object.setValidator(validator)
            self._rendered_object.textChanged.connect(self._update_text)
            # Qt reports an edit before the change: the view has the value first
            self._rendered_object.textEdited.connect(self._update_text)
            self._view.editing_finished.add_qt_signal(self._rendered_object.editingFinished)
            self._view.text_changed.add_qt_signal(self._rendered_object.textChanged)
            self._view.text_edited.add_qt_signal(self._rendered_object.textEdited)
            self.refresh()

    @staticmethod
    def _refresh_value(
        view: FloatInputViewLike, rendered_object: QLineEdit, value: float | None
    ) -> None:
        rendered_object.setText(view.shown_text(value, view.decimals))

    @staticmethod
    def _refresh_placeholder(
        _view: FloatInputViewLike, rendered_object: QLineEdit, value: str
    ) -> None:
        rendered_object.setPlaceholderText(value)

    @staticmethod
    def _refresh_minimum(
        _view: FloatInputViewLike, rendered_object: QLineEdit, value: float | None
    ) -> None:
        validator = rendered_object.validator()
        assert isinstance(validator, QDoubleValidator)
        validator.setBottom(float("-inf") if value is None else value)

    @staticmethod
    def _refresh_maximum(
        _view: FloatInputViewLike, rendered_object: QLineEdit, value: float | None
    ) -> None:
        validator = rendered_object.validator()
        assert isinstance(validator, QDoubleValidator)
        validator.setTop(float("inf") if value is None else value)

    @staticmethod
    def _refresh_decimals(
        view: FloatInputViewLike, rendered_object: QLineEdit, value: int | None
    ) -> None:
        validator = rendered_object.validator()
        assert isinstance(validator, QDoubleValidator)
        validator.setDecimals(-1 if value is None else value)
        rendered_object.setText(view.shown_text(view.value, value))

    def _update_text(self, text: str) -> None:
        with self.stop_refresh():
            if text != "":
                self._view.value = float(text)
            else:
                self._view.value = None


def _line_edit(rendered_object: QAbstractSpinBox) -> QLineEdit:
    """Get the field of a spin box or a date edit."""
    # `QAbstractSpinBox.lineEdit` is protected
    line_edit = rendered_object.findChild(QLineEdit)
    assert line_edit is not None
    return line_edit


class IntInputViewLike(_InputViewLike, Protocol):
    value: int | None
    minimum: int | None
    maximum: int | None


#: a spin box's widest range: Qt's spin box holds a 32-bit int
_INT_MINIMUM, _INT_MAXIMUM = -(2**31), 2**31 - 1


class QtIntInputRenderer(QtWidgetRenderer[IntInputViewLike, QSpinBox]):
    """A spin box, keeping its value within `minimum`/`maximum`.

    It shows no value while the view's is `None`; once it has one, leaving it emptied
    puts the last value back, as any Qt spin box does.
    """

    _invalid_style = "QSpinBox { border: 1px solid red; }"

    def __init__(self, view: IntInputViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "value": self._refresh_value,
                "placeholder": self._refresh_placeholder,
                "minimum": self._refresh_minimum,
                "maximum": self._refresh_maximum,
            }
        )

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QSpinBox()
            self._rendered_object.setRange(_INT_MINIMUM, _INT_MAXIMUM)
            # its text only changes once acceptable, so never for a transient "-"
            self._rendered_object.valueChanged.connect(self._update_value)
            self._view.editing_finished.add_qt_signal(self._rendered_object.editingFinished)
            self._view.text_changed.add_qt_signal(self._rendered_object.textChanged)
            line_edit = _line_edit(self._rendered_object)
            # Qt reports an edit before the spin box reads it: the view has the value first
            line_edit.textEdited.connect(self._update_edited)
            self._view.text_edited.add_qt_signal(line_edit.textEdited)
            self.refresh()

    @staticmethod
    def _refresh_value(
        _view: IntInputViewLike, rendered_object: QSpinBox, value: int | None
    ) -> None:
        if value is None:
            rendered_object.clear()
        else:
            rendered_object.setValue(value)

    @staticmethod
    def _refresh_placeholder(
        _view: IntInputViewLike, rendered_object: QSpinBox, value: str
    ) -> None:
        _line_edit(rendered_object).setPlaceholderText(value)

    @staticmethod
    def _refresh_minimum(
        view: IntInputViewLike, rendered_object: QSpinBox, value: int | None
    ) -> None:
        rendered_object.setMinimum(_INT_MINIMUM if value is None else value)
        # a new range shows a value even while the view has none
        QtIntInputRenderer._refresh_value(view, rendered_object, view.value)

    @staticmethod
    def _refresh_maximum(
        view: IntInputViewLike, rendered_object: QSpinBox, value: int | None
    ) -> None:
        rendered_object.setMaximum(_INT_MAXIMUM if value is None else value)
        QtIntInputRenderer._refresh_value(view, rendered_object, view.value)

    def _update_value(self, value: int) -> None:
        with self.stop_refresh():
            self._view.value = value

    def _update_edited(self, _text: str) -> None:
        """Give the view the value edited, a whole number in range, before the spin box does."""
        assert self._rendered_object is not None
        text = self._rendered_object.cleanText()
        if text == "":
            with self.stop_refresh():
                self._view.value = None
            return
        try:
            value = int(text)
        except ValueError:
            return  # transient text, e.g. "-": the spin box keeps its value
        if self._rendered_object.minimum() <= value <= self._rendered_object.maximum():
            self._update_value(value)


class DateInputViewLike(_InputViewLike, Protocol):
    value: datetime.date | None
    minimum: datetime.date | None
    maximum: datetime.date | None
    date_format: str
    pick_text: str
    value_changed: Signal[datetime.date | None]


class QtDateInputRenderer(QtWidgetRenderer[DateInputViewLike, QDateField]):
    """A field typing the date as the view's `date_format` says, beside a calendar button.

    Its calendar names the months and days in the system's language: Qt's own, as the
    web's in the browser's.
    """

    _invalid_style = "QLineEdit { border: 1px solid red; }"

    def __init__(self, view: DateInputViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "value": self._refresh_value,
                "placeholder": self._refresh_placeholder,
                "minimum": self._refresh_range,
                "maximum": self._refresh_range,
                "date_format": self._refresh_date_format,
                "pick_text": self._refresh_pick_text,
                # Qt's calendar names them, in the system's language
                "month_names": lambda _view, _rendered_object, _value: None,
                "day_names": lambda _view, _rendered_object, _value: None,
                "previous_month_text": lambda _view, _rendered_object, _value: None,
                "next_month_text": lambda _view, _rendered_object, _value: None,
            }
        )

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QDateField()
            # first, so the view's callbacks see the new date
            self._rendered_object.date_edited.connect(self._update_value)
            line_edit = self._rendered_object.line_edit
            self._view.editing_finished.add_qt_signal(line_edit.editingFinished)
            self._view.text_changed.add_qt_signal(line_edit.textChanged)
            self._view.text_edited.add_qt_signal(line_edit.textEdited)
            self.refresh()

    @staticmethod
    def _refresh_value(
        _view: DateInputViewLike, rendered_object: QDateField, value: datetime.date | None
    ) -> None:
        rendered_object.set_date(value)

    @staticmethod
    def _refresh_placeholder(
        view: DateInputViewLike, rendered_object: QDateField, value: str
    ) -> None:
        rendered_object.line_edit.setPlaceholderText(date_hint(value, view.date_format))

    @staticmethod
    def _refresh_range(view: DateInputViewLike, rendered_object: QDateField, _value: Any) -> None:
        rendered_object.set_range(view.minimum, view.maximum)

    @staticmethod
    def _refresh_date_format(
        view: DateInputViewLike, rendered_object: QDateField, value: str
    ) -> None:
        rendered_object.set_date_format(value)
        rendered_object.line_edit.setPlaceholderText(date_hint(view.placeholder, value))

    @staticmethod
    def _refresh_pick_text(
        _view: DateInputViewLike, rendered_object: QDateField, value: str
    ) -> None:
        rendered_object.button.setToolTip(plain_tool_tip(value))
        rendered_object.button.setAccessibleName(value)

    def _update_value(self, value: datetime.date | None) -> None:
        with self.stop_refresh():
            self._view.value = value
        self._view.value_changed.emit(value)


def _file_filters(extensions: dict[str, tuple[str, ...]]) -> str:
    """Get a file dialog's filters, e.g. "CSV (*.csv);;Text (*.txt *.text)"."""
    return ";;".join(
        f"{name} ({' '.join(f'*{e}' for e in name_extensions)})"
        for name, name_extensions in extensions.items()
    )


class FilePathInputViewLike(InputViewLike, Protocol):
    extensions: dict[str, tuple[str, ...]]
    server_roots: tuple[Path, ...]
    has_reload: bool
    browse_text: str
    reload_text: str
    path_picked: Signal[Path]
    reload_clicked: SignalNoArgs

    @property
    def path(self) -> Path | None: ...


class QtFilePathInputRenderer(QtWidgetRenderer[FilePathInputViewLike, QFilePathField]):
    """A field typing a file's path, then a "…" button opening Qt's file dialog.

    The dialog opens in the directory of the field's path, if any, else in the first of the
    view's `server_roots`.
    """

    _invalid_style = "QLineEdit { border: 1px solid red; }"

    def __init__(self, view: FilePathInputViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "text": self._refresh_text,
                "placeholder": self._refresh_placeholder,
                "has_reload": self._refresh_has_reload,
                "browse_text": self._refresh_browse_text,
                "reload_text": self._refresh_reload_text,
                # read by the dialog each time it opens
                **dict.fromkeys(
                    ("extensions", "server_roots"), lambda _view, _rendered_object, _value: None
                ),
                # the web's list of the server's files only
                **dict.fromkeys(
                    (
                        "parent_folder_text",
                        "cancel_text",
                        "unreadable_folder_text",
                        "partial_folder_text",
                    ),
                    lambda _view, _rendered_object, _value: None,
                ),
            }
        )

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QFilePathField()
            line_edit = self._rendered_object.line_edit
            line_edit.textChanged.connect(self._update_text)
            # Qt reports an edit before the change: the view has the text first
            line_edit.textEdited.connect(self._update_text)
            self._view.editing_finished.add_qt_signal(line_edit.editingFinished)
            self._view.text_changed.add_qt_signal(line_edit.textChanged)
            self._view.text_edited.add_qt_signal(line_edit.textEdited)
            self._rendered_object.browse_button.clicked.connect(self.browse)
            self._view.reload_clicked.add_qt_signal(self._rendered_object.reload_button.clicked)
            self.refresh()

    def browse(self) -> None:
        """Pick a file in Qt's dialog, its path then the field's; nothing if cancelled."""
        assert self._rendered_object is not None
        path, roots = self._view.path, self._view.server_roots
        start = path.parent if path is not None else (roots[0] if roots else None)
        directory = "" if start is None else str(start)
        picked, _selected_filter = QFileDialog.getOpenFileName(
            self._rendered_object,
            self._view.browse_text,
            directory,
            _file_filters(self._view.extensions),
        )
        if picked == "":
            return
        # its `textChanged` gives the view the text, and reports it
        self._rendered_object.line_edit.setText(picked)
        self._view.path_picked.emit(Path(picked))

    @staticmethod
    def _refresh_text(
        _view: FilePathInputViewLike, rendered_object: QFilePathField, value: str
    ) -> None:
        # the field's own signals: set in code, the text isn't reported, as a QLineEdit's
        with QSignalBlocker(rendered_object.line_edit):
            rendered_object.line_edit.setText(value)

    @staticmethod
    def _refresh_placeholder(
        _view: FilePathInputViewLike, rendered_object: QFilePathField, value: str
    ) -> None:
        rendered_object.line_edit.setPlaceholderText(value)

    @staticmethod
    def _refresh_has_reload(
        _view: FilePathInputViewLike, rendered_object: QFilePathField, value: bool
    ) -> None:
        rendered_object.reload_button.setVisible(value)

    @staticmethod
    def _refresh_browse_text(
        _view: FilePathInputViewLike, rendered_object: QFilePathField, value: str
    ) -> None:
        rendered_object.browse_button.setToolTip(plain_tool_tip(value))
        rendered_object.browse_button.setAccessibleName(value)

    @staticmethod
    def _refresh_reload_text(
        _view: FilePathInputViewLike, rendered_object: QFilePathField, value: str
    ) -> None:
        rendered_object.reload_button.setToolTip(plain_tool_tip(value))
        rendered_object.reload_button.setAccessibleName(value)

    def _update_text(self, text: str) -> None:
        with self.stop_refresh():
            self._view.text = text


class SliderViewLike(ViewLike, Protocol):
    value: int
    minimum: int
    maximum: int
    step: int
    value_changed: Signal[int]


class QtSliderRenderer(QtWidgetRenderer[SliderViewLike, QValueSlider]):
    """A horizontal slider stopping on each step, its value painted beside the track."""

    _invalid_style = "QSlider { border: 1px solid red; }"

    def __init__(self, view: SliderViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "value": self._refresh_value,
                "minimum": self._refresh_minimum,
                "maximum": self._refresh_maximum,
                "step": self._refresh_step,
            }
        )

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QValueSlider()
            # first, so the view's callbacks see the new value
            self._rendered_object.shown_value_changed.connect(self._update_value)
            self._view.value_changed.add_qt_signal(self._rendered_object.shown_value_changed)
            self.refresh()

    @staticmethod
    def _refresh_value(view: SliderViewLike, rendered_object: QValueSlider, value: int) -> None:
        QtSliderRenderer._show(rendered_object, value, view.minimum, view.maximum, view.step)

    @staticmethod
    def _refresh_minimum(view: SliderViewLike, rendered_object: QValueSlider, value: int) -> None:
        QtSliderRenderer._show(rendered_object, view.value, value, view.maximum, view.step)

    @staticmethod
    def _refresh_maximum(view: SliderViewLike, rendered_object: QValueSlider, value: int) -> None:
        QtSliderRenderer._show(rendered_object, view.value, view.minimum, value, view.step)

    @staticmethod
    def _refresh_step(view: SliderViewLike, rendered_object: QValueSlider, value: int) -> None:
        QtSliderRenderer._show(rendered_object, view.value, view.minimum, view.maximum, value)

    @staticmethod
    def _show(
        rendered_object: QValueSlider, value: int, minimum: int, maximum: int, step: int
    ) -> None:
        last = SliderMixin.last_position(minimum, maximum, step)
        rendered_object.first, rendered_object.step = minimum, step
        rendered_object.setRange(0, last)
        rendered_object.setPageStep(max(1, last // 10))
        rendered_object.setValue(SliderMixin.position(value, minimum, maximum, step))
        rendered_object.updateGeometry()  # the value's slot follows the widest value
        rendered_object.update()  # the value painted, even if the handle didn't move

    def _update_value(self, value: int) -> None:
        with self.stop_refresh():
            self._view.value = value


class LabelViewLike(ViewLike, Protocol):
    text: str


class QtLabelRenderer(QtWidgetRenderer[LabelViewLike, QLabel]):
    def __init__(self, view: LabelViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "text": self._refresh_text,
            }
        )

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = plain_label()
            self.refresh()

    @staticmethod
    def _refresh_text(_view: LabelViewLike, rendered_object: QLabel, value: str) -> None:
        rendered_object.setText(value)


class MarkdownViewLike(ViewLike, Protocol):
    text: str


class QtMarkdownRenderer(QtWidgetRenderer[MarkdownViewLike, QTextBrowser]):
    def __init__(self, view: MarkdownViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update({"text": self._refresh_text})

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QTextBrowser()
            self._rendered_object.setOpenExternalLinks(True)
            self.refresh()

    @staticmethod
    def _refresh_text(_view: MarkdownViewLike, rendered_object: QTextBrowser, value: str) -> None:
        # raw HTML shown as text, as on the web
        features = QTextDocument.MarkdownFeature
        rendered_object.document().setMarkdown(
            value, features.MarkdownDialectGitHub | features.MarkdownNoHTML
        )


class QtFormLabelRenderer(QtWidgetRenderer[FormLabelRowView, QFormLabel]):
    def __init__(self, view: FormLabelRowView) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "label": self._refresh_text,
                "help": self._refresh_help,
                "help_button_text": self._refresh_help_button_text,
            }
        )

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QFormLabel()
            self.refresh()

    @staticmethod
    def _refresh_text(_view: FormLabelRowView, rendered_object: QFormLabel, value: str) -> None:
        rendered_object.set_text(value)

    @staticmethod
    def _refresh_help(_view: FormLabelRowView, rendered_object: QFormLabel, value: str) -> None:
        rendered_object.set_help(value)

    @staticmethod
    def _refresh_help_button_text(
        _view: FormLabelRowView, rendered_object: QFormLabel, value: str
    ) -> None:
        rendered_object.set_help_button_text(value)


class CheckBoxViewLike(ViewLike, Protocol):
    text: str
    is_checked: bool
    toggled: Signal[bool]


class QtCheckBoxRenderer(QtWidgetRenderer[CheckBoxViewLike, QCheckBox]):
    _invalid_style = "QCheckBox { color: red; }"

    def __init__(self, view: CheckBoxViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "text": self._refresh_text,
                "is_checked": self._refresh_is_checked,
            }
        )

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QCheckBox()
            # first, so the view's callbacks see the new check state
            self._rendered_object.toggled.connect(self._update_checked)
            self._view.toggled.add_qt_signal(self._rendered_object.toggled)
            self.refresh()

    @staticmethod
    def _refresh_text(_view: CheckBoxViewLike, rendered_object: QCheckBox, value: str) -> None:
        rendered_object.setText(value)

    @staticmethod
    def _refresh_is_checked(
        _view: CheckBoxViewLike, rendered_object: QCheckBox, value: bool
    ) -> None:
        rendered_object.setChecked(value)

    def _update_checked(self, is_checked: bool) -> None:
        with self.stop_refresh():
            self._view.is_checked = is_checked


class ButtonViewLike(ViewLike, Protocol):
    text: str
    variant: ButtonVariant
    clicked: SignalNoArgs


class QtButtonRenderer(QtWidgetRenderer[ButtonViewLike, QPushButton]):
    def __init__(self, view: ButtonViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {"text": self._refresh_text, "variant": self._refresh_variant}
        )

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QPushButton()
            # Qt's own `clicked` also passes the check state, which a button doesn't have
            self._rendered_object.clicked.connect(self._emit_clicked)
            self.refresh()

    @staticmethod
    def _refresh_text(_view: ButtonViewLike, rendered_object: QPushButton, value: str) -> None:
        rendered_object.setText(value)

    @staticmethod
    def _refresh_variant(
        _view: ButtonViewLike, rendered_object: QPushButton, value: ButtonVariant
    ) -> None:
        # Qt has no variants: the style draws a default button emphasized, and a
        # destroying one is red like an invalid field
        rendered_object.setDefault(value is ButtonVariant.PRIMARY)
        is_danger = value is ButtonVariant.DANGER
        rendered_object.setStyleSheet("QPushButton { color: red; }" if is_danger else "")

    def _emit_clicked(self) -> None:
        self._view.clicked.emit()


class ProgressBarViewLike(ViewLike, Protocol):
    value: int
    maximum: int | None


class QtProgressBarRenderer(QtWidgetRenderer[ProgressBarViewLike, QProgressBar]):
    def __init__(self, view: ProgressBarViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {"value": self._refresh_value, "maximum": self._refresh_maximum}
        )

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QProgressBar()
            self.refresh()

    @staticmethod
    def _refresh_value(
        view: ProgressBarViewLike, rendered_object: QProgressBar, value: int
    ) -> None:
        # clamped: Qt ignores a value out of range, leaving the bar where it was
        rendered_object.setValue(ProgressBarView.clamp(value, view.maximum))

    @staticmethod
    def _refresh_maximum(
        view: ProgressBarViewLike, rendered_object: QProgressBar, value: int | None
    ) -> None:
        # an empty range is Qt's busy bar, for a task of unknown length
        rendered_object.setRange(0, 0 if value is None else value)
        rendered_object.setValue(ProgressBarView.clamp(view.value, value))


def _map_renderer(view: Any) -> Renderer[Any, Any]:
    # Qt Quick and its native libraries are needed only by applications that use maps.
    renderer: Renderer[Any, Any] = import_module("composeui.qtcore.maprenderer").QtMapRenderer(view)
    return renderer


class ChartViewLike(ViewLike, Protocol):
    kind: ChartKind
    title: str
    x_title: str
    y_title: str
    x_unit: str
    y_unit: str
    series: list[Series]
    reference_lines: list[ReferenceLine]
    categories: list[str]
    x_log: bool
    y_log: bool
    save_image_text: str
    clicked: Signal[float, float]
    height: int | None


#: Qt's largest widget size, a widget's maximum when nothing limits it
_QWIDGETSIZE_MAX = 16777215
#: the formats the Save Image dialog offers, the vector ones first, by its filters
_IMAGE_FILTERS = {"PDF (*.pdf)": "pdf", "SVG (*.svg)": "svg", "PNG (*.png)": "png"}


class QtChartRenderer(QtWidgetRenderer[ChartViewLike, QChart]):
    def __init__(self, view: ChartViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "kind": self._refresh_kind,
                "title": self._refresh_title,
                "x_title": self._refresh_x_title,
                "x_unit": self._refresh_x_unit,
                "y_title": self._refresh_y_title,
                "y_unit": self._refresh_y_unit,
                "series": self._refresh_series,
                "reference_lines": self._refresh_reference_lines,
                "categories": self._refresh_categories,
                "x_log": self._refresh_x_log,
                "y_log": self._refresh_y_log,
                "save_image_text": self._refresh_save_image_text,
                "height": self._refresh_height,
            }
        )

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QChart()
            self._rendered_object.save_image_requested.connect(self._save_image)
            self._rendered_object.point_clicked.connect(self._view.clicked.emit)
            self.refresh()

    @staticmethod
    def _refresh_kind(_view: ChartViewLike, rendered_object: QChart, value: ChartKind) -> None:
        rendered_object.set_kind(value)

    @staticmethod
    def _refresh_title(_view: ChartViewLike, rendered_object: QChart, value: str) -> None:
        rendered_object.set_title(value)

    # each refreshed with its new value, the view still holding the old one
    @staticmethod
    def _refresh_x_title(view: ChartViewLike, rendered_object: QChart, value: str) -> None:
        rendered_object.set_axis("bottom", value, view.x_unit)

    @staticmethod
    def _refresh_x_unit(view: ChartViewLike, rendered_object: QChart, value: str) -> None:
        rendered_object.set_axis("bottom", view.x_title, value)

    @staticmethod
    def _refresh_y_title(view: ChartViewLike, rendered_object: QChart, value: str) -> None:
        rendered_object.set_axis("left", value, view.y_unit)

    @staticmethod
    def _refresh_y_unit(view: ChartViewLike, rendered_object: QChart, value: str) -> None:
        rendered_object.set_axis("left", view.y_title, value)

    @staticmethod
    def _refresh_series(_view: ChartViewLike, rendered_object: QChart, value: list[Series]) -> None:
        rendered_object.set_series(value)

    @staticmethod
    def _refresh_reference_lines(
        _view: ChartViewLike, rendered_object: QChart, value: list[ReferenceLine]
    ) -> None:
        rendered_object.set_reference_lines(value)

    @staticmethod
    def _refresh_categories(
        _view: ChartViewLike, rendered_object: QChart, value: list[str]
    ) -> None:
        rendered_object.set_categories(value)

    @staticmethod
    def _refresh_x_log(view: ChartViewLike, rendered_object: QChart, value: bool) -> None:
        rendered_object.set_log(x_log=value, y_log=view.y_log)

    @staticmethod
    def _refresh_y_log(view: ChartViewLike, rendered_object: QChart, value: bool) -> None:
        rendered_object.set_log(x_log=view.x_log, y_log=value)

    @staticmethod
    def _refresh_save_image_text(_view: ChartViewLike, rendered_object: QChart, value: str) -> None:
        rendered_object.save_image_action.setText(f"{value}…")

    @staticmethod
    def _refresh_height(_view: ChartViewLike, rendered_object: QChart, value: int | None) -> None:
        # None: as tall as the layout makes it
        rendered_object.setMinimumHeight(0 if value is None else value)
        rendered_object.setMaximumHeight(_QWIDGETSIZE_MAX if value is None else value)
        # the layout lays it out again, back at its share of the column too
        rendered_object.updateGeometry()

    def _save_image(self) -> None:
        """Ask where to save the chart's image, and save it as it shows, zoomed in too."""
        chart, view = self._rendered_object, self._view
        assert chart is not None
        assert isinstance(view, ChartView)
        path, chosen = QFileDialog.getSaveFileName(
            chart,
            view.save_image_text,
            chartimage.image_name(view.title, "pdf"),
            ";;".join(_IMAGE_FILTERS),
        )
        if path == "":
            return
        filepath = Path(path)
        if filepath.suffix.lstrip(".").lower() not in chartimage.FORMATS:
            filepath = filepath.with_name(f"{filepath.name}.{_IMAGE_FILTERS.get(chosen, 'pdf')}")
        x_range, y_range = chart.shown_range()
        options = chartimage.ImageOptions(x_range=x_range, y_range=y_range)
        chartimage.save_chart_image(view, filepath, options)


class MetricViewLike(ViewLike, Protocol):
    label: str
    value: str
    delta: float | None
    delta_text: str


class QtMetricRenderer(QtWidgetRenderer[MetricViewLike, QMetric]):
    def __init__(self, view: MetricViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "label": self._refresh_label,
                "value": self._refresh_value,
                "delta": self._refresh_delta,
                "delta_text": self._refresh_delta_text,
            }
        )

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QMetric()
            self.refresh()

    @staticmethod
    def _refresh_label(_view: MetricViewLike, rendered_object: QMetric, value: str) -> None:
        rendered_object.label.setText(value)

    @staticmethod
    def _refresh_value(_view: MetricViewLike, rendered_object: QMetric, value: str) -> None:
        rendered_object.value.setText(value)

    @staticmethod
    def _refresh_delta(view: MetricViewLike, rendered_object: QMetric, value: float | None) -> None:
        QtMetricRenderer._show_badge(rendered_object, value, view.delta_text)

    @staticmethod
    def _refresh_delta_text(view: MetricViewLike, rendered_object: QMetric, value: str) -> None:
        QtMetricRenderer._show_badge(rendered_object, view.delta, value)

    @staticmethod
    def _show_badge(rendered_object: QMetric, delta: float | None, delta_text: str) -> None:
        if delta is None:
            rendered_object.set_delta("", 0)
        else:
            sign = (delta > 0) - (delta < 0)
            rendered_object.set_delta(MetricView.badge(delta, delta_text), sign)


class TableViewLike(ViewLike, Protocol):
    headers: list[str]
    filter_texts: dict[str, str]
    selection_mode: SelectionMode
    rows: list[list[str]]
    sortable_columns: list[int]
    filterable_columns: list[int]
    sort_column: int | None
    sort_descending: bool
    search: str
    filters: dict[int, str]
    selected_rows: list[int]
    shown_rows: list[int]
    selection_changed: Signal[list[int]]
    editable_columns: list[int]
    cell_edited: Signal[int, int, str]
    cell_widgets: dict[int, CellWidget]
    cell_clicked: Signal[int, int]
    cell_styles: dict[tuple[int, int], CellStyle]
    header_groups: list[HeaderGroup]
    row_headers: list[str]

    def emit_cell_edited(self, row: int, column: int, text: str) -> None: ...
    def mark_text(self, mark: NodeMark) -> str: ...
    def shown_cell_styles(self) -> dict[tuple[int, int], CellStyle]: ...
    def column_checked(self, column: int) -> bool | None: ...
    def check_all(self, column: int, *, is_checked: bool) -> None: ...
    def sort_by(self, column: int) -> None: ...
    def filter_error(self, column: int, text: str) -> str | None: ...
    def filter_placeholder(self, column: int, *, is_pattern: bool = False) -> str: ...
    def filter_takes_pattern(self, column: int) -> bool: ...
    def filter_chip(self, column: int) -> str: ...


class SourceTableViewLike(ViewLike, Protocol):
    texts: dict[str, str]
    export_filename: str
    sort_column: str | None
    sort_descending: bool
    search: str
    filters: dict[str, str]
    filterable_columns: list[str]
    filter_texts: dict[str, str]

    @property
    def headers(self) -> list[str]: ...
    @property
    def column_names(self) -> list[str]: ...
    @property
    def row_count(self) -> int: ...
    def rows(self, start: int, stop: int) -> list[tuple[Any, list[str]]]: ...
    def sort_by(self, column: str) -> None: ...
    def is_selected(self, row_id: Any) -> bool: ...
    def select_at(self, position: int) -> None: ...
    def extend_to(self, position: int) -> None: ...
    def activate_at(self, position: int) -> None: ...
    @property
    def count_text(self) -> str: ...
    def header(self, column: str) -> str: ...
    def filter_error(self, column: str, text: str) -> str | None: ...
    def filter_takes_pattern(self, column: str) -> bool: ...
    def filter_placeholder(self, column: str, *, is_pattern: bool = False) -> str: ...
    def filter_chip(self, column: str) -> str: ...
    def selection_text(self) -> str: ...
    def export_csv(self, path: Path) -> None: ...


class QtSourceTableRenderer(QtWidgetRenderer[SourceTableViewLike, QDataFilterTable]):
    """A large table: Qt asks the view for the rows it draws, as the user scrolls.

    A click on a header sorts by its column (`SourceTableView.sort_by`). A click on a row
    selects it (`select_at`), Shift extending the selection (`extend_to`), and a double
    click activates it (`activate_at`).

    Its filter bar (`QTableFilterBar`) searches it, and filters the columns of
    `filterable_columns`: the bar knows them by their position among the source's.
    Ctrl+C copies the selected rows to the clipboard (`SourceTableView.selection_text`).
    Export CSV, above the rows and in their context menu, asks where to write the rows
    (`export_csv`). While a job orders the rows (`is_ordering`), the cursor over them is
    busy.
    """

    def __init__(self, view: SourceTableViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "source": self._refresh_source,
                "row_count": self._reset,
                "column_formats": self._repaint,
                "filter_texts": self._refresh_filter_texts,
                "filterable_columns": self._refresh_filterable_columns,
                "search": self._refresh_search,
                "filters": self._refresh_filters,
                # shown with the order they give, which the view sends as `row_count`
                "sort_column": lambda _view, _table, _value: None,
                "sort_descending": lambda _view, _table, _value: None,
                # each click asks the view, which knows the mode
                "selection_mode": lambda _view, _table, _value: None,
                "selected_ids": self._repaint,
                "texts": self._refresh_texts,
                # read as the user exports
                "export_filename": lambda _view, _table, _value: None,
                "is_ordering": self._refresh_is_ordering,
            }
        )

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QDataFilterTable(self._view)
            table, bar = self._rendered_object.table, self._rendered_object.bar
            columns = SourceTableByPosition(self._view)
            table.header_clicked.connect(columns.sort_by)
            table.row_clicked.connect(
                lambda position, is_extended: columns.select(position, is_extended=is_extended)
            )
            table.row_activated.connect(self._view.activate_at)
            table.copy_requested.connect(
                lambda: QApplication.clipboard().setText(self._view.selection_text())
            )
            table.export_requested.connect(self._export)
            bar.check = columns.filter_error
            bar.placeholder = lambda column, is_pattern: columns.filter_placeholder(
                column, is_pattern=is_pattern
            )
            bar.takes_pattern = columns.filter_takes_pattern
            bar.search_edited.connect(self._update_search)
            bar.filter_added.connect(columns.add_filter)
            bar.filter_removed.connect(columns.remove_filter)
            bar.filters_cleared.connect(columns.clear_filters)
            self.refresh()

    @classmethod
    def _refresh_source(
        cls, view: SourceTableViewLike, rendered_object: QDataFilterTable, value: Any
    ) -> None:
        """Show the new source's columns in the bar, then its rows."""
        cls._refresh_filterable_columns(view, rendered_object, view.filterable_columns)
        cls._refresh_filters(view, rendered_object, view.filters)
        cls._reset(view, rendered_object, value)

    @staticmethod
    def _reset(view: SourceTableViewLike, rendered_object: QDataFilterTable, _value: Any) -> None:
        """Show a new order of the rows: the sort indicator, the count, and no row if none."""
        table = rendered_object.table
        table.data_model.reset()
        sort = SourceTableByPosition(view).sort
        table.set_sort_indicator(sort)
        rendered_object.bar.set_count(view.count_text)
        rendered_object.empty.setVisible(view.row_count == 0 and view.count_text != "")

    @staticmethod
    def _refresh_texts(
        _view: SourceTableViewLike, rendered_object: QDataFilterTable, value: dict[str, str]
    ) -> None:
        # "empty": the web's; here the headers stay, over no row
        rendered_object.table.export_action.setText(f"{value.get('export', '')}…")

    @staticmethod
    def _refresh_is_ordering(
        _view: SourceTableViewLike, rendered_object: QDataFilterTable, value: bool
    ) -> None:
        rows = rendered_object.table.viewport()
        if value:
            rows.setCursor(Qt.CursorShape.BusyCursor)
        else:
            rows.unsetCursor()

    def _export(self) -> None:
        """Ask where to write the rows shown as CSV, and write them there."""
        table = self._rendered_object
        assert table is not None
        path, _chosen = QFileDialog.getSaveFileName(
            table, self._view.texts.get("export", ""), self._view.export_filename, "CSV (*.csv)"
        )
        if path != "":
            filepath = Path(path)
            if filepath.suffix.lower() != ".csv":
                filepath = filepath.with_name(f"{filepath.name}.csv")
            self._view.export_csv(filepath)

    @staticmethod
    def _refresh_filter_texts(
        view: SourceTableViewLike, rendered_object: QDataFilterTable, value: dict[str, str]
    ) -> None:
        rendered_object.bar.set_texts(value)
        rendered_object.bar.set_count(view.count_text)
        rendered_object.empty.setText(value.get("no_match", ""))

    @staticmethod
    def _refresh_filterable_columns(
        view: SourceTableViewLike, rendered_object: QDataFilterTable, value: list[str]
    ) -> None:
        columns = SourceTableByPosition(view).bar_columns(value)
        rendered_object.bar.set_columns(columns)
        rendered_object.bar.setVisible(len(columns) > 0)

    @staticmethod
    def _refresh_search(
        _view: SourceTableViewLike, rendered_object: QDataFilterTable, value: str
    ) -> None:
        rendered_object.bar.set_search(value)

    @staticmethod
    def _refresh_filters(
        view: SourceTableViewLike, rendered_object: QDataFilterTable, value: dict[str, str]
    ) -> None:
        rendered_object.bar.set_filters(SourceTableByPosition(view).chips(value))

    def _update_search(self, text: str) -> None:
        with self.stop_refresh():
            self._view.search = text

    @staticmethod
    def _repaint(
        _view: SourceTableViewLike, rendered_object: QDataFilterTable, _value: Any
    ) -> None:
        rendered_object.table.data_model.repaint()


class QtTableRenderer(QtWidgetRenderer[TableViewLike, QFilterTable]):
    """A table under its filter bar; the table shows `shown_rows`, in their order.

    The widgets know the rows only as shown: their indexes map back to `rows` through
    `shown_rows`. A file path cell's button opens Qt's file dialog in the directory of
    the cell's path, if any.
    """

    def __init__(self, view: TableViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "headers": self._refresh_headers,
                "filter_texts": self._refresh_filter_texts,
                "selection_mode": self._refresh_selection_mode,
                # shown with `shown_rows`, which the view always sends next
                "rows": lambda _view, _table, _value: None,
                "sortable_columns": self._refresh_sort,
                "filterable_columns": self._refresh_filterable_columns,
                "sort_column": self._refresh_sort,
                "sort_descending": self._refresh_sort,
                "search": self._refresh_search,
                "filters": self._refresh_filters,
                "selected_rows": self._refresh_selected_rows,
                "shown_rows": self._refresh_shown_rows,
                "editable_columns": self._refresh_editable_columns,
                "cell_widgets": self._refresh_cell_widgets,
                # the web's list of the server's files only
                "file_texts": lambda _view, _rendered_object, _value: None,
                "cell_styles": self._refresh_looks,
                "header_groups": self._refresh_header_groups,
                "row_headers": self._refresh_looks,
                "done_text": functools.partial(self._refresh_mark_text, NodeMark.DONE),
                "warning_text": functools.partial(self._refresh_mark_text, NodeMark.WARNING),
                "error_text": functools.partial(self._refresh_mark_text, NodeMark.ERROR),
            }
        )

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QFilterTable()
            table, bar = self._rendered_object.table, self._rendered_object.bar
            table.selected_rows_changed.connect(self._update_selected_rows)
            table.cell_edited.connect(self._update_cell)
            table.cell_clicked.connect(self._click_cell)
            table.browse_clicked.connect(self._browse)
            table.check_all_clicked.connect(self._check_all)
            table.header_clicked.connect(self._sort_by)
            bar.check = self._view.filter_error
            bar.placeholder = lambda column, is_pattern: self._view.filter_placeholder(
                column, is_pattern=is_pattern
            )
            bar.takes_pattern = self._view.filter_takes_pattern
            bar.search_edited.connect(self._update_search)
            bar.filter_added.connect(self._add_filter)
            bar.filter_removed.connect(self._remove_filter)
            bar.filters_cleared.connect(self._clear_filters)
            self.refresh()

    @classmethod
    def _refresh_headers(
        cls, view: TableViewLike, rendered_object: QFilterTable, _value: list[str]
    ) -> None:
        cls._refresh_shown_rows(view, rendered_object, view.shown_rows)
        cls._refresh_filterable_columns(view, rendered_object, view.filterable_columns)
        cls._refresh_filters(view, rendered_object, view.filters)
        cls._refresh_sort(view, rendered_object, None)

    @staticmethod
    def _refresh_filter_texts(
        view: TableViewLike, rendered_object: QFilterTable, value: dict[str, str]
    ) -> None:
        rendered_object.bar.set_texts(value)
        rendered_object.bar.set_count(_count_text(view, view.shown_rows))
        rendered_object.empty.setText(value.get("no_match", ""))

    @staticmethod
    def _refresh_selection_mode(
        _view: TableViewLike, rendered_object: QFilterTable, value: SelectionMode
    ) -> None:
        rendered_object.table.set_multiple_selection(is_multiple=value is SelectionMode.MULTIPLE)

    @staticmethod
    def _refresh_sort(view: TableViewLike, rendered_object: QFilterTable, _value: Any) -> None:
        sort = None if view.sort_column is None else (view.sort_column, view.sort_descending)
        rendered_object.table.set_sort_indicator(sort, is_shown=len(view.sortable_columns) > 0)

    @staticmethod
    def _refresh_filterable_columns(
        view: TableViewLike, rendered_object: QFilterTable, value: list[int]
    ) -> None:
        columns = [(column, view.headers[column]) for column in value if column < len(view.headers)]
        rendered_object.bar.set_columns(columns)
        rendered_object.bar.setVisible(len(columns) > 0)

    @staticmethod
    def _refresh_search(_view: TableViewLike, rendered_object: QFilterTable, value: str) -> None:
        rendered_object.bar.set_search(value)

    @staticmethod
    def _refresh_filters(
        view: TableViewLike, rendered_object: QFilterTable, value: dict[int, str]
    ) -> None:
        rendered_object.bar.set_filters(
            [
                (column, view.filter_chip(column), text, view.headers[column])
                for column, text in sorted(value.items())
                if column < len(view.headers)
            ]
        )

    @staticmethod
    def _refresh_selected_rows(
        view: TableViewLike, rendered_object: QFilterTable, value: list[int]
    ) -> None:
        positions = {row: position for position, row in enumerate(view.shown_rows)}
        rendered_object.table.set_selected_rows(
            sorted(positions[row] for row in value if row in positions)
        )

    @classmethod
    def _refresh_shown_rows(
        cls, view: TableViewLike, rendered_object: QFilterTable, value: list[int]
    ) -> None:
        row_headers = [
            view.row_headers[row] if row < len(view.row_headers) else "" for row in value
        ]
        rendered_object.table.set_table(
            view.headers,
            [view.rows[row] for row in value],
            view.shown_cell_styles(),
            row_headers if len(view.row_headers) > 0 else [],
        )
        # resetting the table drops its selection: reapply it
        cls._refresh_selected_rows(view, rendered_object, view.selected_rows)
        rendered_object.bar.set_count(_count_text(view, value))
        rendered_object.empty.setVisible(len(value) == 0 and len(view.rows) > 0)
        cls._refresh_checked_columns(view, rendered_object)

    @staticmethod
    def _refresh_checked_columns(
        view: TableViewLike,
        rendered_object: QFilterTable,
        *,
        editable_columns: list[int] | None = None,
        cell_widgets: dict[int, CellWidget] | None = None,
    ) -> None:
        """Show each check-all box; with the new value of a field the view doesn't hold yet."""
        editable = view.editable_columns if editable_columns is None else editable_columns
        widgets = view.cell_widgets if cell_widgets is None else cell_widgets
        rendered_object.table.set_checked_columns(
            {
                column: (view.column_checked(column), column in editable)
                for column, widget in widgets.items()
                if widget.kind is CellKind.CHECK_BOX and widget.check_all
            }
        )

    @classmethod
    def _refresh_editable_columns(
        cls, view: TableViewLike, rendered_object: QFilterTable, value: list[int]
    ) -> None:
        rendered_object.table.set_editable_columns(value)
        cls._refresh_checked_columns(view, rendered_object, editable_columns=value)

    @classmethod
    def _refresh_cell_widgets(
        cls, view: TableViewLike, rendered_object: QFilterTable, value: dict[int, CellWidget]
    ) -> None:
        rendered_object.table.set_cell_widgets(value)
        cls._refresh_checked_columns(view, rendered_object, cell_widgets=value)

    @classmethod
    def _refresh_looks(
        cls, view: TableViewLike, rendered_object: QFilterTable, _value: Any
    ) -> None:
        cls._refresh_shown_rows(view, rendered_object, view.shown_rows)

    @staticmethod
    def _refresh_header_groups(
        _view: TableViewLike, rendered_object: QFilterTable, value: list[HeaderGroup]
    ) -> None:
        rendered_object.table.set_header_groups(value)

    @staticmethod
    def _refresh_mark_text(
        mark: NodeMark, _view: TableViewLike, rendered_object: QFilterTable, value: str
    ) -> None:
        rendered_object.table.set_mark_text(mark, value)

    def _update_selected_rows(self, positions: list[int]) -> None:
        shown = self._view.shown_rows
        rows = sorted(shown[position] for position in positions)
        with self.stop_refresh():
            self._view.selected_rows = rows
        self._view.selection_changed.emit(rows)

    def _update_cell(self, position: int, column: int, text: str) -> None:
        rows, row = self._view.rows, self._view.shown_rows[position]
        self._view.emit_cell_edited(row, column, text)
        if self._view.rows is rows:
            with self.stop_refresh():
                self._view.rows = replace_cell(rows, row, column, text)
        assert self._rendered_object is not None
        # a check-all box follows its column's
        self._refresh_checked_columns(self._view, self._rendered_object)

    def _click_cell(self, position: int, column: int) -> None:
        self._view.cell_clicked.emit(self._view.shown_rows[position], column)

    def _browse(self, position: int, column: int) -> None:
        """Pick a file in Qt's dialog, its path then the cell's; nothing if cancelled.

        The dialog opens in the folder of the cell's path, else in the first server root.
        """
        assert self._rendered_object is not None
        widget = self._view.cell_widgets[column]
        cells = self._view.rows[self._view.shown_rows[position]]
        text = cells[column].strip() if column < len(cells) else ""
        roots = widget.server_roots
        start = Path(text).parent if text != "" else (roots[0] if roots else None)
        picked, _selected_filter = QFileDialog.getOpenFileName(
            self._rendered_object,
            widget.text,
            "" if start is None else str(start),
            _file_filters(widget.extensions),
        )
        if picked != "":
            self._rendered_object.table.set_text(position, column, picked)

    def _check_all(self, column: int) -> None:
        if column in self._view.editable_columns:
            self._view.check_all(column, is_checked=self._view.column_checked(column) is not True)

    def _sort_by(self, column: int) -> None:
        if column in self._view.sortable_columns:
            self._view.sort_by(column)

    def _update_search(self, text: str) -> None:
        with self.stop_refresh():
            self._view.search = text

    def _add_filter(self, column: int, text: str) -> None:
        self._view.filters = {**self._view.filters, column: text}

    def _remove_filter(self, column: int) -> None:
        self._view.filters = {
            other: text for other, text in self._view.filters.items() if other != column
        }

    def _clear_filters(self) -> None:
        self._view.filters = {}


def _count_text(view: TableViewLike, shown: list[int]) -> str:
    """Count the rows shown, while the search or the filters hide some."""
    if len(shown) == len(view.rows):
        return ""
    return view.filter_texts.get("count", "").format(shown=len(shown), total=len(view.rows))


TValue = TypeVar("TValue")


class ValuesViewLike(ViewLike, Protocol, Generic[TValue]):
    value: TValue | None
    values: dict[str, TValue]
    value_changed: Signal[TValue | None]


class QtRadioGroupRenderer(QtWidgetRenderer[ValuesViewLike[TValue], QRadioGroup], Generic[TValue]):
    _invalid_style = "QRadioButton { color: red; }"

    def __init__(self, view: ValuesViewLike[TValue]) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "value": self._refresh_value,
                "values": self._refresh_values,
            }
        )

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QRadioGroup(self._view.values)
            self._rendered_object.value_changed.connect(self._update_value)
            self._view.value_changed.add_qt_signal(self._rendered_object.value_changed)
            self.refresh()

    @staticmethod
    def _refresh_value(
        _view: ValuesViewLike[TValue], rendered_object: QRadioGroup, value: Any
    ) -> None:
        rendered_object.set_value(value)

    @staticmethod
    def _refresh_values(
        view: ValuesViewLike[TValue], rendered_object: QRadioGroup, values: dict[str, Any]
    ) -> None:
        # rebuilding leaves nothing checked, even if `view.value` didn't itself change
        # (and so wouldn't otherwise trigger its own refresh) - reapply it explicitly
        rendered_object.set_values(values)
        rendered_object.set_value(view.value)

    def _update_value(self, value: TValue | None) -> None:
        with self.stop_refresh():
            self._view.value = value


class QtComboBoxRenderer(
    QtWidgetRenderer[ValuesViewLike[TValue], QValueComboBox[TValue]], Generic[TValue]
):
    _invalid_style = "QComboBox { border: 1px solid red; }"

    def __init__(self, view: ValuesViewLike[TValue]) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "value": self._refresh_value,
                "values": self._refresh_values,
            }
        )

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QValueComboBox(self._view.values)
            self._rendered_object.current_value_changed.connect(self._update_value)
            self._view.value_changed.add_qt_signal(self._rendered_object.current_value_changed)
            self.refresh()

    @staticmethod
    def _refresh_value(
        _view: ValuesViewLike[TValue], rendered_object: QValueComboBox[TValue], value: TValue
    ) -> None:
        rendered_object.set_current_value(value)

    @staticmethod
    def _refresh_values(
        view: ValuesViewLike[TValue],
        rendered_object: QValueComboBox[TValue],
        values: dict[str, TValue],
    ) -> None:
        rendered_object.set_values(values)
        rendered_object.set_current_value(view.value)

    def _update_value(self, value: TValue | None) -> None:
        with self.stop_refresh():
            self._view.value = value


class LogViewLike(ViewLike, Protocol):
    log_message: str
    log_type: LogType


class QtLogRenderer(QtWidgetRenderer[LogViewLike, QLabel]):
    def __init__(self, view: LogViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "log_message": self._refresh_log_message,
                "log_type": self._refresh_log_type,
            }
        )

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = plain_label()
            self._rendered_object.setWordWrap(True)
            self.refresh()

    @staticmethod
    def _refresh_log_message(_view: LogViewLike, rendered_object: QLabel, value: str) -> None:
        rendered_object.setVisible(value != "")
        rendered_object.setText(value)

    @staticmethod
    def _refresh_log_type(_view: LogViewLike, rendered_object: QLabel, value: LogType) -> None:
        if value == LogType.ERROR:
            rendered_object.setStyleSheet("QLabel { color : red; }")
        elif value == LogType.WARNING:
            rendered_object.setStyleSheet("QLabel { color : orange; }")
        else:
            rendered_object.setStyleSheet("")


class QtFormRenderer(QtWidgetRenderer[FormView, QWidget]):
    def render(self) -> None:
        if self._rendered_object is None:
            if isinstance(self._view, GroupFormView):
                self._rendered_object = QGroupBox()
            else:
                self._rendered_object = QWidget()
            layout = QFormLayout()
            self._rendered_object.setLayout(layout)
            for view in self._view.content_views:
                if isinstance(view, FormRowView) and isinstance(view.renderer, RendererContainer):
                    self.add_row(layout, view, view.renderer)
                # another view, e.g. a table, as wide as the form
                elif (widget := _widget_of(view)) is not None:
                    layout.addRow(widget)
                # else a view this backend doesn't register: left out
            log = self._view.log_view.renderer
            assert isinstance(log, QtWidgetRenderer)
            assert isinstance(log.qt_object, QWidget)
            layout.addRow(log.qt_object)
            self.refresh()

    @classmethod
    def add_row(
        cls, layout: QFormLayout, row: FormRowView, row_renderer: RendererContainer[View]
    ) -> None:
        """Add `row` to `layout`: its label, beside its field above its message."""
        field_container = QWidget()
        field_container_layout = QVBoxLayout(field_container)
        # avoid extra row spacing
        field_container_layout.setContentsMargins(0, 0, 0, 0)
        field_container_layout.addWidget(cls._get_field_object(row_renderer))
        field_container_layout.addWidget(cls._get_log_object(row_renderer))
        if isinstance(row, FormLabelRowView):
            layout.addRow(cls._get_label_object(row_renderer), field_container)
        else:
            layout.addRow(field_container)

    @staticmethod
    def _get_field_object(field_row_renderer: RendererContainer[View]) -> QWidget:
        field_renderer = field_row_renderer.get_renderer("field")
        assert isinstance(field_renderer, QtWidgetRenderer)
        assert isinstance(field_renderer.qt_object, QWidget)
        return field_renderer.qt_object

    @staticmethod
    def _get_log_object(field_row_renderer: RendererContainer[View]) -> QWidget:
        log_renderer = field_row_renderer.get_renderer("log")
        assert isinstance(log_renderer, QtLogRenderer)
        assert log_renderer.qt_object is not None
        return log_renderer.qt_object

    @staticmethod
    def _get_label_object(field_row_renderer: RendererContainer[View]) -> QFormLabel:
        label_renderer = field_row_renderer.get_renderer("label")
        assert isinstance(label_renderer, QtFormLabelRenderer)
        assert label_renderer.qt_object is not None
        return label_renderer.qt_object


class QtGroupFormRenderer(QtFormRenderer):
    def __init__(self, view: GroupFormView) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "title": self._refresh_title,
            }
        )

    @staticmethod
    def _refresh_title(_view: FormView, rendered_object: QWidget, value: str) -> None:
        assert isinstance(rendered_object, QGroupBox)
        rendered_object.setTitle(value)


#: widgets scrolling within themselves: as tall as the room they're given, rather than
#: their content, so they take a column's spare height, and a row's whole height; a
#: splitter too, its panes as tall as it
_SCROLLING_WIDGETS = (QTextBrowser, QScrollArea, QTreeWidget, QSplitter, QDataFilterTable)


#: the widgets of the form rows shown outside a form, by their rows' renderers: built once,
#: as a widget has one parent, and gone with the row
_ROW_WIDGETS: weakref.WeakKeyDictionary[RendererContainer[Any], QWidget] = (
    weakref.WeakKeyDictionary()
)


def _widget_of(view: View) -> QWidget | None:
    """Get the widget showing `view` in a layout; a form row's anywhere, as a form shows it.

    None when this backend doesn't render `view`.
    """
    renderer = view.renderer
    if isinstance(view, FormRowView) and isinstance(renderer, RendererContainer):
        widget = _ROW_WIDGETS.get(renderer)
        if widget is None:
            widget = QWidget()
            layout = QFormLayout(widget)
            # the layout holding the row already insets it
            layout.setContentsMargins(0, 0, 0, 0)
            QtFormRenderer.add_row(layout, view, renderer)
            _ROW_WIDGETS[renderer] = widget
        return widget
    if isinstance(renderer, QtWidgetRenderer) and isinstance(renderer.qt_object, QWidget):
        return renderer.qt_object
    return None


def _add_content_widget(layout: QVBoxLayout, view: View) -> None:
    """Add `view`'s widget to a column of content: a window's, or a page's."""
    widget = _widget_of(view)
    if widget is None:
        return
    if isinstance(view, DialogView):
        # a window of its own, over the column's window
        widget.setParent(layout.parentWidget(), widget.windowFlags())
    elif isinstance(view, (FormView, PageView)) and not isinstance(view, GroupFormView):
        # a plain form insets its rows with its own layout's margins, and a page its views;
        # a page holding a view that scrolls within itself takes the spare height, for it
        inner = widget.layout()
        expands = inner is not None and bool(inner.expandingDirections() & Qt.Orientation.Vertical)
        layout.addWidget(widget, 1 if expands else 0)
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
        # a document, a list or a tree scrolls within itself, and so does a row holding one:
        # it takes the column's spare height, ahead of the spacer under the views
        inner = widget.layout()
        expands = isinstance(widget, _SCROLLING_WIDGETS) or (
            isinstance(view, HorizontalView)
            and inner is not None
            and bool(inner.expandingDirections() & Qt.Orientation.Vertical)
        )
        layout.addLayout(inset, 1 if expands else 0)


#: macOS shows no title on a message box (Apple's guidelines): its bold text is the title there,
#: and its informative text the message
_TITLE_AS_TEXT = sys.platform == "darwin"


def _show_dialog_text(box: QMessageBox, title: str, text: str) -> None:
    """Show a dialog's title and text, the title as the bold text where it has no title."""
    title_as_text = _TITLE_AS_TEXT and title != ""
    box.setWindowTitle(title)  # macOS ignores it
    box.setText(title if title_as_text else text)
    box.setInformativeText(text if title_as_text else "")


class QtDialogRenderer(QtWidgetRenderer[DialogView, QMessageBox]):
    """A modal message box, shown without blocking: its answer reaches the view later."""

    def __init__(self, view: DialogView) -> None:
        super().__init__(view)
        self._accept_button: QPushButton | None = None
        self._reject_button: QPushButton | None = None
        #: the button that closed the box; None when it was closed from its window
        self._clicked: QAbstractButton | None = None
        self._refresh_dispatcher.update(
            {
                "is_visible": self._refresh_dialog_visible,
                "title": self._refresh_dialog_title,
                "text": self._refresh_dialog_text,
                "kind": self._refresh_kind,
                "accept_text": self._refresh_accept_text,
                "reject_text": self._refresh_reject_text,
            }
        )

    def render(self) -> None:
        if self._rendered_object is None:
            box = QMessageBox()
            box.setTextFormat(Qt.TextFormat.PlainText)
            box.setModal(True)
            release_when_hidden(box)
            self._accept_button = box.addButton("", QMessageBox.ButtonRole.AcceptRole)
            self._reject_button = box.addButton("", QMessageBox.ButtonRole.RejectRole)
            box.buttonClicked.connect(self._set_clicked)
            box.finished.connect(self._answer)
            self._rendered_object = box
            self.refresh()

    def _set_clicked(self, button: QAbstractButton) -> None:
        self._clicked = button

    def _answer(self, _result: int) -> None:
        if self._clicked is None:
            self._view.dismiss()
        elif self._clicked is self._accept_button:
            self._view.accept()
        else:
            self._view.reject()

    def _refresh_dialog_visible(
        self, _view: DialogView, rendered_object: QMessageBox, value: bool
    ) -> None:
        if value:
            self._clicked = None
        rendered_object.setVisible(value)

    @staticmethod
    def _refresh_dialog_title(view: DialogView, rendered_object: QMessageBox, value: str) -> None:
        # the view's field still holds the previous value: it's set once the refresh is over
        _show_dialog_text(rendered_object, value, view.text)

    @staticmethod
    def _refresh_dialog_text(view: DialogView, rendered_object: QMessageBox, value: str) -> None:
        _show_dialog_text(rendered_object, view.title, value)

    def _refresh_kind(
        self, _view: DialogView, rendered_object: QMessageBox, value: DialogKind
    ) -> None:
        assert self._accept_button is not None
        assert self._reject_button is not None
        is_confirm = value is DialogKind.CONFIRM
        self._reject_button.setVisible(is_confirm)
        # Escape clicks it: the hidden reject button would otherwise answer a message
        rendered_object.setEscapeButton(self._reject_button if is_confirm else self._accept_button)

    def _refresh_accept_text(
        self, _view: DialogView, _rendered_object: QMessageBox, value: str
    ) -> None:
        assert self._accept_button is not None
        self._accept_button.setText(value)

    def _refresh_reject_text(
        self, _view: DialogView, _rendered_object: QMessageBox, value: str
    ) -> None:
        assert self._reject_button is not None
        self._reject_button.setText(value)


class QtFormDialogRenderer(QtWidgetRenderer[OkCancelDialogView, QFormDialog]):
    """A modal dialog holding its form or other view, shown without blocking.

    Its answer reaches the view. OK is disabled while the view says so, e.g. while a check
    of the form fails; the view closes the dialog once it accepts the answer, so OK on a
    form refusing it leaves the dialog open.
    """

    def __init__(self, view: OkCancelDialogView) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "title": self._refresh_dialog_title,
                "text": self._refresh_text,
                "kind": self._refresh_kind,
                "accept_text": self._refresh_accept_text,
                "reject_text": self._refresh_reject_text,
                "is_accept_enabled": self._refresh_is_accept_enabled,
            }
        )

    def render(self) -> None:
        if self._rendered_object is None:
            dialog = QFormDialog()
            release_when_hidden(dialog)
            content = _widget_of(self._view.content)
            assert content is not None
            dialog.set_form(content)
            dialog.answered_ok.connect(self._view.accept)
            dialog.answered_cancel.connect(self._view.reject)
            dialog.dismissed.connect(self._view.dismiss)
            self._rendered_object = dialog
            self.refresh()

    @staticmethod
    def _refresh_dialog_title(
        _view: OkCancelDialogView, rendered_object: QFormDialog, value: str
    ) -> None:
        rendered_object.setWindowTitle(value)

    @staticmethod
    def _refresh_text(_view: OkCancelDialogView, rendered_object: QFormDialog, value: str) -> None:
        rendered_object.text.setText(value)
        rendered_object.text.setVisible(value != "")

    @staticmethod
    def _refresh_kind(
        _view: OkCancelDialogView, _rendered_object: QFormDialog, _value: Any
    ) -> None:
        pass  # always OK and Cancel: its view is confirmed or not

    @staticmethod
    def _refresh_accept_text(
        _view: OkCancelDialogView, rendered_object: QFormDialog, value: str
    ) -> None:
        rendered_object.ok_button.setText(value)

    @staticmethod
    def _refresh_reject_text(
        _view: OkCancelDialogView, rendered_object: QFormDialog, value: str
    ) -> None:
        rendered_object.cancel_button.setText(value)

    @staticmethod
    def _refresh_is_accept_enabled(
        _view: OkCancelDialogView, rendered_object: QFormDialog, value: bool
    ) -> None:
        rendered_object.ok_button.setEnabled(value)


class QtPageRenderer(QtWidgetRenderer[PageView, QWidget]):
    """A page's views in a column, laid out like the window's own."""

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QWidget()
            layout = QVBoxLayout(self._rendered_object)
            # the window's layout already insets the page
            layout.setContentsMargins(0, 0, 0, 0)
            for view in self._view.content_views:
                _add_content_widget(layout, view)
            layout.addStretch()
            self.refresh()


class QtHorizontalRenderer(QtWidgetRenderer[HorizontalView, QWidget]):
    """Views side by side, each as wide as its share of the row."""

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QWidget()
            layout = QHBoxLayout(self._rendered_object)
            # the column holding the row already insets it
            layout.setContentsMargins(0, 0, 0, 0)
            # a spacer with no share: it takes the free width only when no view has a
            # share, ahead of views (e.g. buttons) that would otherwise grow into it
            if self._view.align is Align.END:
                layout.addStretch(0)
            for view, stretch in self._view.stretched_views:
                widget = _widget_of(view)
                if widget is not None:
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
            self.refresh()


class QtVerticalRenderer(QtWidgetRenderer[VerticalView, QWidget]):
    """Views one above the other, at the top of the column."""

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QWidget()
            layout = QVBoxLayout(self._rendered_object)
            # the row holding the column already insets it
            layout.setContentsMargins(0, 0, 0, 0)
            for view in self._view.children_views:
                widget = _widget_of(view)
                if widget is not None:
                    layout.addWidget(widget)
            # height to spare, next to a taller view, goes below the views, not between them
            layout.addStretch()
            self.refresh()


class QtSplitterRenderer(QtWidgetRenderer[SplitterView, QComposeSplitter]):
    """A splitter: the panes in a row or a column, a handle between two the user drags."""

    def __init__(self, view: SplitterView) -> None:
        super().__init__(view)
        self._refresh_dispatcher["sizes"] = self._refresh_sizes
        # names a border on the web only
        self._refresh_dispatcher["border_text"] = lambda _view, _splitter, _value: None

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
            self._rendered_object.moved_by_user.connect(self._update_sizes)
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
            self._rendered_object.expanded_changed.connect(self._update_expanded)
            self._view.toggled.add_qt_signal(self._rendered_object.expanded_changed)
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


class QtSidebarRenderer(QtWidgetRenderer[SidebarView, QSidebar]):
    """A dock on the window's left: its title and a button retracting it, then its views."""

    def __init__(self, view: SidebarView) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "title": self._refresh_title,
                "toggle_text": self._refresh_toggle_text,
                "is_expanded": self._refresh_is_expanded,
            }
        )

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QSidebar()
            for view in self._view.children_views:
                _add_content_widget(self._rendered_object.content_layout, view)
            self._rendered_object.finish_content()
            # first, so the view's callbacks see the new state
            self._rendered_object.expanded_changed.connect(self._update_expanded)
            self._view.toggled.add_qt_signal(self._rendered_object.expanded_changed)
            self.refresh()

    @staticmethod
    def _refresh_title(_view: SidebarView, rendered_object: QSidebar, value: str) -> None:
        rendered_object.set_title(value)

    @staticmethod
    def _refresh_toggle_text(_view: SidebarView, rendered_object: QSidebar, value: str) -> None:
        rendered_object.toggle.setToolTip(plain_tool_tip(value))
        rendered_object.toggle.setAccessibleName(value)

    @staticmethod
    def _refresh_is_expanded(_view: SidebarView, rendered_object: QSidebar, value: bool) -> None:
        rendered_object.set_expanded(value)

    def _update_expanded(self, is_expanded: bool) -> None:
        with self.stop_refresh():
            self._view.is_expanded = is_expanded


class QtListRenderer(QtWidgetRenderer["ListView[Any]", QScrollArea]):
    """The records' views one above the other, added, moved and removed as they change.

    In a scroll area taking the column's spare height (see `_add_content_widget`): the
    window keeps its height however many records there are.
    """

    def __init__(self, view: ListView[Any]) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update({"item_views": self._refresh_item_views})

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


class QtTreeRenderer(QtWidgetRenderer[TreeView, QTreeWidget]):
    """A tree widget without a header, each item holding its node's path.

    Its first column shows a node's icon and label, its second the node's mark, hidden
    while no node has one. The user selects one item at most: a Ctrl+click deselecting
    it selects it again, as the view always keeps the node the user selected.
    """

    def __init__(self, view: TreeView) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "nodes": self._refresh_nodes,
                "expanded": self._refresh_expanded,
                "selected": self._refresh_selected,
                "done_text": functools.partial(self._refresh_mark_text, NodeMark.DONE),
                "warning_text": functools.partial(self._refresh_mark_text, NodeMark.WARNING),
                "error_text": functools.partial(self._refresh_mark_text, NodeMark.ERROR),
            }
        )

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QTreeWidget()
            self._rendered_object.setHeaderHidden(True)
            self._rendered_object.setColumnCount(2)
            header = self._rendered_object.header()
            assert header is not None
            # the marks as narrow as their icon, at the right
            header.setStretchLastSection(False)
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
            self._rendered_object.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
            self._rendered_object.itemSelectionChanged.connect(self._update_selected)
            self._rendered_object.itemExpanded.connect(
                lambda item: self._update_expanded(item, is_expanded=True)
            )
            self._rendered_object.itemCollapsed.connect(
                lambda item: self._update_expanded(item, is_expanded=False)
            )
            self.refresh()

    @classmethod
    def _refresh_nodes(
        cls, view: TreeView, rendered_object: QTreeWidget, value: list[TreeNode]
    ) -> None:
        rendered_object.clear()

        def add(
            parent: QTreeWidget | QTreeWidgetItem, nodes: Iterable[TreeNode], path: TreePath
        ) -> None:
            for node in nodes:
                item = QTreeWidgetItem(parent, [node.label])
                item.setData(0, Qt.ItemDataRole.UserRole, [*path, node.key])
                if node.icon is not None:
                    item.setIcon(0, QIcon(node.icon))
                font = item.font(0)
                font.setBold(node.is_bold)
                font.setUnderline(node.is_underlined)
                item.setFont(0, font)
                if node.mark is not None:
                    item.setIcon(1, mark_icon(node.mark))
                    item.setToolTip(1, plain_tool_tip(view.mark_text(node.mark)))
                add(item, node.children, (*path, node.key))

        add(rendered_object, value, ())
        rendered_object.setColumnHidden(1, all(node.mark is None for _, node in walk_tree(value)))
        # the view's, already kept to those still in the nodes
        cls._refresh_expanded(view, rendered_object, view.expanded)
        cls._refresh_selected(view, rendered_object, view.selected)

    @staticmethod
    def _refresh_expanded(
        _view: TreeView, rendered_object: QTreeWidget, value: list[TreePath]
    ) -> None:
        expanded = set(value)
        for path, item in _tree_items(rendered_object):
            item.setExpanded(path in expanded)

    @staticmethod
    def _refresh_selected(
        _view: TreeView, rendered_object: QTreeWidget, value: TreePath | None
    ) -> None:
        rendered_object.clearSelection()
        for path, item in _tree_items(rendered_object):
            if path == value:
                rendered_object.setCurrentItem(item)
                item.setSelected(True)

    @staticmethod
    def _refresh_mark_text(
        mark: NodeMark, view: TreeView, rendered_object: QTreeWidget, value: str
    ) -> None:
        for path, item in _tree_items(rendered_object):
            if view.node(path).mark is mark:
                item.setToolTip(1, plain_tool_tip(value))

    def _update_selected(self) -> None:
        assert self._rendered_object is not None
        selected = self._rendered_object.selectedItems()
        if len(selected) == 0:
            self.refresh_attribute("selected", self._view.selected)
            return
        path = _tree_path(selected[0])
        if path == self._view.selected:
            # Qt reports a change only: kept against a second `selection_changed`
            return  # pragma: no cover
        with self.stop_refresh():
            self._view.selected = path
        self._view.selection_changed.emit(path)

    def _update_expanded(self, item: QTreeWidgetItem, *, is_expanded: bool) -> None:
        path = _tree_path(item)
        with self.stop_refresh():
            self._view.expanded = self._view.expanded_with(path, is_expanded=is_expanded)
        self._view.toggled.emit(path, is_expanded)


def _tree_path(item: QTreeWidgetItem) -> TreePath:
    return tuple(item.data(0, Qt.ItemDataRole.UserRole))


def _tree_items(tree: QTreeWidget) -> list[tuple[TreePath, QTreeWidgetItem]]:
    """Get the tree's items with their nodes' paths, depth first."""
    items: list[tuple[TreePath, QTreeWidgetItem]] = []

    def add(item: QTreeWidgetItem) -> None:
        items.append((_tree_path(item), item))
        for index in range(item.childCount()):
            child = item.child(index)
            assert child is not None
            add(child)

    for index in range(tree.topLevelItemCount()):
        item = tree.topLevelItem(index)
        assert item is not None
        add(item)
    return items


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

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QWidget()
            layout = QVBoxLayout(self._rendered_object)
            for view in self._view.children_views:
                _add_content_widget(layout, view)
            # height to spare goes below the views, not between them
            layout.addStretch()
            self.refresh()

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
    """A tab widget: the tabs in a row, the current one's views under them."""

    def __init__(self, view: TabView) -> None:
        super().__init__(view)
        self._refresh_dispatcher["current_index"] = self._refresh_current_index

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QTabWidget()
            for tab in self._view.tabs:
                assert isinstance(tab.renderer, QtTabPageRenderer)
                assert tab.renderer.qt_object is not None
                self._rendered_object.addTab(tab.renderer.qt_object, tab.title)
                tab.renderer.refresh()  # its tab's state, now that it has one
            # once the tabs are in: adding the first one makes it current
            self._rendered_object.currentChanged.connect(self._update_current_index)
            self._view.current_changed.add_qt_signal(self._rendered_object.currentChanged)
            self.refresh()

    @staticmethod
    def _refresh_current_index(_view: TabView, rendered_object: QTabWidget, value: int) -> None:
        rendered_object.setCurrentIndex(value)

    def _update_current_index(self, index: int) -> None:
        with self.stop_refresh():
            self._view.current_index = index


class QtGridRenderer(QtWidgetRenderer[GridView, QWidget]):
    """Views in a grid's cells: equally wide columns, rows as tall as their views."""

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QWidget()
            layout = QGridLayout(self._rendered_object)
            # the column holding the grid already insets it
            layout.setContentsMargins(0, 0, 0, 0)
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


class QtRouterRenderer(QtWidgetRenderer[Router, QStackedWidget]):
    """The pages, stacked, and a toolbar of their actions that the window docks.

    Each page sits in a slot of its own: the stack shows and hides its slots, which
    leaves the page's own `is_visible` to the page.
    """

    def __init__(self, view: Router) -> None:
        super().__init__(view)
        #: the toolbar of the pages' actions, docked by the main window
        self.toolbar: QToolBar | None = None
        self._slots: dict[str, QWidget] = {}
        self._refresh_dispatcher.update({"current_route": self._refresh_current_route})

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QStackedWidget()
            self.toolbar = QToolBar()
            self.toolbar.setMovable(False)
            self.toolbar.toggleViewAction().setVisible(False)  # no way to close it
            for page in self._view.pages:
                assert isinstance(page.action.renderer, QtActionRenderer)
                page.action.renderer.set_parent_rendered_object(self.toolbar)
                page.action.renderer.render()
                assert page.action.renderer.qt_object is not None
                self.toolbar.addAction(page.action.renderer.qt_object)
                slot = QWidget()
                slot_layout = QVBoxLayout(slot)
                slot_layout.setContentsMargins(0, 0, 0, 0)
                assert isinstance(page.renderer, QtPageRenderer)
                assert page.renderer.qt_object is not None
                slot_layout.addWidget(page.renderer.qt_object)
                self._slots[page.route] = slot
                self._rendered_object.addWidget(slot)
            self.refresh()

    def _refresh_current_route(
        self, _view: Router, rendered_object: QStackedWidget, value: str
    ) -> None:
        slot = self._slots.get(value)
        if slot is not None:
            rendered_object.setCurrentWidget(slot)


class QtMainRenderer(QtWidgetRenderer[MainView, QMainWindow], MainRenderer[MainView, QMainWindow]):
    def __init__(self, view: MainView, window: QMainWindow | None = None) -> None:
        super().__init__(view)
        #: another main view's window to show this one in, in place of its parts, e.g.
        #: the previous code's on a reload: the window keeps its place and size
        self._window = window
        self._refresh_dispatcher.update(
            {
                "title": self._refresh_title,
                "state_filepath": self._refresh_state_filepath,
                "minimum_width": self._refresh_minimum_width,
                "minimum_height": self._refresh_minimum_height,
            }
        )

    def render(self) -> None:
        if self._rendered_object is None:
            if self._window is None:
                self._rendered_object = QMainWindow()
            else:
                self._rendered_object = self._window
                self._clear_window(self._window)
            self._rendered_object.setMinimumSize(
                self._view.minimum_width, self._view.minimum_height
            )
            if self._view.app_icon is not None:
                self._rendered_object.setWindowIcon(QIcon(str(self._view.app_icon)))
            self._add_child_widgets(self._view, self._rendered_object)
            self.refresh()

    def open_file(self) -> Path | None:
        """Return an existing file selected by the user."""
        assert self._rendered_object is not None
        filepath_str, selected_filter = QFileDialog.getOpenFileName(
            self._rendered_object, "Open File", "", self._build_extensions()
        )
        return self._build_filepath(filepath_str, selected_filter)

    def save_file(self) -> Path | None:
        assert self._rendered_object is not None
        filepath_str, selected_filter = QFileDialog.getSaveFileName(
            self._rendered_object, "Save File", "", self._build_extensions()
        )
        return self._build_filepath(filepath_str, selected_filter)

    def close(self) -> None:
        assert self._rendered_object is not None
        self._rendered_object.close()

    def _build_filepath(self, filepath_str: str, selected_filter: str) -> Path | None:
        if filepath_str == "":
            return None
        name_extension = selected_filter.split("(", maxsplit=1)[0].strip()
        filepath = Path(filepath_str)
        extensions = self._view.file_view.extensions.get(name_extension)
        if extensions is not None and all(
            not self._has_extension(filepath, extension) for extension in extensions
        ):
            filepath = Path(filepath_str + extensions[0])
        return filepath

    @staticmethod
    def _has_extension(filepath: Path, extension: str) -> bool:
        parts = [f".{e}" for e in extension.split(".") if e != ""]
        if len(parts) > 0:
            return filepath.suffixes[-len(parts) :] == parts
        return False

    def _build_extensions(self) -> str:
        return _file_filters(self._view.file_view.extensions)

    @staticmethod
    def _clear_window(window: QMainWindow) -> None:
        """Remove what another main view set on `window`: its bars, menus, sidebar and icon.

        Its content goes once replaced (`setCentralWidget`).
        """
        window.setWindowIcon(QIcon())  # set again only if this main view has one
        # the previous bars are deleted
        window.setMenuBar(QMenuBar())
        window.setStatusBar(None)  # type: ignore[arg-type]  # Qt takes none: it removes the bar
        for child in window.findChildren(QWidget, "", Qt.FindChildOption.FindDirectChildrenOnly):
            if isinstance(child, QToolBar):
                window.removeToolBar(child)
            elif isinstance(child, QDockWidget):
                window.removeDockWidget(child)
            elif not isinstance(child, QMenu):
                continue
            child.deleteLater()

    @staticmethod
    def _add_child_widgets(view: MainView, rendered_object: QMainWindow) -> None:
        central_widget = QWidget()
        central_layout = QVBoxLayout()
        central_widget.setLayout(central_layout)
        for child_view in view.children_views:
            if QtMainRenderer._add_window_part(child_view, rendered_object):
                continue
            if isinstance(child_view.renderer, QtRouterRenderer):
                toolbar = child_view.renderer.toolbar
                stack = child_view.renderer.qt_object
                assert toolbar is not None
                assert stack is not None
                rendered_object.addToolBar(toolbar)
                central_layout.addWidget(stack)
            else:
                _add_content_widget(central_layout, child_view)
        central_layout.addStretch()
        central_layout.update()
        rendered_object.setCentralWidget(central_widget)

    @staticmethod
    def _add_window_part(child_view: View, rendered_object: QMainWindow) -> bool:
        """Add a part of the window around the content, if `child_view` is one.

        Its menus, status bar, toolbars and sidebar; return whether `child_view` is one.
        """
        renderer = child_view.renderer
        if isinstance(renderer, QtMenuRenderer):
            renderer.set_parent_rendered_object(rendered_object)
            renderer.render()
            assert renderer.qt_object is not None
            rendered_object.menuBar().addMenu(renderer.qt_object)
        elif isinstance(renderer, QtStatusBarRenderer):
            assert isinstance(renderer.qt_object, QStatusBar)
            rendered_object.setStatusBar(renderer.qt_object)
        elif isinstance(renderer, QtToolBarRenderer):
            assert renderer.qt_object is not None
            rendered_object.addToolBar(renderer.qt_object)
        elif isinstance(renderer, QtSidebarRenderer):
            assert renderer.qt_object is not None
            rendered_object.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, renderer.qt_object)
        else:
            return False
        return True

    @staticmethod
    def _refresh_title(_view: MainView, rendered_object: QMainWindow, value: str) -> None:
        rendered_object.setWindowTitle(value)

    @staticmethod
    def _refresh_state_filepath(
        _view: MainView, rendered_object: QMainWindow, value: Path
    ) -> None: ...

    @staticmethod
    def _refresh_minimum_width(_view: MainView, rendered_object: QMainWindow, value: int) -> None:
        rendered_object.setMinimumWidth(value)

    @staticmethod
    def _refresh_minimum_height(_view: MainView, rendered_object: QMainWindow, value: int) -> None:
        rendered_object.setMinimumHeight(value)


class QtStatusBarRenderer(QtWidgetRenderer[StatusBar, QStatusBar]):
    def __init__(self, view: StatusBar) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "message": self._refresh_message,
            }
        )

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QStatusBar()
            self._view.message_changed.add_qt_signal(self._rendered_object.messageChanged)
            self.refresh()

    @staticmethod
    def _refresh_message(_view: StatusBar, rendered_object: QStatusBar, message: str) -> None:
        rendered_object.showMessage(message)


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

    def render(self) -> None:
        if self._rendered_object is None and self._parent_rendered_object:
            self._rendered_object = QAction(self._parent_rendered_object)
            self._view.triggered.add_qt_signal(self._rendered_object.triggered)
            self.refresh()

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


#: renderer keys of the Qt backend, looked up by `composeui.core.registry.create_renderer`
RENDERERS: dict[str, Callable[[Any], Renderer[Any, Any]]] = {
    "action": QtActionRenderer,
    "button": QtButtonRenderer,
    "chart": QtChartRenderer,
    "map": _map_renderer,
    "checkbox": QtCheckBoxRenderer,
    "combobox": QtComboBoxRenderer,
    "source_table": QtSourceTableRenderer,
    "date_input": QtDateInputRenderer,
    "file_path_input": QtFilePathInputRenderer,
    "dialog": QtDialogRenderer,
    "expander": QtExpanderRenderer,
    "float_input": QtFloatInputRenderer,
    "int_input": QtIntInputRenderer,
    "form": QtFormRenderer,
    "content_dialog": QtFormDialogRenderer,
    "form_dialog": QtFormDialogRenderer,
    "form_label": QtFormLabelRenderer,
    "grid": QtGridRenderer,
    "group_form": QtGroupFormRenderer,
    "horizontal": QtHorizontalRenderer,
    "input": QtInputRenderer,
    "label": QtLabelRenderer,
    "list": QtListRenderer,
    "log": QtLogRenderer,
    "main": QtMainRenderer,
    "markdown": QtMarkdownRenderer,
    "menu": QtMenuRenderer,
    "metric": QtMetricRenderer,
    "page": QtPageRenderer,
    "progress_bar": QtProgressBarRenderer,
    "slider": QtSliderRenderer,
    "radio_group": QtRadioGroupRenderer,
    "router": QtRouterRenderer,
    "separator": QtSeparatorRenderer,
    "sidebar": QtSidebarRenderer,
    "splitter": QtSplitterRenderer,
    "status_bar": QtStatusBarRenderer,
    "table": QtTableRenderer,
    "tab_page": QtTabPageRenderer,
    "tabs": QtTabsRenderer,
    "toolbar": QtToolBarRenderer,
    "tree": QtTreeRenderer,
    "vertical": QtVerticalRenderer,
}

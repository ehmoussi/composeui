from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Generic, TypeVar

from qtpy.QtCore import QObject, Qt
from qtpy.QtCore import Signal as QtSignal
from qtpy.QtGui import QAction, QDoubleValidator, QIcon, QKeySequence
from qtpy.QtWidgets import (
    QAbstractButton,
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QStatusBar,
    QStyle,
    QToolBar,
    QVBoxLayout,
    QWidget,
)
from typing_extensions import Protocol

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
    DialogKind,
    DialogView,
    FormLabelRowView,
    FormRowView,
    FormView,
    GroupFormView,
    HorizontalView,
    LogType,
    MainView,
    Menu,
    PageView,
    Router,
    SelectionMode,
    SeparatorAction,
    StatusBar,
    ToolBar,
    VerticalView,
    View,
    replace_cell,
)
from composeui.qtcore.widgets.qiconpath import QIconPath
from composeui.qtcore.widgets.qradiogroup import QRadioGroup
from composeui.qtcore.widgets.qtexttable import QTextTableView
from composeui.qtcore.widgets.qvaluecombobox import QValueComboBox

if TYPE_CHECKING:
    from collections.abc import Callable

    from composeui.core.signal import Signal, SignalNoArgs

TView = TypeVar("TView", bound=ViewLike)
TWidget = TypeVar("TWidget", bound="QWidget | QAction")


class NoQtRendererObjectError(Exception):
    def __init__(self) -> None:
        super().__init__("Renderer should be inherited by QtRenderer")


class NotQWidgetError(Exception):
    def __init__(self) -> None:
        super().__init__("Renderer object should be of type QWidget")


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
        """Refresh the framework view object using the view state."""
        if self._rendered_object is None:
            raise NoRenderedObjectError
        self._rendered_object.blockSignals(True)  # noqa: FBT003
        super().refresh_attribute(attr_name, value)
        self._rendered_object.blockSignals(False)  # noqa: FBT003

    def update_state(self) -> None:
        """Update the state of the view using framework view object."""
        if self._rendered_object is None:
            raise NoRenderedObjectError
        self._update_state(self._view, self._rendered_object)
        self._view.is_visible = self._rendered_object.isVisible()
        self._view.is_enabled = self._rendered_object.isEnabled()

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
            if isinstance(renderer_object, QWidget):  # always, for a field renderer
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

    @staticmethod
    def _update_state(view: InputViewLike, rendered_object: QLineEdit) -> None:
        view.text = rendered_object.text()
        view.placeholder = rendered_object.placeholderText()

    def _update_text(self, text: str) -> None:
        with self.stop_refresh():
            self._view.text = text


class FloatInputViewLike(_InputViewLike, Protocol):
    value: float | None
    minimum: float | None
    maximum: float | None
    decimals: int | None


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
            self._view.editing_finished.add_qt_signal(self._rendered_object.editingFinished)
            self._view.text_changed.add_qt_signal(self._rendered_object.textChanged)
            self._view.text_edited.add_qt_signal(self._rendered_object.textEdited)
            self.refresh()

    @staticmethod
    def _refresh_value(
        _view: FloatInputViewLike, rendered_object: QLineEdit, value: float | None
    ) -> None:
        rendered_object.setText(str(value) if value is not None else "")

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
        _view: FloatInputViewLike, rendered_object: QLineEdit, value: int | None
    ) -> None:
        validator = rendered_object.validator()
        assert isinstance(validator, QDoubleValidator)
        validator.setDecimals(-1 if value is None else value)

    @staticmethod
    def _update_state(view: FloatInputViewLike, rendered_object: QLineEdit) -> None:
        text = rendered_object.text()
        if text != "":
            view.value = float(text)
        else:
            view.value = None
        view.placeholder = rendered_object.placeholderText()
        validator = rendered_object.validator()
        assert isinstance(validator, QDoubleValidator)
        bottom = validator.bottom()
        view.minimum = bottom if bottom != float("-inf") else None
        top = validator.top()
        view.maximum = top if top != float("inf") else None
        decimals = validator.decimals()
        view.decimals = decimals if decimals != -1 else None

    def _update_text(self, text: str) -> None:
        with self.stop_refresh():
            if text != "":
                self._view.value = float(text)
            else:
                self._view.value = None


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
            self._rendered_object = QLabel()
            self.refresh()

    @staticmethod
    def _refresh_text(_view: LabelViewLike, rendered_object: QLabel, value: str) -> None:
        rendered_object.setText(value)

    @staticmethod
    def _update_state(view: LabelViewLike, rendered_object: QLabel) -> None:
        view.text = rendered_object.text()


class QtFormLabelRenderer(QtWidgetRenderer[FormLabelRowView, QLabel]):
    def __init__(self, view: FormLabelRowView) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "label": self._refresh_text,
            }
        )

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QLabel()
            self.refresh()

    @staticmethod
    def _refresh_text(_view: FormLabelRowView, rendered_object: QLabel, value: str) -> None:
        rendered_object.setText(value)

    @staticmethod
    def _update_state(view: FormLabelRowView, rendered_object: QLabel) -> None:
        view.label = rendered_object.text()


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

    @staticmethod
    def _update_state(view: CheckBoxViewLike, rendered_object: QCheckBox) -> None:
        view.text = rendered_object.text()
        view.is_checked = rendered_object.isChecked()

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

    @staticmethod
    def _update_state(view: ButtonViewLike, rendered_object: QPushButton) -> None:
        view.text = rendered_object.text()

    def _emit_clicked(self) -> None:
        self._view.clicked.emit()


class TableViewLike(ViewLike, Protocol):
    headers: list[str]
    selection_mode: SelectionMode
    rows: list[list[str]]
    selected_rows: list[int]
    selection_changed: Signal[list[int]]
    editable_columns: list[int]
    cell_edited: Signal[int, int, str]

    def emit_cell_edited(self, row: int, column: int, text: str) -> None: ...


class QtTableRenderer(QtWidgetRenderer[TableViewLike, QTextTableView]):
    def __init__(self, view: TableViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "headers": self._refresh_headers,
                "selection_mode": self._refresh_selection_mode,
                "rows": self._refresh_rows,
                "selected_rows": self._refresh_selected_rows,
                "editable_columns": self._refresh_editable_columns,
            }
        )

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QTextTableView()
            self._rendered_object.selected_rows_changed.connect(self._update_selected_rows)
            self._rendered_object.cell_edited.connect(self._update_cell)
            self.refresh()

    @staticmethod
    def _refresh_headers(
        view: TableViewLike, rendered_object: QTextTableView, value: list[str]
    ) -> None:
        # resetting the table drops its selection: reapply it
        rendered_object.set_table(value, view.rows)
        rendered_object.set_selected_rows(view.selected_rows)

    @staticmethod
    def _refresh_selection_mode(
        _view: TableViewLike, rendered_object: QTextTableView, value: SelectionMode
    ) -> None:
        rendered_object.set_multiple_selection(is_multiple=value is SelectionMode.MULTIPLE)

    @staticmethod
    def _refresh_rows(
        view: TableViewLike, rendered_object: QTextTableView, value: list[list[str]]
    ) -> None:
        rendered_object.set_table(view.headers, value)

    @staticmethod
    def _refresh_selected_rows(
        _view: TableViewLike, rendered_object: QTextTableView, value: list[int]
    ) -> None:
        rendered_object.set_selected_rows(value)

    @staticmethod
    def _refresh_editable_columns(
        _view: TableViewLike, rendered_object: QTextTableView, value: list[int]
    ) -> None:
        rendered_object.set_editable_columns(value)

    @staticmethod
    def _update_state(view: TableViewLike, rendered_object: QTextTableView) -> None:
        view.selected_rows = rendered_object.selected_rows()

    def _update_selected_rows(self, rows: list[int]) -> None:
        with self.stop_refresh():
            self._view.selected_rows = rows
        self._view.selection_changed.emit(rows)

    def _update_cell(self, row: int, column: int, text: str) -> None:
        rows = self._view.rows
        self._view.emit_cell_edited(row, column, text)
        if self._view.rows is rows:
            with self.stop_refresh():
                self._view.rows = replace_cell(rows, row, column, text)
        elif self._view.rows == rows:
            # the app put the same rows back, which reached nothing: show them again
            self.refresh()


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

    @staticmethod
    def _update_state(view: ValuesViewLike[TValue], rendered_object: QRadioGroup) -> None:
        view.value = rendered_object.value()

    def _update_value(self, value: TValue | None) -> None:
        with self.stop_refresh():
            self._view.value = value


class QtComboboxRenderer(
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

    @staticmethod
    def _update_state(
        view: ValuesViewLike[TValue], rendered_object: QValueComboBox[TValue]
    ) -> None:
        view.value = rendered_object.current_value()

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
            self._rendered_object = QLabel()
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

    @staticmethod
    def _update_state(view: LogViewLike, rendered_object: QLabel) -> None:
        view.log_message = rendered_object.text()


class QtFormRenderer(QtWidgetRenderer[FormView, QWidget]):
    def render(self) -> None:
        if self._rendered_object is None:
            if isinstance(self._view, GroupFormView):
                self._rendered_object = QGroupBox()
            else:
                self._rendered_object = QWidget()
            layout = QFormLayout()
            self._rendered_object.setLayout(layout)
            for field_row in self._view.field_rows:
                if isinstance(field_row, FormRowView) and isinstance(
                    field_row.renderer, RendererContainer
                ):
                    field_container = QWidget()
                    field_container_layout = QVBoxLayout(field_container)
                    # avoid extra row spacing
                    field_container_layout.setContentsMargins(0, 0, 0, 0)
                    field_object = self._get_field_object(field_row.renderer)
                    field_container_layout.addWidget(field_object)
                    log_object = self._get_log_object(field_row.renderer)
                    field_container_layout.addWidget(log_object)
                    if isinstance(field_row, FormLabelRowView):
                        label_object = self._get_label_object(field_row.renderer)
                        layout.addRow(label_object, field_container)
                    else:
                        layout.addRow(field_container)
                elif (
                    isinstance(field_row.renderer, QtWidgetRenderer)
                    and field_row.renderer.qt_object is not None
                ):
                    layout.addRow(field_row.renderer.qt_object)
            if (
                isinstance(self._view.log_view.renderer, QtWidgetRenderer)
                and self._view.log_view.renderer.qt_object is not None
            ):
                layout.addRow(self._view.log_view.renderer.qt_object)
            self.refresh()

    def _get_field_object(self, field_row_renderer: RendererContainer[View]) -> QWidget:
        try:
            field_renderer = field_row_renderer.get_renderer("field")
        except KeyError as e:
            msg = f"The field renderer is missing in the row of the form {self._view}"
            raise ValueError(msg) from e
        if not isinstance(field_renderer, QtWidgetRenderer):
            raise NoQtRendererObjectError
        field_object = field_renderer.qt_object
        if not isinstance(field_object, QWidget):
            raise NotQWidgetError
        return field_object

    def _get_log_object(self, field_row_renderer: RendererContainer[View]) -> QWidget:
        try:
            log_renderer = field_row_renderer.get_renderer("log")
        except KeyError as e:
            msg = f"The log renderer is missing in the row of the form {self._view}"
            raise ValueError(msg) from e
        if not isinstance(log_renderer, QtLogRenderer):
            raise NoQtRendererObjectError
        log_object = log_renderer.qt_object
        if not isinstance(log_object, QWidget):
            raise NotQWidgetError
        return log_object

    def _get_label_object(self, field_row_renderer: RendererContainer[View]) -> QLabel:
        try:
            label_renderer = field_row_renderer.get_renderer("label")
        except KeyError as e:
            msg = f"The label renderer is missing in the row of the form {self._view}"
            raise ValueError(msg) from e
        if not isinstance(label_renderer, QtFormLabelRenderer):
            raise NoQtRendererObjectError
        label_object = label_renderer.qt_object
        if label_object is None:
            raise NoRenderedObjectError
        return label_object

    @staticmethod
    def _update_state(view: FormView, rendered_object: QWidget) -> None:
        if isinstance(rendered_object, QGroupBox) and isinstance(view, GroupFormView):
            view.title = rendered_object.title()


class QtGroupFormRenderer(QtFormRenderer):
    def __init__(self, view: GroupFormView) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "title": self._refresh_title,
            }
        )

    @staticmethod
    def _refresh_title(view: FormView, rendered_object: QWidget, value: str) -> None:
        if isinstance(rendered_object, QGroupBox) and isinstance(view, GroupFormView):
            rendered_object.setTitle(value)


def _add_content_widget(layout: QVBoxLayout, view: View) -> None:
    """Add `view`'s widget to a column of content: a window's, or a page's."""
    if not isinstance(view.renderer, QtWidgetRenderer):
        return
    widget = view.renderer.qt_object
    if not isinstance(widget, QWidget):
        return
    if isinstance(view, DialogView):
        # a window of its own, over the column's window
        widget.setParent(layout.parentWidget(), widget.windowFlags())
    elif isinstance(view, (FormView, PageView)) and not isinstance(view, GroupFormView):
        # a plain form insets its rows with its own layout's margins, and a page its views
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
                "text": self._refresh_text,
                "kind": self._refresh_kind,
                "accept_text": self._refresh_accept_text,
                "reject_text": self._refresh_reject_text,
            }
        )

    def render(self) -> None:
        if self._rendered_object is None:
            box = QMessageBox()
            box.setModal(True)
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
    def _refresh_dialog_title(_view: DialogView, rendered_object: QMessageBox, value: str) -> None:
        rendered_object.setWindowTitle(value)

    @staticmethod
    def _refresh_text(_view: DialogView, rendered_object: QMessageBox, value: str) -> None:
        rendered_object.setText(value)

    def _refresh_kind(
        self, _view: DialogView, rendered_object: QMessageBox, value: DialogKind
    ) -> None:
        if self._accept_button is None or self._reject_button is None:
            return
        is_confirm = value is DialogKind.CONFIRM
        self._reject_button.setVisible(is_confirm)
        # Escape clicks it: the hidden reject button would otherwise answer a message
        rendered_object.setEscapeButton(self._reject_button if is_confirm else self._accept_button)

    def _refresh_accept_text(
        self, _view: DialogView, _rendered_object: QMessageBox, value: str
    ) -> None:
        if self._accept_button is not None:
            self._accept_button.setText(value)

    def _refresh_reject_text(
        self, _view: DialogView, _rendered_object: QMessageBox, value: str
    ) -> None:
        if self._reject_button is not None:
            self._reject_button.setText(value)

    @staticmethod
    def _update_state(view: DialogView, rendered_object: QMessageBox) -> None:
        view.title = rendered_object.windowTitle()
        view.text = rendered_object.text()


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

    @staticmethod
    def _update_state(view: PageView, rendered_object: QWidget) -> None:
        pass  # a page has no user-editable state of its own


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
                if isinstance(view.renderer, QtWidgetRenderer) and isinstance(
                    view.renderer.qt_object, QWidget
                ):
                    # at the top: Qt centres a view shorter than the row (e.g. a table
                    # as tall as its rows, beside a taller one) as the window grows
                    layout.addWidget(view.renderer.qt_object, stretch, Qt.AlignmentFlag.AlignTop)
            if self._view.align is Align.START:
                layout.addStretch(0)
            self.refresh()

    @staticmethod
    def _update_state(view: HorizontalView, rendered_object: QWidget) -> None:
        pass  # a row has no user-editable state of its own


class QtVerticalRenderer(QtWidgetRenderer[VerticalView, QWidget]):
    """Views one above the other, at the top of the column."""

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QWidget()
            layout = QVBoxLayout(self._rendered_object)
            # the row holding the column already insets it
            layout.setContentsMargins(0, 0, 0, 0)
            for view in self._view.children_views:
                if isinstance(view.renderer, QtWidgetRenderer) and isinstance(
                    view.renderer.qt_object, QWidget
                ):
                    layout.addWidget(view.renderer.qt_object)
            # height to spare, next to a taller view, goes below the views, not between them
            layout.addStretch()
            self.refresh()

    @staticmethod
    def _update_state(view: VerticalView, rendered_object: QWidget) -> None:
        pass  # a column has no user-editable state of its own


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
                if not isinstance(page.action.renderer, QtActionRenderer):
                    continue
                page.action.renderer.set_parent_rendered_object(self.toolbar)
                page.action.renderer.render()
                action = page.action.renderer.qt_object
                if action is not None:
                    self.toolbar.addAction(action)
                slot = QWidget()
                slot_layout = QVBoxLayout(slot)
                slot_layout.setContentsMargins(0, 0, 0, 0)
                if isinstance(page.renderer, QtPageRenderer) and page.renderer.qt_object:
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

    @staticmethod
    def _update_state(view: Router, rendered_object: QStackedWidget) -> None:
        pass  # navigation goes through the pages' actions, never the stack itself


class QtMainRenderer(QtWidgetRenderer[MainView, QMainWindow], MainRenderer[MainView, QMainWindow]):
    def __init__(self, view: MainView) -> None:
        super().__init__(view)
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
            self._rendered_object = QMainWindow()
            self._rendered_object.setMinimumSize(
                self._view.minimum_width, self._view.minimum_height
            )
            self._add_child_widgets(self._view, self._rendered_object)
            self.refresh()

    def open_file(self) -> Path | None:
        """Return an existing file selected by the user."""
        if self._rendered_object is None:
            raise NoQtRendererObjectError
        filepath_str, selected_filter = QFileDialog.getOpenFileName(
            self._rendered_object, "Open File", "", self._build_extensions()
        )
        return self._build_filepath(filepath_str, selected_filter)

    def save_file(self) -> Path | None:
        if self._rendered_object is None:
            raise NoQtRendererObjectError
        filepath_str, selected_filter = QFileDialog.getSaveFileName(
            self._rendered_object, "Save File", "", self._build_extensions()
        )
        return self._build_filepath(filepath_str, selected_filter)

    def close(self) -> None:
        if self._rendered_object is None:
            raise NoQtRendererObjectError
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
        extensions: list[str] = []
        for name, name_extensions in self._view.file_view.extensions.items():
            extensions.append(f"{name} ({' '.join(f'*{n}' for n in name_extensions)})")
        return ";;".join(extensions)

    @staticmethod
    def _add_child_widgets(view: MainView, rendered_object: QMainWindow) -> None:
        central_widget = QWidget()
        central_layout = QVBoxLayout()
        central_widget.setLayout(central_layout)
        for child_view in view.children_views:
            if isinstance(child_view.renderer, QtMenuRenderer):
                child_view.renderer.set_parent_rendered_object(rendered_object)
                child_view.renderer.render()
                menu_obj = child_view.renderer.qt_object
                if menu_obj is not None:
                    rendered_object.menuBar().addMenu(menu_obj)
            elif isinstance(child_view.renderer, QtStatusBarRenderer):
                status_bar_obj = child_view.renderer.qt_object
                if isinstance(status_bar_obj, QStatusBar):
                    rendered_object.setStatusBar(status_bar_obj)
            elif isinstance(child_view.renderer, QtToolBarRenderer):
                toolbar_obj = child_view.renderer.qt_object
                if toolbar_obj is not None:
                    rendered_object.addToolBar(toolbar_obj)
            elif isinstance(child_view.renderer, QtRouterRenderer):
                toolbar = child_view.renderer.toolbar
                stack = child_view.renderer.qt_object
                if toolbar is not None and stack is not None:
                    rendered_object.addToolBar(toolbar)
                    central_layout.addWidget(stack)
            else:
                _add_content_widget(central_layout, child_view)
        central_layout.addStretch()
        central_layout.update()
        rendered_object.setCentralWidget(central_widget)

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

    @staticmethod
    def _update_state(view: MainView, rendered_object: QMainWindow) -> None:
        view.title = rendered_object.windowTitle()
        view.minimum_width = rendered_object.minimumWidth()
        view.minimum_height = rendered_object.minimumHeight()


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

    @staticmethod
    def _update_state(view: StatusBar, rendered_object: QStatusBar) -> None:
        view.message = rendered_object.currentMessage()


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

    def set_parent_rendered_object(self, parent: QWidget) -> None:
        self._parent_rendered_object = parent

    def render(self) -> None:
        if self._rendered_object is None and self._parent_rendered_object:
            self._rendered_object = QAction(self._parent_rendered_object)
            self._view.triggered.add_qt_signal(self._rendered_object.triggered)
            self.refresh()

    @staticmethod
    def _update_state(view: ActionView, rendered_object: QAction) -> None:
        view.text = rendered_object.text()
        icon = rendered_object.icon()
        if isinstance(icon, QIconPath):
            view.icon = icon.get_path()
        else:
            view.icon = None
        view.data = rendered_object.data()
        shortcut = rendered_object.shortcut().toString()
        view.shortcut = None if shortcut == "" else shortcut
        view.is_checkable = rendered_object.isCheckable()
        view.is_checked = rendered_object.isChecked()

    @staticmethod
    def _refresh_text(_view: ActionView, rendered_object: QAction, text: str) -> None:
        rendered_object.setText(text)

    @staticmethod
    def _refresh_icon(_view: ActionView, rendered_object: QAction, icon: str | None) -> None:
        if icon is None:
            rendered_object.setIcon(QIcon())
        else:
            icon_obj = QIconPath(icon)
            rendered_object.setIcon(icon_obj)

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

    @staticmethod
    def _update_state(view: SeparatorAction, rendered_object: QAction) -> None: ...


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
                    if action is None:
                        msg = f"{child_view} don't have a QAction object rendered"
                        raise ValueError(msg)
                    self._rendered_object.addAction(action)
            self.refresh()

    @staticmethod
    def _update_state(view: Menu, rendered_object: QMenu) -> None:
        view.title = rendered_object.title()

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
                    if action is not None:
                        self._rendered_object.addAction(action)
            self.refresh()

    @staticmethod
    def _update_state(view: ToolBar, rendered_object: QToolBar) -> None:
        view.title = rendered_object.windowTitle()

    @staticmethod
    def _refresh_title(_view: ToolBar, rendered_object: QToolBar, title: str) -> None:
        rendered_object.setWindowTitle(title)


#: renderer keys of the Qt backend, looked up by `composeui.core.registry.create_renderer`
RENDERERS: dict[str, Callable[[Any], Renderer[Any, Any]]] = {
    "action": QtActionRenderer,
    "button": QtButtonRenderer,
    "checkbox": QtCheckBoxRenderer,
    "combobox": QtComboboxRenderer,
    "dialog": QtDialogRenderer,
    "float_input": QtFloatInputRenderer,
    "form": QtFormRenderer,
    "form_label": QtFormLabelRenderer,
    "group_form": QtGroupFormRenderer,
    "horizontal": QtHorizontalRenderer,
    "input": QtInputRenderer,
    "label": QtLabelRenderer,
    "log": QtLogRenderer,
    "main": QtMainRenderer,
    "menu": QtMenuRenderer,
    "page": QtPageRenderer,
    "radio_group": QtRadioGroupRenderer,
    "router": QtRouterRenderer,
    "separator": QtSeparatorRenderer,
    "status_bar": QtStatusBarRenderer,
    "table": QtTableRenderer,
    "toolbar": QtToolBarRenderer,
    "vertical": QtVerticalRenderer,
}

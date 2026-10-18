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
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QStatusBar,
    QStyle,
    QTextBrowser,
    QToolBar,
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
    PageView,
    PickFileAction,
    ProgressBarView,
    Router,
    SelectionMode,
    SeparatorAction,
    SidebarView,
    SliderMixin,
    StatusBar,
    ToolBar,
    VerticalView,
    View,
    replace_cell,
)
from composeui.qtcore.widgets.qchart import QChart
from composeui.qtcore.widgets.qexpander import QExpander
from composeui.qtcore.widgets.qfiltertable import QFilterTable
from composeui.qtcore.widgets.qformlabel import QFormLabel
from composeui.qtcore.widgets.qiconpath import QIconPath
from composeui.qtcore.widgets.qmetric import QMetric
from composeui.qtcore.widgets.qradiogroup import QRadioGroup
from composeui.qtcore.widgets.qsidebar import QSidebar
from composeui.qtcore.widgets.qvaluecombobox import QValueComboBox
from composeui.qtcore.widgets.qvalueslider import QValueSlider

if TYPE_CHECKING:
    from collections.abc import Callable

    from composeui.core.signal import Signal, SignalNoArgs
    from composeui.core.view import Series

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
            self._view.text_edited.add_qt_signal(self._line_edit(self._rendered_object).textEdited)
            self.refresh()

    @staticmethod
    def _line_edit(rendered_object: QSpinBox) -> QLineEdit:
        # `QAbstractSpinBox.lineEdit` is protected
        line_edit = rendered_object.findChild(QLineEdit)
        assert line_edit is not None
        return line_edit

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
        QtIntInputRenderer._line_edit(rendered_object).setPlaceholderText(value)

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

    @staticmethod
    def _update_state(view: IntInputViewLike, rendered_object: QSpinBox) -> None:
        view.value = rendered_object.value() if rendered_object.cleanText() != "" else None
        view.placeholder = QtIntInputRenderer._line_edit(rendered_object).placeholderText()
        minimum, maximum = rendered_object.minimum(), rendered_object.maximum()
        view.minimum = minimum if minimum != _INT_MINIMUM else None
        view.maximum = maximum if maximum != _INT_MAXIMUM else None

    def _update_value(self, value: int) -> None:
        with self.stop_refresh():
            self._view.value = value


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

    @staticmethod
    def _update_state(view: SliderViewLike, rendered_object: QValueSlider) -> None:
        # only the value: the slider's range ends at the last step, short of a `maximum`
        # that isn't a whole number of steps away
        view.value = rendered_object.shown_value()

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
            self._rendered_object = QLabel()
            self.refresh()

    @staticmethod
    def _refresh_text(_view: LabelViewLike, rendered_object: QLabel, value: str) -> None:
        rendered_object.setText(value)

    @staticmethod
    def _update_state(view: LabelViewLike, rendered_object: QLabel) -> None:
        view.text = rendered_object.text()


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
        rendered_object.setMarkdown(value)

    @staticmethod
    def _update_state(view: MarkdownViewLike, rendered_object: QTextBrowser) -> None:
        pass  # read-only: nothing to read back


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

    @staticmethod
    def _update_state(view: FormLabelRowView, rendered_object: QFormLabel) -> None:
        view.label = rendered_object.text()
        view.help = rendered_object.help()


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

    @staticmethod
    def _update_state(view: ProgressBarViewLike, rendered_object: QProgressBar) -> None:
        pass  # the user can't move a progress bar; nothing to read back


class ChartViewLike(ViewLike, Protocol):
    kind: ChartKind
    title: str
    x_title: str
    y_title: str
    x_unit: str
    y_unit: str
    series: list[Series]
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
        if chart is None or not isinstance(view, ChartView):
            return
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

    @staticmethod
    def _update_state(view: ChartViewLike, rendered_object: QChart) -> None:
        pass  # the user only looks at a chart; nothing to read back


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

    @staticmethod
    def _update_state(view: MetricViewLike, rendered_object: QMetric) -> None:
        pass  # a metric is read-only; nothing to read back


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

    def emit_cell_edited(self, row: int, column: int, text: str) -> None: ...
    def sort_by(self, column: int) -> None: ...
    def filter_error(self, column: int, text: str) -> str | None: ...
    def filter_placeholder(self, column: int, *, is_pattern: bool = False) -> str: ...
    def filter_takes_pattern(self, column: int) -> bool: ...
    def filter_chip(self, column: int) -> str: ...


class QtTableRenderer(QtWidgetRenderer[TableViewLike, QFilterTable]):
    """A table under its filter bar; the table shows `shown_rows`, in their order.

    The widgets know the rows only as shown: their indexes map back to `rows` through
    `shown_rows`.
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
            }
        )

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QFilterTable()
            table, bar = self._rendered_object.table, self._rendered_object.bar
            table.selected_rows_changed.connect(self._update_selected_rows)
            table.cell_edited.connect(self._update_cell)
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
        rendered_object.table.set_table(view.headers, [view.rows[row] for row in value])
        # resetting the table drops its selection: reapply it
        cls._refresh_selected_rows(view, rendered_object, view.selected_rows)
        rendered_object.bar.set_count(_count_text(view, value))
        rendered_object.empty.setVisible(len(value) == 0 and len(view.rows) > 0)

    @staticmethod
    def _refresh_editable_columns(
        _view: TableViewLike, rendered_object: QFilterTable, value: list[int]
    ) -> None:
        rendered_object.table.set_editable_columns(value)

    @staticmethod
    def _update_state(view: TableViewLike, rendered_object: QFilterTable) -> None:
        shown = view.shown_rows
        view.selected_rows = sorted(shown[row] for row in rendered_object.table.selected_rows())

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

    def _get_label_object(self, field_row_renderer: RendererContainer[View]) -> QFormLabel:
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
        # a document scrolls within itself: it takes the column's spare height, ahead of
        # the spacer under the views
        layout.addLayout(inset, 1 if isinstance(widget, QTextBrowser) else 0)


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
                if isinstance(view.renderer, QtWidgetRenderer) and isinstance(
                    view.renderer.qt_object, QWidget
                ):
                    self._rendered_object.content_layout.addWidget(view.renderer.qt_object)
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

    @staticmethod
    def _update_state(view: ExpanderView, rendered_object: QExpander) -> None:
        view.title = rendered_object.header.text()
        view.is_expanded = rendered_object.is_expanded()

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
        rendered_object.toggle.setToolTip(value)
        rendered_object.toggle.setAccessibleName(value)

    @staticmethod
    def _refresh_is_expanded(_view: SidebarView, rendered_object: QSidebar, value: bool) -> None:
        rendered_object.set_expanded(value)

    @staticmethod
    def _update_state(view: SidebarView, rendered_object: QSidebar) -> None:
        view.is_expanded = rendered_object.is_expanded()

    def _update_expanded(self, is_expanded: bool) -> None:
        with self.stop_refresh():
            self._view.is_expanded = is_expanded


class QtListRenderer(QtWidgetRenderer["ListView[Any]", QWidget]):
    """The records' views one above the other, added, moved and removed as they change."""

    def __init__(self, view: ListView[Any]) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update({"item_views": self._refresh_item_views})

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QWidget()
            layout = QVBoxLayout(self._rendered_object)
            # the column holding the list already insets it
            layout.setContentsMargins(0, 0, 0, 0)
            self.refresh()

    @staticmethod
    def _refresh_item_views(
        _view: ListView[Any], rendered_object: QWidget, value: list[View]
    ) -> None:
        widgets: list[QWidget] = []
        for item_view in value:
            if item_view.renderer is None:
                item_view.render(RendererType.QT)  # a record's view built since
            if isinstance(item_view.renderer, QtWidgetRenderer) and isinstance(
                item_view.renderer.qt_object, QWidget
            ):
                widgets.append(item_view.renderer.qt_object)
        layout = rendered_object.layout()
        assert layout is not None
        while layout.count() > 0:
            item = layout.takeAt(0)
            widget = None if item is None else item.widget()
            if widget is not None and widget not in widgets:
                # its record is gone
                widget.setParent(None)
                widget.deleteLater()
        for widget in widgets:
            layout.addWidget(widget)

    @staticmethod
    def _update_state(view: ListView[Any], rendered_object: QWidget) -> None:
        pass  # a list has no user-editable state of its own: its records are the model's


class QtGridRenderer(QtWidgetRenderer[GridView, QWidget]):
    """Views in a grid's cells: equally wide columns, rows as tall as their views."""

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QWidget()
            layout = QGridLayout(self._rendered_object)
            # the column holding the grid already insets it
            layout.setContentsMargins(0, 0, 0, 0)
            for view, position in self._view.positioned_views:
                if isinstance(view.renderer, QtWidgetRenderer) and isinstance(
                    view.renderer.qt_object, QWidget
                ):
                    # at the top, as in a row; with no share of a row, as wide as its content
                    alignment = Qt.AlignmentFlag.AlignTop
                    if view.default_stretch == 0:
                        alignment |= Qt.AlignmentFlag.AlignLeft
                    layout.addWidget(view.renderer.qt_object, *position, alignment)
            for column in range(self._view.column_count):
                layout.setColumnStretch(column, 1)
            # height to spare, next to a taller view, goes below the rows, not between them
            layout.setRowStretch(self._view.row_count, 1)
            self.refresh()

    @staticmethod
    def _update_state(view: GridView, rendered_object: QWidget) -> None:
        pass  # a grid has no user-editable state of its own


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
            if QtMainRenderer._add_window_part(child_view, rendered_object):
                continue
            if isinstance(child_view.renderer, QtRouterRenderer):
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
    def _add_window_part(child_view: View, rendered_object: QMainWindow) -> bool:
        """Add a part of the window around the content, if `child_view` is one.

        Its menus, status bar, toolbars and sidebar; return whether `child_view` is one.
        """
        renderer = child_view.renderer
        if isinstance(renderer, QtMenuRenderer):
            renderer.set_parent_rendered_object(rendered_object)
            renderer.render()
            if renderer.qt_object is not None:
                rendered_object.menuBar().addMenu(renderer.qt_object)
        elif isinstance(renderer, QtStatusBarRenderer):
            if isinstance(renderer.qt_object, QStatusBar):
                rendered_object.setStatusBar(renderer.qt_object)
        elif isinstance(renderer, QtToolBarRenderer):
            if renderer.qt_object is not None:
                rendered_object.addToolBar(renderer.qt_object)
        elif isinstance(renderer, QtSidebarRenderer):
            if renderer.qt_object is not None:
                rendered_object.addDockWidget(
                    Qt.DockWidgetArea.LeftDockWidgetArea, renderer.qt_object
                )
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
    "chart": QtChartRenderer,
    "checkbox": QtCheckBoxRenderer,
    "combobox": QtComboboxRenderer,
    "dialog": QtDialogRenderer,
    "expander": QtExpanderRenderer,
    "float_input": QtFloatInputRenderer,
    "int_input": QtIntInputRenderer,
    "form": QtFormRenderer,
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
    "status_bar": QtStatusBarRenderer,
    "table": QtTableRenderer,
    "toolbar": QtToolBarRenderer,
    "vertical": QtVerticalRenderer,
}

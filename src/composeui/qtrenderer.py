from __future__ import annotations

from typing import Any, Generic, TypeVar

from qtpy.QtGui import QDoubleValidator
from qtpy.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMainWindow,
    QVBoxLayout,
    QWidget,
)

from composeui.qradiogroup import QRadioGroup
from composeui.renderer import NoRenderedObjectError, Renderer
from composeui.view import (
    FloatInputView,
    FormRowView,
    FormView,
    GroupFormView,
    InputView,
    LabelFormRowView,
    LabelView,
    LogFormRow,
    LogType,
    MainView,
    RadioGroupView,
    View,
)

TView = TypeVar("TView", bound=View)
TWidget = TypeVar("TWidget", bound=QWidget)


class NoQtRendererObjectError(Exception):
    def __init__(self) -> None:
        super().__init__("Renderer should be inherited by QtRenderer")


class NotQWidgetError(Exception):
    def __init__(self) -> None:
        super().__init__("Renderer object should be of type QWidget")


class QtWidgetRenderer(Renderer[TView, TWidget]):
    def __init__(self, view: TView) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "is_visible": self._refresh_visible,
                "is_enabled": self._refresh_enabled,
            }
        )

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


class QtInputRenderer(QtWidgetRenderer[InputView, QLineEdit]):
    def __init__(self, view: InputView) -> None:
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
            self._view.editing_finished.add_qt_signal(
                self._rendered_object.editingFinished
            )
            self._view.text_changed.add_qt_signal(self._rendered_object.textChanged)
            self._view.text_edited.add_qt_signal(self._rendered_object.textEdited)
            self.refresh()

    @staticmethod
    def _refresh_text(_view: InputView, rendered_object: QLineEdit, value: str) -> None:
        rendered_object.setText(value)

    @staticmethod
    def _refresh_placeholder(
        _view: InputView, rendered_object: QLineEdit, value: str
    ) -> None:
        rendered_object.setPlaceholderText(value)

    @staticmethod
    def _update_state(view: InputView, rendered_object: QLineEdit) -> None:
        view.text = rendered_object.text()
        view.placeholder = rendered_object.placeholderText()

    def _update_text(self, text: str) -> None:
        with self.stop_refresh():
            self._view.text = text


class QtFloatInputRenderer(QtWidgetRenderer[FloatInputView, QLineEdit]):
    def __init__(self, view: FloatInputView) -> None:
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
            self._view.editing_finished.add_qt_signal(
                self._rendered_object.editingFinished
            )
            self._view.text_changed.add_qt_signal(self._rendered_object.textChanged)
            self._view.text_edited.add_qt_signal(self._rendered_object.textEdited)
            self.refresh()

    @staticmethod
    def _refresh_value(
        _view: FloatInputView, rendered_object: QLineEdit, value: float | None
    ) -> None:
        rendered_object.setText(str(value) if value is not None else "")

    @staticmethod
    def _refresh_placeholder(
        _view: FloatInputView, rendered_object: QLineEdit, value: str
    ) -> None:
        rendered_object.setPlaceholderText(value)

    @staticmethod
    def _refresh_minimum(
        _view: FloatInputView, rendered_object: QLineEdit, value: float | None
    ) -> None:
        validator = rendered_object.validator()
        assert isinstance(validator, QDoubleValidator)
        validator.setBottom(float("-inf") if value is None else value)

    @staticmethod
    def _refresh_maximum(
        _view: FloatInputView, rendered_object: QLineEdit, value: float | None
    ) -> None:
        validator = rendered_object.validator()
        assert isinstance(validator, QDoubleValidator)
        validator.setTop(float("inf") if value is None else value)

    @staticmethod
    def _refresh_decimals(
        _view: FloatInputView, rendered_object: QLineEdit, value: int | None
    ) -> None:
        validator = rendered_object.validator()
        assert isinstance(validator, QDoubleValidator)
        validator.setDecimals(-1 if value is None else value)

    @staticmethod
    def _update_state(view: FloatInputView, rendered_object: QLineEdit) -> None:
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


class QtLabelRenderer(QtWidgetRenderer[LabelView, QLabel]):
    def __init__(self, view: LabelView) -> None:
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
    def _refresh_text(_view: LabelView, rendered_object: QLabel, value: str) -> None:
        rendered_object.setText(value)

    @staticmethod
    def _update_state(view: LabelView, rendered_object: QLabel) -> None:
        view.text = rendered_object.text()


TValue = TypeVar("TValue")


class QtRadioGroupRenderer(
    QtWidgetRenderer[RadioGroupView[TValue], QRadioGroup], Generic[TValue]
):
    def __init__(self, view: RadioGroupView[TValue]) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "value": self._refresh_value,
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
        _view: RadioGroupView[TValue], rendered_object: QRadioGroup, value: Any
    ) -> None:
        rendered_object.set_value(value)

    @staticmethod
    def _update_state(
        view: RadioGroupView[TValue], rendered_object: QRadioGroup
    ) -> None:
        view.value = rendered_object.value()

    def _update_value(self, value: TValue | None) -> None:
        with self.stop_refresh():
            self._view.value = value


class QtLogFormRowRenderer(QtWidgetRenderer[LogFormRow, QLabel]):
    def __init__(self, view: LogFormRow) -> None:
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
    def _refresh_log_message(
        _view: LogFormRow, rendered_object: QLabel, value: str
    ) -> None:
        rendered_object.setText(value)

    @staticmethod
    def _refresh_log_type(
        _view: LogFormRow, rendered_object: QLabel, value: LogType
    ) -> None:
        if value == LogType.ERROR:
            rendered_object.setStyleSheet("QLabel { color : red; }")
        elif value == LogType.WARNING:
            rendered_object.setStyleSheet("QLabel { color : orange; }")
        else:
            rendered_object.setStyleSheet("")

    @staticmethod
    def _update_state(view: LogFormRow, rendered_object: QLabel) -> None:
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
                if isinstance(field_row, FormRowView):
                    field_layout_object = QVBoxLayout()
                    field_object = self._get_field_object(field_row)
                    field_layout_object.addWidget(field_object)
                    log_object = self._get_log_object(field_row)
                    field_layout_object.addWidget(log_object)
                    if isinstance(field_row, LabelFormRowView):
                        label_object = self._get_label_object(field_row)
                        layout.addRow(label_object, field_layout_object)
                    else:
                        layout.addRow(field_layout_object)
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

    def _get_field_object(self, field_row: FormRowView[View]) -> QWidget:
        field_view = field_row.field_view
        if not isinstance(field_view.renderer, QtWidgetRenderer):
            raise NoQtRendererObjectError
        field_object = field_view.renderer.qt_object
        if not isinstance(field_object, QWidget):
            raise NotQWidgetError
        return field_object

    def _get_log_object(self, field_row: FormRowView[View]) -> QWidget:
        log_view = field_row.log_view
        if not isinstance(log_view.renderer, QtWidgetRenderer):
            raise NoQtRendererObjectError
        log_object = log_view.renderer.qt_object
        if not isinstance(log_object, QWidget):
            raise NotQWidgetError
        return log_object

    def _get_label_object(self, field_row: LabelFormRowView[View]) -> QLabel:
        if not isinstance(field_row.label_view.renderer, QtLabelRenderer):
            raise NoQtRendererObjectError
        label_object = field_row.label_view.renderer.qt_object
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


class QtMainRenderer(QtWidgetRenderer[MainView, QMainWindow]):
    def __init__(self, view: MainView) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "title": self._refresh_title,
                "minimum_width": self._refresh_minimum_width,
                "minimum_height": self._refresh_minimum_height,
            }
        )

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QMainWindow()
            self._create_central_widget(self._view, self._rendered_object)
            self.refresh()

    @staticmethod
    def _create_central_widget(view: MainView, rendered_object: QMainWindow) -> None:
        central_widget = QWidget()
        central_layout = QVBoxLayout()
        central_widget.setLayout(central_layout)
        rendered_object.setCentralWidget(central_widget)
        for child_view in view.children_views:
            if isinstance(child_view.renderer, QtWidgetRenderer):
                child_rendered_object = child_view.renderer.qt_object
                if isinstance(child_rendered_object, QWidget):
                    central_layout.addWidget(child_rendered_object)

    @staticmethod
    def _refresh_title(
        _view: MainView, rendered_object: QMainWindow, value: str
    ) -> None:
        rendered_object.setWindowTitle(value)

    @staticmethod
    def _refresh_minimum_width(
        _view: MainView, rendered_object: QMainWindow, value: int
    ) -> None:
        rendered_object.setMinimumWidth(value)

    @staticmethod
    def _refresh_minimum_height(
        _view: MainView, rendered_object: QMainWindow, value: int
    ) -> None:
        rendered_object.setMinimumHeight(value)

    @staticmethod
    def _update_state(view: MainView, rendered_object: QMainWindow) -> None:
        view.title = rendered_object.windowTitle()
        view.minimum_width = rendered_object.minimumWidth()
        view.minimum_height = rendered_object.minimumHeight()

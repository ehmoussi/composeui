from __future__ import annotations

from typing import TypeVar

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
    @property
    def qt_object(self) -> TWidget | None:
        return self._rendered_object

    def refresh(self) -> None:
        if self._rendered_object is None:
            raise NoRenderedObjectError
        self._rendered_object.blockSignals(True)  # noqa: FBT003
        self._refresh(self._view, self._rendered_object)
        self._rendered_object.setVisible(self._view.is_visible)
        self._rendered_object.setEnabled(self._view.is_enabled)
        self._rendered_object.blockSignals(False)  # noqa: FBT003

    def update_state(self) -> None:
        """Update the state of the view using framework view object."""
        if self._rendered_object is None:
            raise NoRenderedObjectError
        self._update_state(self._view, self._rendered_object)
        self._view.is_visible = self._rendered_object.isVisible()
        self._view.is_enabled = self._rendered_object.isEnabled()


class QtInputRenderer(QtWidgetRenderer[InputView, QLineEdit]):
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
    def _refresh(view: InputView, rendered_object: QLineEdit) -> None:
        rendered_object.setText(view.text)
        rendered_object.setPlaceholderText(view.placeholder)

    @staticmethod
    def _update_state(view: InputView, rendered_object: QLineEdit) -> None:
        view.text = rendered_object.text()
        view.placeholder = rendered_object.placeholderText()

    def _update_text(self, text: str) -> None:
        self._view.text = text


class QtFloatInputRenderer(QtWidgetRenderer[FloatInputView, QLineEdit]):
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
    def _refresh(view: FloatInputView, rendered_object: QLineEdit) -> None:
        rendered_object.setText(str(view.value) if view.value is not None else "")
        rendered_object.setPlaceholderText(view.placeholder)
        validator = rendered_object.validator()
        assert isinstance(validator, QDoubleValidator)
        validator.setBottom(float("-inf") if view.minimum is None else view.minimum)
        validator.setTop(float("inf") if view.maximum is None else view.maximum)
        validator.setDecimals(-1 if view.decimals is None else view.decimals)

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
        if text != "":
            self._view.value = float(text)
        else:
            self._view.value = None


class QtLabelRenderer(QtWidgetRenderer[LabelView, QLabel]):
    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QLabel()
            self.refresh()

    @staticmethod
    def _refresh(view: LabelView, rendered_object: QLabel) -> None:
        rendered_object.setText(view.text)

    @staticmethod
    def _update_state(view: LabelView, rendered_object: QLabel) -> None:
        view.text = rendered_object.text()


class QtLogFormRowRenderer(QtWidgetRenderer[LogFormRow, QLabel]):
    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QLabel()
            self.refresh()

    @staticmethod
    def _refresh(view: LogFormRow, rendered_object: QLabel) -> None:
        rendered_object.setText(view.log_message)
        if view.log_type == LogType.ERROR:
            rendered_object.setStyleSheet("QLabel { color : red; }")
        elif view.log_type == LogType.WARNING:
            rendered_object.setStyleSheet("QLabel { color : orange; }")

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
                else:
                    layout.addRow(field_row.renderer.qt_object)
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
    def _refresh(view: FormView, rendered_object: QWidget) -> None:
        if isinstance(rendered_object, QGroupBox) and isinstance(view, GroupFormView):
            rendered_object.setTitle(view.title)

    @staticmethod
    def _update_state(view: FormView, rendered_object: QWidget) -> None:
        if isinstance(rendered_object, QGroupBox) and isinstance(view, GroupFormView):
            view.title = rendered_object.title()


class QtMainRenderer(QtWidgetRenderer[MainView, QMainWindow]):
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
    def _refresh(view: MainView, rendered_object: QMainWindow) -> None:
        rendered_object.setWindowTitle(view.title)
        rendered_object.setMinimumWidth(view.minimum_width)
        rendered_object.setMinimumHeight(view.minimum_height)

    @staticmethod
    def _update_state(view: MainView, rendered_object: QMainWindow) -> None:
        view.title = rendered_object.windowTitle()
        view.minimum_width = rendered_object.minimumWidth()
        view.minimum_height = rendered_object.minimumHeight()

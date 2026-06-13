from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

from qtpy.QtWidgets import (
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from composeui.renderer import NoRenderedObjectError, Renderer
from composeui.view import (
    FormRowView,
    FormView,
    InputView,
    LabelFormRowView,
    LabelView,
    LogFormRow,
    LogType,
    View,
)

if TYPE_CHECKING:
    from qtpy.QtCore import QObject

TView = TypeVar("TView", bound=View)
TObject = TypeVar("TObject", bound="QObject")


class NoQtRendererObjectError(Exception):
    def __init__(self) -> None:
        super().__init__("Renderer should be inherited by QtRenderer")


class NotQWidgetError(Exception):
    def __init__(self) -> None:
        super().__init__("Renderer object should be of type QWidget")


class QtRenderer(Renderer[TView, TObject]):
    @property
    def qt_object(self) -> TObject | None:
        return self._rendered_object

    def refresh(self) -> None:
        if self._rendered_object is None:
            raise NoRenderedObjectError
        self._rendered_object.blockSignals(True)  # noqa: FBT003
        self._refresh(self._view, self._rendered_object)
        self._rendered_object.blockSignals(False)  # noqa: FBT003


TWidget = TypeVar("TWidget", bound="QWidget")


class QtWidgetRenderer(QtRenderer[TView, TWidget]):
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
            self._rendered_object = QWidget()
            layout = QFormLayout()
            self._rendered_object.setLayout(layout)
            for field_row in self._view.field_rows:
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
            self.refresh()

    def _get_field_object(self, field_row: FormRowView) -> QWidget:
        field_view = field_row.field_view
        if not isinstance(field_view.renderer, QtRenderer):
            raise NoQtRendererObjectError
        field_object = field_view.renderer.qt_object
        if not isinstance(field_object, QWidget):
            raise NotQWidgetError
        return field_object

    def _get_log_object(self, field_row: FormRowView) -> QWidget:
        log_view = field_row.log_view
        if not isinstance(log_view.renderer, QtRenderer):
            raise NoQtRendererObjectError
        log_object = log_view.renderer.qt_object
        if not isinstance(log_object, QWidget):
            raise NotQWidgetError
        return log_object

    def _get_label_object(self, field_row: LabelFormRowView) -> QLabel:
        if not isinstance(field_row.label_view.renderer, QtLabelRenderer):
            raise NoQtRendererObjectError
        label_object = field_row.label_view.renderer.qt_object
        if label_object is None:
            raise NoRenderedObjectError
        return label_object

    @staticmethod
    def _refresh(view: FormView, rendered_object: QWidget) -> None:
        pass

    @staticmethod
    def _update_state(view: FormView, rendered_object: QWidget) -> None:
        pass

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from qtpy.QtGui import QDoubleValidator
from qtpy.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMainWindow,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)
from typing_extensions import Protocol

from composeui.qradiogroup import QRadioGroup
from composeui.renderer import (
    NoRenderedObjectError,
    Renderer,
    RendererContainer,
    ViewLike,
)
from composeui.view import (
    FormLabelRowView,
    FormRowView,
    FormView,
    GroupFormView,
    LogType,
    MainView,
    StatusBar,
    View,
)

if TYPE_CHECKING:
    from composeui.signal import Signal, SignalNoArgs

TView = TypeVar("TView", bound=ViewLike)
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


class _InputViewLike(ViewLike, Protocol):
    placeholder: str
    text_changed: Signal[str]
    text_edited: Signal[str]
    editing_finished: SignalNoArgs


class InputViewLike(_InputViewLike, Protocol):
    text: str


class QtInputRenderer(QtWidgetRenderer[InputViewLike, QLineEdit]):
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


TValue = TypeVar("TValue")


class RadioGroupViewLike(ViewLike, Protocol, Generic[TValue]):
    value: TValue | None
    values: dict[str, TValue]
    value_changed: Signal[TValue | None]


class QtRadioGroupRenderer(
    QtWidgetRenderer[RadioGroupViewLike[TValue], QRadioGroup], Generic[TValue]
):
    def __init__(self, view: RadioGroupViewLike[TValue]) -> None:
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
        _view: RadioGroupViewLike[TValue], rendered_object: QRadioGroup, value: Any
    ) -> None:
        rendered_object.set_value(value)

    @staticmethod
    def _update_state(view: RadioGroupViewLike[TValue], rendered_object: QRadioGroup) -> None:
        view.value = rendered_object.value()

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
            self._rendered_object.setMinimumSize(
                self._view.minimum_width, self._view.minimum_height
            )
            self._create_central_widget(self._view, self._rendered_object)
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
            extensions.append(f"{name} ({' '.join(name_extensions)})")
        return ";;".join(extensions)

    @staticmethod
    def _create_central_widget(view: MainView, rendered_object: QMainWindow) -> None:
        central_widget = QWidget()
        central_layout = QVBoxLayout()
        central_widget.setLayout(central_layout)
        for child_view in view.children_views:
            if isinstance(child_view.renderer, QtStatusBarRenderer):
                child_rendered_object = child_view.renderer.qt_object
                if isinstance(child_rendered_object, QStatusBar):
                    rendered_object.setStatusBar(child_rendered_object)
            elif isinstance(child_view.renderer, QtWidgetRenderer):
                child_rendered_object = child_view.renderer.qt_object
                if isinstance(child_rendered_object, QWidget):
                    central_layout.addWidget(child_rendered_object)
        central_layout.addStretch()
        central_layout.update()
        rendered_object.setCentralWidget(central_widget)

    @staticmethod
    def _refresh_title(_view: MainView, rendered_object: QMainWindow, value: str) -> None:
        rendered_object.setWindowTitle(value)

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

from __future__ import annotations

import enum
import threading
from abc import abstractmethod
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Generic, Optional, TypeVar, cast, overload

import attrs
from typing_extensions import dataclass_transform

from composeui.renderer import Renderer, RendererContainer
from composeui.signal import Signal, SignalNoArgs

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from attrs import AttrsInstance


class RendererType(enum.Enum):
    QT = enum.auto()


def notify_renderer(instance: View, attribute: Any, value: Any) -> Any:
    attribute_name = str(attribute.name)
    if not attribute_name.startswith("_") and hasattr(instance, attribute_name):
        old_value = getattr(instance, attribute_name)
        if (
            old_value != value
            and isinstance(instance.renderer, Renderer)
            and not instance.renderer.is_updating_state()
        ):
            instance.renderer.refresh_attribute(attribute.name, value)
    return value


T = TypeVar("T", bound=type)


@overload
def define_view(cls: T) -> T: ...
@overload
def define_view(cls: None = None, **kwargs: Any) -> Callable[[T], T]: ...
@dataclass_transform(kw_only_default=True, field_specifiers=(attrs.field,))
def define_view(cls: T | None = None, **kwargs: Any) -> T | Callable[[T], T]:
    def wrap(cls: T) -> T:
        if "on_setattr" in kwargs:
            if isinstance(kwargs["on_setattr"], Sequence):
                kwargs["on_setattr"] = [*kwargs["on_setattr"], notify_renderer]
            else:
                kwargs["on_setattr"] = [kwargs["on_setattr"], notify_renderer]
        return attrs.define(cls, on_setattr=[notify_renderer], kw_only=True, slots=False, **kwargs)

    if cls is None:
        return wrap
    return wrap(cls)


@define_view
class View:
    # properties
    is_visible: bool = attrs.field(default=True)
    is_enabled: bool = attrs.field(default=True)
    # renderer
    renderer: Renderer[Any, Any] | RendererContainer[Any] | None = attrs.field(default=None)

    def __attrs_post_init__(self) -> None:
        for f in attrs.fields(cast("type[AttrsInstance]", type(self))):
            signal = getattr(self, f.name, None)
            if isinstance(signal, Signal):
                signal.set_name(f"{type(self).__name__}.{f.name}")

    @property
    def children_views(self) -> list[View]:
        """Get all the field rows of the form view."""
        children_views: list[View] = []
        for field_row_attr in attrs.fields(cast("type[AttrsInstance]", type(self))):
            view = getattr(self, field_row_attr.name)
            if isinstance(view, View):
                children_views.append(view)
        return children_views

    def render(self, renderer_type: RendererType) -> None:
        self._render_children(renderer_type)
        if self.renderer is None:
            self._create_renderer(renderer_type)
        if self.renderer is not None:
            self.renderer.render()

    def _create_renderer(self, renderer_type: RendererType) -> None:
        """Create the renderer of the view."""
        raise NotImplementedError(self._create_renderer)

    def _render_children(self, renderer_type: RendererType) -> None:
        for child_view in self.children_views:
            child_view.render(renderer_type)


@define_view
class StatusBar(View):
    message: str = attrs.field(default="")
    message_changed: Signal[str] = attrs.Factory(Signal[str])
    _timer: threading.Timer | None = attrs.field(default=None)

    def show_message(self, message: str, *, timeout: int = 0) -> None:
        """Show a message.

        The message is dismissed after timeout seconds. A timeout of 0 means
        the message is never automatically dismissed.
        """
        self.message = message
        if self._timer is not None:
            self._timer.cancel()
        if timeout > 0:
            self._timer = threading.Timer(timeout, self.clear_message)
            self._timer.start()

    def clear_message(self) -> None:
        self.message = ""
        self._timer = None

    def _create_renderer(self, renderer_type: RendererType) -> None:
        if renderer_type == RendererType.QT:
            from composeui.qtrenderer import QtStatusBarRenderer  # noqa: PLC0415

            self.renderer = QtStatusBarRenderer(self)


# class FileType(enum.Enum):
#     OpenFile = enum.auto()
#     SaveFile = enum.auto()


@define_view
class FileView(View):
    filepath: Path | None = attrs.field(default=None)
    extensions: dict[str, tuple[str, ...]] = attrs.Factory(dict[str, tuple[str, ...]])
    # file_type: FileType = attrs.field(default=FileType.OpenFile)

    def _create_renderer(self, renderer_type: RendererType) -> None:
        return None


@define_view
class MainView(View):
    title: str = attrs.field(init=False, on_setattr=attrs.setters.frozen)
    extension: str = attrs.field(init=False, on_setattr=attrs.setters.frozen)
    saved_filepath: Path | None = None

    minimum_width: int = attrs.field(default=720)
    minimum_height: int = attrs.field(default=480)

    # file_menu: FileMenu = FileMenu(title="File")
    # study_toolbar: StudyToolbar = StudyToolbar(title="study")
    file_view: FileView = attrs.Factory(FileView)
    # message_view: MessageView = MessageView()
    status_bar: StatusBar = attrs.Factory(StatusBar)

    def open_file(self, extensions: dict[str, tuple[str, ...]]) -> Path | None:
        from composeui.qtrenderer import QtMainRenderer  # noqa: PLC0415

        self.file_view.extensions = extensions
        if isinstance(self.renderer, QtMainRenderer):
            self.file_view.filepath = self.renderer.open_file()
        return self.file_view.filepath

    def save_file(self, extensions: dict[str, tuple[str, ...]]) -> Path | None:
        from composeui.qtrenderer import QtMainRenderer  # noqa: PLC0415

        self.file_view.extensions = extensions
        if isinstance(self.renderer, QtMainRenderer):
            self.file_view.filepath = self.renderer.save_file()
        return self.file_view.filepath

    def _create_renderer(self, renderer_type: RendererType) -> None:
        if renderer_type == RendererType.QT:
            from composeui.qtrenderer import QtMainRenderer  # noqa: PLC0415

            self.renderer = QtMainRenderer(self)


@define_view
class _InputView:
    # properties
    placeholder: str = attrs.field(default="")
    # signals
    editing_finished: SignalNoArgs = attrs.field(factory=SignalNoArgs)
    text_changed: Signal[str] = attrs.field(factory=Signal[str])
    text_edited: Signal[str] = attrs.field(factory=Signal[str])


@define_view
class InputMixin(_InputView):
    # properties
    text: str = attrs.field(default="")


@define_view
class InputView(InputMixin, View):
    def _create_renderer(self, renderer_type: RendererType) -> None:
        if renderer_type == RendererType.QT:
            from composeui.qtrenderer import QtInputRenderer  # noqa: PLC0415

            self.renderer = QtInputRenderer(self)


@define_view
class FloatInputMixin(_InputView):
    # properties
    value: float | None = attrs.field(default=None)
    minimum: float | None = attrs.field(default=None)
    maximum: float | None = attrs.field(default=None)
    decimals: int | None = attrs.field(default=None)


@define_view
class FloatInputView(FloatInputMixin, View):
    def _create_renderer(self, renderer_type: RendererType) -> None:
        if renderer_type == RendererType.QT:
            from composeui.qtrenderer import QtFloatInputRenderer  # noqa: PLC0415

            self.renderer = QtFloatInputRenderer(self)


class LogType(enum.Enum):
    ERROR = enum.auto()
    WARNING = enum.auto()
    INFO = enum.auto()


@define_view
class LogMixin:
    log_message: str = attrs.field(default="")
    log_type: LogType = attrs.field(default=LogType.ERROR)


@define_view
class LogView(LogMixin, View):
    def _create_renderer(self, renderer_type: RendererType) -> None:
        if renderer_type == RendererType.QT:
            from composeui.qtrenderer import QtLogRenderer  # noqa: PLC0415

            self.renderer = QtLogRenderer(self)


@define_view
class LabelMixin:
    text: str = attrs.field(default="")


@define_view
class LabelView(LabelMixin, View):
    def _create_renderer(self, renderer_type: RendererType) -> None:
        if renderer_type == RendererType.QT:
            from composeui.qtrenderer import QtLabelRenderer  # noqa: PLC0415

            self.renderer = QtLabelRenderer(self)


TValue = TypeVar("TValue")


@define_view
class RadioGroupMixin(Generic[TValue]):
    value: TValue | None = attrs.field(default=None)
    values: dict[str, TValue] = attrs.field(
        factory=dict[str, TValue],
        on_setattr=attrs.setters.frozen,
    )
    value_changed: Signal[TValue | None] = attrs.Factory(Signal[Optional[TValue]])


@define_view
class RadioGroupView(RadioGroupMixin[TValue], View):
    def _create_renderer(self, renderer_type: RendererType) -> None:
        if renderer_type == RendererType.QT:
            from composeui.qtrenderer import QtRadioGroupRenderer  # noqa: PLC0415

            self.renderer = QtRadioGroupRenderer(self)


@define_view
class FormRowView(LogMixin, View):
    def _create_renderer(self, renderer_type: RendererType) -> None:
        field_renderer = self._create_field_renderer(renderer_type)
        if renderer_type == RendererType.QT and field_renderer is not None:
            from composeui.qtrenderer import QtLogRenderer  # noqa: PLC0415

            log_renderer = QtLogRenderer(self)
            self.renderer = RendererContainer(self, {"field": field_renderer, "log": log_renderer})

    @abstractmethod
    def _create_field_renderer(self, renderer_type: RendererType) -> Renderer[Any, Any] | None: ...


@define_view
class FormLabelRowView(FormRowView):
    label: str = attrs.field(default="")

    def _create_renderer(self, renderer_type: RendererType) -> None:
        field_renderer = self._create_field_renderer(renderer_type)
        if renderer_type == RendererType.QT and field_renderer is not None:
            from composeui.qtrenderer import (  # noqa: PLC0415
                QtFormLabelRenderer,
                QtLogRenderer,
            )

            log_renderer = QtLogRenderer(self)
            label_renderer = QtFormLabelRenderer(self)
            self.renderer = RendererContainer(
                self,
                {"label": label_renderer, "field": field_renderer, "log": log_renderer},
            )

    @abstractmethod
    def _create_field_renderer(self, renderer_type: RendererType) -> Renderer[Any, Any] | None: ...


@define_view
class RowInputView(FormRowView, InputMixin):
    def _create_field_renderer(self, renderer_type: RendererType) -> Renderer[Any, Any] | None:
        if renderer_type == RendererType.QT:
            from composeui.qtrenderer import QtInputRenderer  # noqa: PLC0415

            return QtInputRenderer(self)
        return None


@define_view
class LabelRowInputView(FormLabelRowView, InputMixin):
    def _create_field_renderer(self, renderer_type: RendererType) -> Renderer[Any, Any] | None:
        if renderer_type == RendererType.QT:
            from composeui.qtrenderer import QtInputRenderer  # noqa: PLC0415

            return QtInputRenderer(self)
        return None


@define_view
class RowFloatInputView(FormRowView, FloatInputMixin):
    def _create_field_renderer(self, renderer_type: RendererType) -> Renderer[Any, Any] | None:
        if renderer_type == RendererType.QT:
            from composeui.qtrenderer import QtFloatInputRenderer  # noqa: PLC0415

            return QtFloatInputRenderer(self)
        return None


@define_view
class LabelRowFloatInputView(FormLabelRowView, FloatInputMixin):
    def _create_field_renderer(self, renderer_type: RendererType) -> Renderer[Any, Any] | None:
        if renderer_type == RendererType.QT:
            from composeui.qtrenderer import QtFloatInputRenderer  # noqa: PLC0415

            return QtFloatInputRenderer(self)
        return None


@define_view
class RowRadioGroupView(FormRowView, RadioGroupMixin[TValue]):
    def _create_field_renderer(self, renderer_type: RendererType) -> Renderer[Any, Any] | None:
        if renderer_type == RendererType.QT:
            from composeui.qtrenderer import QtRadioGroupRenderer  # noqa: PLC0415

            return QtRadioGroupRenderer(self)
        return None


@define_view
class LabelRowRadioGroupView(FormLabelRowView, RadioGroupMixin[TValue]):
    def _create_field_renderer(self, renderer_type: RendererType) -> Renderer[Any, Any] | None:
        if renderer_type == RendererType.QT:
            from composeui.qtrenderer import QtRadioGroupRenderer  # noqa: PLC0415

            return QtRadioGroupRenderer(self)
        return None


@define_view
class FormView(View):
    log_view: LogView = attrs.field(factory=LogView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.log_view.is_visible = False

    @property
    def field_rows(self) -> list[FormRowView | FormView]:
        """Get all the field rows of the form view."""
        return [
            getattr(self, field_row_attr.name)
            for field_row_attr in attrs.fields(cast("type[AttrsInstance]", type(self)))
            if isinstance(getattr(self, field_row_attr.name), (FormRowView, FormView))
        ]

    def _create_renderer(self, renderer_type: RendererType) -> None:
        if renderer_type == RendererType.QT:
            from composeui.qtrenderer import QtFormRenderer  # noqa: PLC0415

            self.renderer = QtFormRenderer(self)


@define_view
class GroupFormView(FormView):
    title: str = attrs.field(default="")

    def _create_renderer(self, renderer_type: RendererType) -> None:
        if renderer_type == RendererType.QT:
            from composeui.qtrenderer import QtGroupFormRenderer  # noqa: PLC0415

            self.renderer = QtGroupFormRenderer(self)

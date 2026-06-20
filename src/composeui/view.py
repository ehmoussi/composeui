from __future__ import annotations

import enum
from abc import abstractmethod
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Generic, TypeVar, overload

import attrs

from composeui.renderer import Renderer, RendererContainer
from composeui.signal import Signal

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


class RendererType(enum.Enum):
    QT = enum.auto()


def notify_renderer(instance: View, attribute: Any, value: Any) -> Any:
    if hasattr(instance, attribute.name):
        old_value = getattr(instance, attribute.name)
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
def define_view(cls: T | None = None, **kwargs: Any) -> T | Callable[[T], T]:
    def wrap(cls: T) -> T:
        if "on_setattr" in kwargs:
            if isinstance(kwargs["on_setattr"], Sequence):
                kwargs["on_setattr"] = [*kwargs["on_setattr"], notify_renderer]
            else:
                kwargs["on_setattr"] = [kwargs["on_setattr"], notify_renderer]
        return attrs.define(
            cls, on_setattr=[notify_renderer], kw_only=True, slots=False, **kwargs
        )

    if cls is None:
        return wrap
    return wrap(cls)


@define_view
class View:
    # properties
    is_visible: bool = attrs.field(default=True)
    is_enabled: bool = attrs.field(default=True)
    # renderer
    renderer: Renderer[Any, Any] | RendererContainer[Any] | None = attrs.field(
        default=None
    )

    @property
    def children_views(self) -> list[View]:
        """Get all the field rows of the form view."""
        children_views: list[View] = []
        for field_row_attr in attrs.fields(type(self)):
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
class MainView(View):
    title: str = attrs.field(init=False, on_setattr=attrs.setters.frozen)
    extension: str = attrs.field(init=False, on_setattr=attrs.setters.frozen)
    saved_filepath: Path | None = None

    minimum_width: int = attrs.field(default=720)
    minimum_height: int = attrs.field(default=480)

    # file_menu: FileMenu = FileMenu(title="File")
    # study_toolbar: StudyToolbar = StudyToolbar(title="study")
    # file_view: FileView = FileView()
    # message_view: MessageView = MessageView()
    # status_bar: StatusBar = StatusBar()

    def _create_renderer(self, renderer_type: RendererType) -> None:
        if renderer_type == RendererType.QT:
            from composeui.qtrenderer import QtMainRenderer  # noqa: PLC0415

            self.renderer = QtMainRenderer(self)


@define_view
class _InputView:
    # properties
    placeholder: str = attrs.field(default="")
    # signals
    editing_finished: Signal = attrs.field(factory=Signal)
    text_changed: Signal = attrs.field(factory=Signal)
    text_edited: Signal = attrs.field(factory=Signal)


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
    value_changed: Signal = attrs.Factory(Signal)


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
            self.renderer = RendererContainer(
                self, {"field": field_renderer, "log": log_renderer}
            )

    @abstractmethod
    def _create_field_renderer(
        self, renderer_type: RendererType
    ) -> Renderer[Any, Any] | None: ...


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
    def _create_field_renderer(
        self, renderer_type: RendererType
    ) -> Renderer[Any, Any] | None: ...


@define_view
class RowInputView(FormRowView, InputMixin):
    def _create_field_renderer(
        self, renderer_type: RendererType
    ) -> Renderer[Any, Any] | None:
        if renderer_type == RendererType.QT:
            from composeui.qtrenderer import QtInputRenderer  # noqa: PLC0415

            return QtInputRenderer(self)
        return None


@define_view
class LabelRowInputView(FormLabelRowView, InputMixin):
    def _create_field_renderer(
        self, renderer_type: RendererType
    ) -> Renderer[Any, Any] | None:
        if renderer_type == RendererType.QT:
            from composeui.qtrenderer import QtInputRenderer  # noqa: PLC0415

            return QtInputRenderer(self)
        return None


@define_view
class RowFloatInputView(FormRowView, FloatInputMixin):
    def _create_field_renderer(
        self, renderer_type: RendererType
    ) -> Renderer[Any, Any] | None:
        if renderer_type == RendererType.QT:
            from composeui.qtrenderer import QtFloatInputRenderer  # noqa: PLC0415

            return QtFloatInputRenderer(self)
        return None


@define_view
class LabelRowFloatInputView(FormLabelRowView, FloatInputMixin):
    def _create_field_renderer(
        self, renderer_type: RendererType
    ) -> Renderer[Any, Any] | None:
        if renderer_type == RendererType.QT:
            from composeui.qtrenderer import QtFloatInputRenderer  # noqa: PLC0415

            return QtFloatInputRenderer(self)
        return None


@define_view
class RowRadioGroupView(FormRowView, RadioGroupMixin[TValue]):
    def _create_field_renderer(
        self, renderer_type: RendererType
    ) -> Renderer[Any, Any] | None:
        if renderer_type == RendererType.QT:
            from composeui.qtrenderer import QtRadioGroupRenderer  # noqa: PLC0415

            return QtRadioGroupRenderer(self)
        return None


@define_view
class LabelRowRadioGroupView(FormLabelRowView, RadioGroupMixin[TValue]):
    def _create_field_renderer(
        self, renderer_type: RendererType
    ) -> Renderer[Any, Any] | None:
        if renderer_type == RendererType.QT:
            from composeui.qtrenderer import QtRadioGroupRenderer  # noqa: PLC0415

            return QtRadioGroupRenderer(self)
        return None


@define_view
class FormView(View):
    log_view: LogView = attrs.field(factory=LogView)

    def __attrs_post_init__(self) -> None:
        self.log_view.is_visible = False

    @property
    def field_rows(self) -> list[FormRowView | FormView]:
        """Get all the field rows of the form view."""
        return [
            getattr(self, field_row_attr.name)
            for field_row_attr in attrs.fields(type(self))
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

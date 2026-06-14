from __future__ import annotations

import enum
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Generic, TypeVar, overload

import attrs

from composeui.renderer import Renderer
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
        return attrs.define(cls, on_setattr=[notify_renderer], **kwargs)

    if cls is None:
        return wrap
    return wrap(cls)


@define_view(kw_only=True)
class View:
    # properties
    is_visible: bool = attrs.field(default=True)
    is_enabled: bool = attrs.field(default=True)
    # renderer
    renderer: Renderer[Any, Any] | None = attrs.field(default=None)

    @property
    def children_views(self) -> list[View]:
        """Get all the field rows of the form view."""
        return [
            getattr(self, field_row_attr.name)
            for field_row_attr in attrs.fields(type(self))
            if isinstance(getattr(self, field_row_attr.name), View)
        ]

    def render(self, renderer_type: RendererType) -> None:
        self._render_children(renderer_type)
        if self.renderer is None:
            self._create_renderer(renderer_type)
        if self.renderer is not None:
            self.renderer.render()

    def _create_renderer(self, renderer_type: RendererType) -> None:
        """Create the renderer of the view."""
        raise NotImplementedError

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
class _InputView(View):
    # properties
    placeholder: str = attrs.field(default="")
    # signals
    editing_finished: Signal = attrs.field(factory=Signal)
    text_changed: Signal = attrs.field(factory=Signal)
    text_edited: Signal = attrs.field(factory=Signal)


@define_view
class InputView(_InputView):
    # properties
    text: str = attrs.field(default="")

    def _create_renderer(self, renderer_type: RendererType) -> None:
        if renderer_type == RendererType.QT:
            from composeui.qtrenderer import QtInputRenderer  # noqa: PLC0415

            self.renderer = QtInputRenderer(self)


@define_view
class FloatInputView(_InputView):
    # properties
    value: float | None = attrs.field(default=None)
    minimum: float | None = attrs.field(default=None)
    maximum: float | None = attrs.field(default=None)
    decimals: int | None = attrs.field(default=None)

    def _create_renderer(self, renderer_type: RendererType) -> None:
        if renderer_type == RendererType.QT:
            from composeui.qtrenderer import QtFloatInputRenderer  # noqa: PLC0415

            self.renderer = QtFloatInputRenderer(self)


class LogType(enum.Enum):
    ERROR = enum.auto()
    WARNING = enum.auto()
    INFO = enum.auto()


@define_view
class LogFormRow(View):
    log_message: str = attrs.field(default="")
    log_type: LogType = attrs.field(default=LogType.ERROR)

    def _create_renderer(self, renderer_type: RendererType) -> None:
        if renderer_type == RendererType.QT:
            from composeui.qtrenderer import QtLogFormRowRenderer  # noqa: PLC0415

            self.renderer = QtLogFormRowRenderer(self)


@define_view
class LabelView(View):
    text: str = attrs.field(default="")

    def _create_renderer(self, renderer_type: RendererType) -> None:
        if renderer_type == RendererType.QT:
            from composeui.qtrenderer import QtLabelRenderer  # noqa: PLC0415

            self.renderer = QtLabelRenderer(self)


TValue = TypeVar("TValue")


@define_view
class RadioGroupView(View, Generic[TValue]):
    value: TValue | None = attrs.field(default=None)
    values: dict[str, TValue] = attrs.field(
        factory=dict[str, TValue],
        on_setattr=attrs.setters.frozen,
    )
    value_changed: Signal = attrs.Factory(Signal)

    def _create_renderer(self, renderer_type: RendererType) -> None:
        if renderer_type == RendererType.QT:
            from composeui.qtrenderer import QtRadioGroupRenderer  # noqa: PLC0415

            self.renderer = QtRadioGroupRenderer(self)


TView = TypeVar("TView", bound=View)


@define_view
class FormRowView(View, Generic[TView]):
    log_view: LogFormRow = attrs.field(factory=LogFormRow)
    field_view: TView = attrs.field(kw_only=True, init=False)

    def __attrs_post_init__(self) -> None:
        self.log_view.is_visible = False

    def _create_renderer(self, renderer_type: RendererType) -> None:
        pass


@define_view
class LabelFormRowView(FormRowView[TView]):
    label_view: LabelView = attrs.field(factory=LabelView)


@define_view
class LabelInputRowView(LabelFormRowView[InputView]):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.field_view = InputView()


@define_view
class LabelFloatInputRowView(LabelFormRowView[FloatInputView]):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.field_view = FloatInputView()


@define_view
class LabelRadioGroupRowView(LabelFormRowView[RadioGroupView[TValue]]):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.field_view = RadioGroupView()


@define_view
class FormView(View):
    log_view: LogFormRow = attrs.field(factory=LogFormRow)

    def __attrs_post_init__(self) -> None:
        self.log_view.is_visible = False

    @property
    def field_rows(self) -> list[FormRowView[View] | FormView]:
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

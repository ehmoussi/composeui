from __future__ import annotations

import enum
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Generic, TypeVar, overload

import attrs
from attr import define, field

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
        return define(cls, on_setattr=[notify_renderer], **kwargs)

    if cls is None:
        return wrap
    return wrap(cls)


@define_view(kw_only=True)
class View:
    # properties
    is_visible: bool = field(default=True)
    is_enabled: bool = field(default=True)
    # renderer
    renderer: Renderer[Any, Any] | None = field(default=None)

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
    title: str = field(init=False, on_setattr=attrs.setters.frozen)
    extension: str = field(init=False, on_setattr=attrs.setters.frozen)
    saved_filepath: Path | None = None

    minimum_width: int = field(default=720)
    minimum_height: int = field(default=480)

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
    placeholder: str = field(default="")
    # signals
    editing_finished: Signal = field(factory=Signal)
    text_changed: Signal = field(factory=Signal)
    text_edited: Signal = field(factory=Signal)


@define_view
class InputView(_InputView):
    # properties
    text: str = field(default="")

    def _create_renderer(self, renderer_type: RendererType) -> None:
        if renderer_type == RendererType.QT:
            from composeui.qtrenderer import QtInputRenderer  # noqa: PLC0415

            self.renderer = QtInputRenderer(self)


@define_view
class FloatInputView(_InputView):
    # properties
    value: float | None = field(default=None)
    minimum: float | None = field(default=None)
    maximum: float | None = field(default=None)
    decimals: int | None = field(default=None)

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
    log_message: str = field(default="")
    log_type: LogType = field(default=LogType.ERROR)

    def _create_renderer(self, renderer_type: RendererType) -> None:
        if renderer_type == RendererType.QT:
            from composeui.qtrenderer import QtLogFormRowRenderer  # noqa: PLC0415

            self.renderer = QtLogFormRowRenderer(self)


@define_view
class LabelView(View):
    text: str = field(default="")

    def _create_renderer(self, renderer_type: RendererType) -> None:
        if renderer_type == RendererType.QT:
            from composeui.qtrenderer import QtLabelRenderer  # noqa: PLC0415

            self.renderer = QtLabelRenderer(self)


TView = TypeVar("TView", bound=View)


@define_view
class FormRowView(View, Generic[TView]):
    log_view: LogFormRow = field(factory=LogFormRow)
    field_view: TView = field(kw_only=True, init=False)

    def __attrs_post_init__(self) -> None:
        self.log_view.is_visible = False

    def _create_renderer(self, renderer_type: RendererType) -> None:
        pass


@define_view
class LabelFormRowView(FormRowView[TView]):
    label_view: LabelView = field(factory=LabelView)


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
class FormView(View):
    log_view: LogFormRow = field(factory=LogFormRow)

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
    title: str = field(default="")

    def _create_renderer(self, renderer_type: RendererType) -> None:
        if renderer_type == RendererType.QT:
            from composeui.qtrenderer import QtGroupFormRenderer  # noqa: PLC0415

            self.renderer = QtGroupFormRenderer(self)

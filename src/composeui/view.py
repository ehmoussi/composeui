from __future__ import annotations

import enum
from typing import TYPE_CHECKING, Any

import attrs
from attr import define, field

from composeui.signal import Signal

if TYPE_CHECKING:
    from composeui.renderer import Renderer


class RendererType(enum.Enum):
    QT = enum.auto()


@define(kw_only=True)
class View:
    # properties
    is_visible: bool = field(default=True)
    is_enabled: bool = field(default=True)
    # renderer
    renderer: Renderer[Any, Any] | None = field(default=None)

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
        """Render all the children views."""
        raise NotImplementedError


@define
class InputView(View):
    # properties
    text: str = field(default="")
    placeholder: str = field(default="")
    # signals
    editing_finished: Signal = field(factory=Signal)
    text_changed: Signal = field(factory=Signal)
    text_edited: Signal = field(factory=Signal)

    def _create_renderer(self, renderer_type: RendererType) -> None:
        if renderer_type == RendererType.QT:
            from composeui.qtrenderer import QtInputRenderer  # noqa: PLC0415

            self.renderer = QtInputRenderer(self)

    def _render_children(self, renderer_type: RendererType) -> None:
        pass


class LogType(enum.Enum):
    ERROR = enum.auto()
    WARNING = enum.auto()
    INFO = enum.auto()


@define
class LogFormRow(View):
    log_message: str = field(default="")
    log_type: LogType = field(default=LogType.ERROR)

    def _create_renderer(self, renderer_type: RendererType) -> None:
        if renderer_type == RendererType.QT:
            from composeui.qtrenderer import QtLogFormRowRenderer  # noqa: PLC0415

            self.renderer = QtLogFormRowRenderer(self)

    def _render_children(self, renderer_type: RendererType) -> None:
        pass


@define
class LabelView(View):
    text: str = field(default="")

    def _create_renderer(self, renderer_type: RendererType) -> None:
        if renderer_type == RendererType.QT:
            from composeui.qtrenderer import QtLabelRenderer  # noqa: PLC0415

            self.renderer = QtLabelRenderer(self)

    def _render_children(self, renderer_type: RendererType) -> None:
        pass


@define
class FormRowView(View):
    log_view: LogFormRow = field(factory=LogFormRow)
    field_view: View = field(kw_only=True)

    def _create_renderer(self, renderer_type: RendererType) -> None:
        pass

    def _render_children(self, renderer_type: RendererType) -> None:
        self.log_view.render(renderer_type)
        self.field_view.render(renderer_type)


@define
class LabelFormRowView(FormRowView):
    label_view: LabelView = field(factory=LabelView)

    def _render_children(self, renderer_type: RendererType) -> None:
        super()._render_children(renderer_type)
        self.label_view.render(renderer_type)


@define
class FormView(View):
    @property
    def field_rows(self) -> list[FormRowView]:
        """Get all the field rows of the form view."""
        return [
            getattr(self, field_row_attr.name)
            for field_row_attr in attrs.fields(type(self))
            if isinstance(getattr(self, field_row_attr.name), FormRowView)
        ]

    def _create_renderer(self, renderer_type: RendererType) -> None:
        if renderer_type == RendererType.QT:
            from composeui.qtrenderer import QtFormRenderer  # noqa: PLC0415

            self.renderer = QtFormRenderer(self)

    def _render_children(self, renderer_type: RendererType) -> None:
        for field_row_attr in attrs.fields(type(self)):
            field_row = getattr(self, field_row_attr.name)
            if isinstance(field_row, View):
                field_row.render(renderer_type)

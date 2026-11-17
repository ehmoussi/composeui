"""Textual forms and the widget lookup that assembles form rows."""

from __future__ import annotations

import weakref
from typing import TYPE_CHECKING, Any

from textual.containers import Vertical
from textual.content import Content
from textual.widgets import Label

from composeui.core.renderer import RendererContainer
from composeui.core.view import FormLabelRowView, FormRowView, FormView, GroupFormView, View
from composeui.textualcore._renderers.content import TextualLogRenderer
from composeui.textualcore.textualrenderer import TextualWidgetRenderer

if TYPE_CHECKING:
    from textual.widget import Widget


class TextualFormLabelRenderer(TextualWidgetRenderer[FormLabelRowView, Label]):
    """A form row's label, then the row's help as a dimmed hint under it.

    A hint rather than a tooltip, which only the mouse shows.
    """

    def __init__(self, view: FormLabelRowView) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "label": self._refresh_text,
                "help": self._refresh_help,
            }
        )

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = Label()

    @staticmethod
    def _refresh_text(view: FormLabelRowView, rendered_object: Label, value: str) -> None:
        rendered_object.update(TextualFormLabelRenderer._content(value, view.help))

    @staticmethod
    def _refresh_help(view: FormLabelRowView, rendered_object: Label, value: str) -> None:
        rendered_object.update(TextualFormLabelRenderer._content(view.label, value))

    @staticmethod
    def _content(label: str, help_text: str) -> Content:
        if help_text == "":
            return Content(label)
        return Content.assemble(label, "\n", (help_text, "dim"))


#: the widgets of the form rows shown outside a form, by their rows' renderers: built once,
#: as a widget has one parent, and gone with the row
_ROW_WIDGETS: weakref.WeakKeyDictionary[RendererContainer[Any], Widget] = (
    weakref.WeakKeyDictionary()
)


def _widget_of(view: View) -> Widget | None:
    """Get the widget showing `view` in a layout; a form row's anywhere, as a form shows it.

    None when this backend doesn't render `view`.
    """
    renderer = view.renderer
    if isinstance(view, FormRowView) and isinstance(renderer, RendererContainer):
        widget = _ROW_WIDGETS.get(renderer)
        if widget is None:
            widget = TextualFormRenderer.row_widget(view, renderer)
            _ROW_WIDGETS[renderer] = widget
        return widget
    if isinstance(renderer, TextualWidgetRenderer):
        return renderer.widget
    return None


class TextualFormRenderer(TextualWidgetRenderer[FormView, Vertical]):
    def render(self) -> None:
        if self._rendered_object is None:
            # its rows and its other views, e.g. a table; a view this backend doesn't
            # register is left out
            rows = [
                widget
                for view in self._view.content_views
                if (widget := _widget_of(view)) is not None
            ]
            log = self._view.log_view.renderer
            assert isinstance(log, TextualWidgetRenderer)
            assert log.widget is not None
            rows.append(log.widget)
            self._rendered_object = Vertical(*rows)
            self._rendered_object.styles.height = "auto"

    @classmethod
    def row_widget(cls, row: FormRowView, row_renderer: RendererContainer[View]) -> Widget:
        """Get a new widget showing `row`: its label, above its field and its message."""
        row_widgets: list[Widget] = []
        if isinstance(row, FormLabelRowView):
            row_widgets.append(cls._get_label_widget(row_renderer))
        row_widgets.append(cls._get_field_widget(row_renderer))
        row_widgets.append(cls._get_log_widget(row_renderer))
        widget = Vertical(*row_widgets)
        # `Vertical`'s default `height: 1fr` stretches to fill its parent
        # instead of sizing to its content, which quietly defeats
        # `VerticalScroll` (nothing ever appears to overflow the viewport).
        widget.styles.height = "auto"
        return widget

    @staticmethod
    def _get_field_widget(field_row_renderer: RendererContainer[View]) -> Widget:
        field_renderer = field_row_renderer.get_renderer("field")
        assert isinstance(field_renderer, TextualWidgetRenderer)
        assert field_renderer.widget is not None
        return field_renderer.widget

    @staticmethod
    def _get_log_widget(field_row_renderer: RendererContainer[View]) -> Widget:
        log_renderer = field_row_renderer.get_renderer("log")
        assert isinstance(log_renderer, TextualLogRenderer)
        assert log_renderer.widget is not None
        return log_renderer.widget

    @staticmethod
    def _get_label_widget(field_row_renderer: RendererContainer[View]) -> Widget:
        label_renderer = field_row_renderer.get_renderer("label")
        assert isinstance(label_renderer, TextualFormLabelRenderer)
        assert label_renderer.widget is not None
        return label_renderer.widget


class TextualGroupFormRenderer(TextualFormRenderer):
    def __init__(self, view: GroupFormView) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "title": self._refresh_title,
            }
        )

    def render(self) -> None:
        is_first_render = self._rendered_object is None
        super().render()
        if is_first_render:
            assert self._rendered_object is not None
            # `border_title` has no effect without an actual border to attach it to -
            # without this, every group (e.g. pipeform.py's "Main Pipe"/"Incident Pipe")
            # renders as a plain, undecorated box indistinguishable from the rest of
            # the form, and adjacent groups run into each other with no separation.
            self._rendered_object.styles.border = ("round", "gray")
            self._rendered_object.styles.padding = (0, 1)

    @staticmethod
    def _refresh_title(_view: FormView, rendered_object: Vertical, value: str) -> None:
        rendered_object.border_title = Content(value)

"""The web renderers of forms: a form, a group of rows, and a row's label."""

from __future__ import annotations

from typing import Any

from markupsafe import Markup

from composeui.core.renderer import RendererContainer
from composeui.core.view import FormLabelRowView, FormView, GroupFormView
from composeui.webcore.changes import _DIRTY
from composeui.webcore.webrenderer import WebRenderer, _fragment, _icon, _view_html


class WebFormLabelRenderer(WebRenderer[FormLabelRowView]):
    """The label of a form row, pointing at the row's field for clicks/screen readers.

    With help, a "?" button beside the label opens it in a popover: a click, a tap, or
    Enter once Tab reached it, as hovering can't on a phone. The button is outside the
    `<label>`, so it isn't part of the field's name.
    """

    _role = "form_label"

    def __init__(self, view: FormLabelRowView) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "label": self._mark_dirty,
                "help": self._refresh_help,
                "help_button_text": self._mark_dirty,
            }
        )

    @property
    def text_id(self) -> str:
        """The id of the ``<label>`` itself, which names a field ``<label for>`` can't."""
        return f"{self.widget_id}-text"

    @property
    def help_id(self) -> str:
        """The id of the row's help, which describes the field while there is help."""
        return f"{self.widget_id}-help"

    def has_help(self) -> bool:
        return self._view.help != ""

    def to_html(self, *, oob: bool = False) -> Markup:
        field = self._field_renderer()
        # a radio group or a checkbox is a `<div>`, which isn't labelable: its
        # `aria-labelledby` names it instead
        target = Markup(' for="{}"').format(field.widget_id) if field.is_labelable else ""
        return Markup(
            '<div {root_attributes} class="flex items-center gap-1">'
            '<label id="{text_id}"{target}'
            ' class="label text-sm font-medium text-base-content"'
            ">{label}</label>{help_html}</div>"
        ).format(
            root_attributes=self._root_attributes(oob=oob),
            text_id=self.text_id,
            target=target,
            label=self._view.label,
            help_html=self._help_html(),
        )

    def _help_html(self) -> Markup:
        """Render the "?" button and the help it opens, which also describes the field.

        Closed, the popover is hidden, which `aria-describedby` still reads. The page's
        script places it beside the button (see `page.js`).
        """
        if not self.has_help():
            return Markup()
        return Markup(
            '<button type="button" popovertarget="{help_id}"'
            ' class="inline-flex cursor-pointer rounded-full text-base-content/40'
            " transition-colors hover:text-primary focus-visible:text-primary"
            ' focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"'
            ' aria-label="{help_button_text}">{help_icon}</button>'
            # `cui-help`: the arrow pointing at the button, see `css/app.css`
            '<div id="{help_id}" popover data-help class="cui-help m-0 w-max max-w-80'
            " rounded-field border border-base-300 bg-base-100 px-3 py-2 text-xs"
            ' leading-relaxed text-base-content shadow-lg">'
            "{help}</div>"
        ).format(
            help_id=self.help_id,
            help_button_text=self._view.help_button_text,
            help_icon=_icon("help"),
            help=self._view.help,
        )

    def _refresh_help(self, view: FormLabelRowView, rendered_object: str, value: str) -> None:
        self._mark_dirty(view, rendered_object, value)
        dirty = _DIRTY.get()
        if dirty is not None and (view.help == "") != (value == ""):
            # its `aria-describedby` gains or loses the help
            field = self._field_renderer()
            dirty[field.widget_id] = field

    def _field_renderer(self) -> WebRenderer[Any]:
        assert isinstance(self._view.renderer, RendererContainer)  # a row's label's
        field_renderer = self._view.renderer.get_renderer("field")
        assert isinstance(field_renderer, WebRenderer)
        return field_renderer


class WebFormRenderer(WebRenderer[FormView]):
    """A form: each row's label, field and log stacked together, then the form's log.

    A `<fieldset>`, so disabling the form disables every control in it, as disabling a
    Qt container disables its children. Rows have no fragment of their own: each of a
    row's renderers hides itself when the row does, and swaps on its own.
    """

    _role = "form"

    def render(self) -> None:
        super().render()
        self._adopt(self._view.children_views)

    def to_html(self, *, oob: bool = False) -> Markup:
        return self._fieldset(oob=oob, classes="flex min-w-0 flex-col gap-5", legend="")

    def _fieldset(self, *, oob: bool, classes: str, legend: str) -> Markup:
        disabled = "" if self.is_enabled else " disabled"
        # its rows and its other views, e.g. a table; a view this backend doesn't support:
        # empty
        rows = Markup("").join(_view_html(view) for view in self._view.content_views)
        return Markup(
            "<fieldset {root_attributes}"
            ' class="{classes}"{disabled}>{legend}{rows}{fragment}</fieldset>'
        ).format(
            root_attributes=self._root_attributes(oob=oob),
            classes=classes,
            disabled=disabled,
            legend=legend,
            rows=rows,
            fragment=_fragment(self._view.log_view.renderer),
        )


class WebGroupFormRenderer(WebFormRenderer):
    """A titled group of rows, e.g. `pipeform.py`'s "Main Pipe"."""

    _role = "group_form"

    def __init__(self, view: GroupFormView) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update({"title": self._mark_dirty})

    def to_html(self, *, oob: bool = False) -> Markup:
        title = self._view.title if isinstance(self._view, GroupFormView) else ""
        return self._fieldset(
            oob=oob,
            classes="fieldset form-grid min-w-0 gap-4 rounded-box border border-base-300"
            " bg-base-200 p-4",
            legend=(
                Markup(
                    '<legend class="fieldset-legend px-1 text-sm font-semibold text-primary">'
                    "{}</legend>"
                ).format(title)
            ),
        )

"""The web renderers of dialogs: a message or question, and a form in a dialog."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from markupsafe import Markup

from composeui.core.view import DialogKind, DialogView, OkCancelDialogView

if TYPE_CHECKING:
    from collections.abc import Mapping

from composeui.webcore.webrenderer import WebRenderer, _view_html


class WebDialogRenderer(WebRenderer[DialogView]):
    """A modal `<dialog>`, opened by the page's script once swapped in shown.

    The main renderer puts every dialog at the end of the page, outside any page's
    slot, which hides its content. A button closes the dialog in the browser, so focus
    goes back where it was, then posts its answer; Escape posts a dismissal. The
    server then swaps the dialog closed: it isn't the button's own fragment, and is
    closed already.
    """

    #: its `dispatch` decides by event: a second click on a dialog just closed does nothing
    @property
    def takes_events(self) -> bool:
        return True

    _role = "dialog"
    is_drawn_apart = True

    def __init__(self, view: DialogView) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            dict.fromkeys(
                ("title", "text", "kind", "accept_text", "reject_text", "is_destructive"),
                self._mark_dirty,
            )
        )

    def to_html(self, *, oob: bool = False) -> Markup:
        view = self._view
        title_id = f"{self.widget_id}-title"
        text_id = f"{self.widget_id}-text"
        disabled = "" if self.is_enabled else " disabled"
        is_confirm = view.kind is DialogKind.CONFIRM
        # a destructive confirmation focuses its rejecting button: Enter mustn't lose anything
        is_safe_first = is_confirm and view.is_destructive
        reject = (
            self._button_html("reject", view.reject_text, "btn", disabled, is_focused=is_safe_first)
            if is_confirm
            else ""
        )
        accept = self._button_html(
            "accept",
            view.accept_text,
            "btn btn-error" if is_safe_first else "btn btn-primary",
            disabled,
            is_focused=not is_safe_first,
        )
        # a disabled dialog can't be closed: its answer would be ignored
        cancel = (
            Markup(
                ' hx-post="/widget/{}" hx-trigger="cancel"'
                """ hx-vals='{{"event": "dismiss"}}'"""
            ).format(self.widget_id)
            if self.is_enabled
            else " data-keep-open"
        )
        title = (
            Markup('<h2 id="{}" class="text-lg font-bold">{}</h2>').format(title_id, view.title)
            if view.title
            else ""
        )
        labelledby = Markup(' aria-labelledby="{}"').format(title_id) if view.title else ""
        return Markup(
            '<dialog {root_attributes} class="modal" data-dialog'
            '{labelledby} aria-describedby="{text_id}"{cancel} hx-swap="none">'
            '<div class="modal-box">{title}'
            '<p id="{text_id}" class="py-4 whitespace-pre-line">{text}</p>'
            '<div class="modal-action">{reject}{accept}</div></div></dialog>'
        ).format(
            root_attributes=self._root_attributes(oob=oob),
            labelledby=labelledby,
            text_id=text_id,
            cancel=cancel,
            title=title,
            text=view.text,
            reject=reject,
            accept=accept,
        )

    def _button_html(
        self, event: str, text: str, classes: str, disabled: str, *, is_focused: bool
    ) -> Markup:
        # the dialog's own `close`, not `cancel`: no dismissal posted on top of the answer
        autofocus = " autofocus" if is_focused else ""
        return Markup(
            '<button type="button" class="{classes}" hx-post="/widget/{widget_id}"'
            """ hx-vals='{{"event": "{event}"}}'"""
            " data-close-dialog{autofocus}{disabled}>"
            "{text}</button>"
        ).format(
            classes=classes,
            widget_id=self.widget_id,
            event=event,
            autofocus=autofocus,
            disabled=disabled,
            text=text,
        )

    def dispatch(self, event: str, form: Mapping[str, str]) -> None:
        answers = {
            "accept": self._view.accept,
            "reject": self._view.reject,
            "dismiss": self._view.dismiss,
        }
        answer = answers.get(event)
        if answer is None:
            super().dispatch(event, form)  # raises: no answer of a dialog's
        elif self.is_enabled:
            answer()


class WebFormDialogRenderer(WebDialogRenderer):
    """A modal `<dialog>` holding its form or other view, then Cancel and OK.

    OK is disabled while the view says so, e.g. while a check of the form fails, and only
    it swaps when that changes.
    The dialog itself, swapped while open, would take back what the user is typing.
    Unlike a message's, OK doesn't close the dialog in the browser: the form may refuse
    it, the dialog then staying open with its checks shown. The server swaps it closed
    once accepted. Cancel and Escape close it first, as for any dialog.
    """

    _role = "form_dialog"

    def __init__(self, view: OkCancelDialogView) -> None:
        super().__init__(view)
        self._form_view = view
        #: whether more than OK changed since the dialog was last sent: then it swaps whole
        self._is_whole = False
        self._refresh_dispatcher["is_accept_enabled"] = self._refresh_accept
        self._refresh_dispatcher["has_failing_check"] = self._refresh_accept

    def render(self) -> None:
        super().render()
        view = self._form_view
        self._adopt([view.content, view.log_view, *view.buttons])

    @property
    def accept_id(self) -> str:
        return f"{self.widget_id}-accept"

    def to_html(self, *, oob: bool = False) -> Markup:
        is_whole, self._is_whole = self._is_whole, False
        if oob and not is_whole:
            return self._accept_html(oob=True)
        view = self._form_view
        title_id = f"{self.widget_id}-title"
        text_id = f"{self.widget_id}-text"
        disabled = "" if self.is_enabled else " disabled"
        reject = self._button_html("reject", view.reject_text, "btn", disabled, is_focused=False)
        cancel = (
            Markup(
                ' hx-post="/widget/{}" hx-trigger="cancel"'
                """ hx-vals='{{"event": "dismiss"}}'"""
            ).format(self.widget_id)
            if self.is_enabled
            else " data-keep-open"
        )
        title = (
            Markup('<h2 id="{}" class="text-lg font-bold">{}</h2>').format(title_id, view.title)
            if view.title
            else ""
        )
        text = (
            Markup('<p id="{}" class="whitespace-pre-line">{}</p>').format(text_id, view.text)
            if view.text
            else ""
        )
        labelledby = Markup(' aria-labelledby="{}"').format(title_id) if view.title else ""
        describedby = Markup(' aria-describedby="{}"').format(text_id) if view.text else ""
        form_html = _view_html(view.content)
        log_html = _view_html(view.log_view)
        buttons = Markup("").join(_view_html(button) for button in view.buttons)
        return Markup(
            '<dialog {root_attributes} class="modal" data-dialog'
            '{labelledby}{describedby}{cancel} hx-swap="none">'
            '<div class="modal-box flex flex-col gap-4">{title}{text}{form_html}{log_html}'
            '<div class="modal-action">{reject}{buttons}{accept_html}</div>'
            "</div></dialog>"
        ).format(
            root_attributes=self._root_attributes(oob=oob),
            labelledby=labelledby,
            describedby=describedby,
            cancel=cancel,
            title=title,
            text=text,
            form_html=form_html,
            log_html=log_html,
            reject=reject,
            buttons=buttons,
            accept_html=self._accept_html(oob=False),
        )

    def _accept_html(self, *, oob: bool) -> Markup:
        swap = Markup(' hx-swap-oob="true"') if oob else ""
        disabled = "" if self.is_enabled and self._form_view.can_accept else " disabled"
        return Markup(
            '<button id="{accept_id}" type="button" class="btn btn-primary"{swap}'
            ' hx-post="/widget/{widget_id}"'
            """ hx-vals='{{"event": "accept"}}'{disabled}>"""
            "{accept_text}</button>"
        ).format(
            accept_id=self.accept_id,
            swap=swap,
            widget_id=self.widget_id,
            disabled=disabled,
            accept_text=self._form_view.accept_text,
        )

    def _refresh_accept(self, view: DialogView, rendered_object: str, value: Any) -> None:
        super()._mark_dirty(view, rendered_object, value)

    def _mark_dirty(self, view: DialogView, rendered_object: str, value: Any) -> None:
        self._is_whole = True
        super()._mark_dirty(view, rendered_object, value)

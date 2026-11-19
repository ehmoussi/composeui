"""Textual message and content dialogs."""

from __future__ import annotations

import functools
from typing import TYPE_CHECKING, Any

from textual.content import Content

from composeui.core.renderer import Renderer
from composeui.core.view import DialogKind, DialogView, OkCancelDialogView
from composeui.textualcore._renderers.forms import _widget_of
from composeui.textualcore.textualrenderer import _call_on_app_thread, _refresh_tree
from composeui.textualcore.widgets.composedialog import ComposeDialog
from composeui.textualcore.widgets.composeformdialog import ComposeFormDialog

if TYPE_CHECKING:
    from collections.abc import Callable

    from composeui.textualcore._renderers.actions import _ComposeUIApp


class TextualDialogRenderer(Renderer[DialogView, DialogView]):
    """No widget in the screen: a modal screen pushed while the dialog is open.

    A screen popped from the app can't be pushed again, so each opening pushes a new
    one, built from the view.
    """

    def __init__(self, view: DialogView) -> None:
        super().__init__(view)
        #: set by `TextualMainRenderer` once it has built the app
        self.app: _ComposeUIApp | None = None
        #: the screen showing the dialog, while open
        self.screen: ComposeDialog | None = None
        self._refresh_dispatcher.update(
            {
                "is_visible": self._refresh_visible,
                "is_enabled": self._refresh_enabled,
                "title": self._refresh_title,
                "text": self._refresh_text,
                "kind": self._refresh_kind,
                "accept_text": self._refresh_accept_text,
                "reject_text": self._refresh_reject_text,
                "is_destructive": self._refresh_is_destructive,
            }
        )

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = self._view

    def call_on_main_thread(self, callback: Callable[[], None]) -> None:
        _call_on_app_thread(self.app, callback)

    def refresh(self) -> None:
        # see `TextualWidgetRenderer.refresh`
        self.call_on_main_thread(super().refresh)

    def refresh_attribute(self, attr_name: str, value: Any) -> None:
        self.call_on_main_thread(functools.partial(super().refresh_attribute, attr_name, value))

    def _refresh_visible(self, view: DialogView, _rendered_object: DialogView, value: bool) -> None:
        app = self.app
        # opened before the app runs: its mount refreshes the tree again
        if app is None or not app.is_running:
            return
        if value and self.screen is None:
            screen = ComposeDialog(view)
            self.screen = screen
            app.push_screen(screen, functools.partial(self._answer, screen))
        elif not value and self.screen is not None:
            screen, self.screen = self.screen, None
            # no longer `self.screen`: `_answer` ignores its dismissal
            if screen.is_active:
                screen.dismiss()
            else:  # dismissing it now would pop the screen above it
                screen.closed_while_covered = True

    def _answer(self, screen: ComposeDialog, answer: bool | None) -> None:
        if screen is not self.screen:
            return  # closed by the app, not the user
        self.screen = None
        if answer is None:
            self._view.dismiss()
        elif answer:
            self._view.accept()
        else:
            self._view.reject()

    def _refresh_enabled(
        self, _view: DialogView, _rendered_object: DialogView, value: bool
    ) -> None:
        if self.screen is not None:
            self.screen.set_enabled(is_enabled=value)

    def _refresh_title(self, _view: DialogView, _rendered_object: DialogView, value: str) -> None:
        if self.screen is not None:
            self.screen.title_label.update(value)
            self.screen.title_label.display = value != ""

    def _refresh_text(self, _view: DialogView, _rendered_object: DialogView, value: str) -> None:
        if self.screen is not None:
            self.screen.text_label.update(value)

    def _refresh_kind(
        self, view: DialogView, _rendered_object: DialogView, value: DialogKind
    ) -> None:
        if self.screen is not None:
            self.screen.reject_button.display = value is DialogKind.CONFIRM
            self.screen.show_safe_button(kind=value, is_destructive=view.is_destructive)

    def _refresh_is_destructive(
        self, view: DialogView, _rendered_object: DialogView, value: bool
    ) -> None:
        if self.screen is not None:
            self.screen.show_safe_button(kind=view.kind, is_destructive=value)

    def _refresh_accept_text(
        self, _view: DialogView, _rendered_object: DialogView, value: str
    ) -> None:
        if self.screen is not None:
            self.screen.accept_button.label = Content(value)

    def _refresh_reject_text(
        self, _view: DialogView, _rendered_object: DialogView, value: str
    ) -> None:
        if self.screen is not None:
            self.screen.reject_button.label = Content(value)


class TextualFormDialogRenderer(TextualDialogRenderer):
    """A modal screen holding the form or other view, installed once: pushed open, popped closed.

    The view's widgets are built once, so its screen is too, unlike a message's. OK is
    disabled while the view says so, e.g. while a check of the form fails. The view closes
    the dialog once it accepts the answer, so OK on a form refusing it leaves the screen up.
    """

    def __init__(self, view: OkCancelDialogView) -> None:
        super().__init__(view)
        self._form_view = view
        self.form_screen: ComposeFormDialog | None = None
        self._refresh_dispatcher["is_accept_enabled"] = self._refresh_is_accept_enabled
        self._refresh_dispatcher["has_failing_check"] = self._refresh_has_failing_check
        self._refresh_dispatcher["is_destructive"] = self._refresh_kind

    def render(self) -> None:
        if self._rendered_object is None:
            super().render()
            view = self._form_view
            content = _widget_of(view.content)
            assert content is not None
            log = _widget_of(view.log_view)
            assert log is not None
            buttons = [_widget_of(button) for button in view.buttons]
            self.form_screen = ComposeFormDialog(
                content, log, [button for button in buttons if button is not None]
            )
            self.form_screen.answered.connect(self._answer_form)
            # its form's widgets mount with it, first pushed: their state only then
            self.form_screen.mounted.connect(self._refresh_screen)
            self.form_screen.resumed.connect(self._pop_if_closed)

    def _refresh_screen(self) -> None:
        view = self._form_view
        for shown in (view.content, view.log_view, *view.buttons):
            _refresh_tree(shown)
        self.refresh()  # the screen's title, text and buttons

    def _pop_if_closed(self) -> None:
        """Pop the screen uncovered, if the app closed its dialog under another one."""
        app, screen = self.app, self.form_screen
        if (
            app is not None
            and screen is not None
            and screen.is_active
            and not self._view.is_visible
        ):
            app.pop_screen()

    def _answer_form(self, answer: str) -> None:
        {"accept": self._view.accept, "reject": self._view.reject}.get(answer, self._view.dismiss)()

    def _refresh_visible(self, view: DialogView, _rendered_object: DialogView, value: bool) -> None:
        app, screen = self.app, self.form_screen
        # opened before the app runs: its mount refreshes the tree again
        if app is None or not app.is_running:
            return
        assert screen is not None
        if value and screen not in app.screen_stack:  # closed while covered, it's still there
            name = f"cui-{id(view)}-dialog"
            if not app.is_screen_installed(screen):
                app.install_screen(screen, name)
            app.push_screen(name)
        elif not value and screen.is_active:  # covered: `_pop_if_closed`, once uncovered
            app.pop_screen()

    def _refresh_enabled(
        self, _view: DialogView, _rendered_object: DialogView, value: bool
    ) -> None:
        assert self.form_screen is not None
        self.form_screen.reject_button.disabled = not value
        self.form_screen.accept_button.disabled = not (value and self._form_view.can_accept)

    def _refresh_title(self, _view: DialogView, _rendered_object: DialogView, value: str) -> None:
        assert self.form_screen is not None
        self.form_screen.title_label.update(value)
        self.form_screen.title_label.display = value != ""

    def _refresh_text(self, _view: DialogView, _rendered_object: DialogView, value: str) -> None:
        assert self.form_screen is not None
        self.form_screen.text_label.update(value)
        self.form_screen.text_label.display = value != ""

    def _refresh_kind(self, _view: DialogView, _rendered_object: DialogView, _value: Any) -> None:
        pass  # always OK and Cancel: a form is confirmed or not

    def _refresh_accept_text(
        self, _view: DialogView, _rendered_object: DialogView, value: str
    ) -> None:
        assert self.form_screen is not None
        self.form_screen.accept_button.label = Content(value)

    def _refresh_reject_text(
        self, _view: DialogView, _rendered_object: DialogView, value: str
    ) -> None:
        assert self.form_screen is not None
        self.form_screen.reject_button.label = Content(value)

    # each is told its own field's new value, not yet the view's
    def _refresh_is_accept_enabled(
        self, _view: DialogView, _rendered_object: DialogView, value: bool
    ) -> None:
        self._enable_accept(is_accepted=value and not self._form_view.has_failing_check)

    def _refresh_has_failing_check(
        self, _view: DialogView, _rendered_object: DialogView, value: bool
    ) -> None:
        self._enable_accept(is_accepted=self._form_view.is_accept_enabled and not value)

    def _enable_accept(self, *, is_accepted: bool) -> None:
        assert self.form_screen is not None
        self.form_screen.accept_button.disabled = not (is_accepted and self._view.is_enabled)

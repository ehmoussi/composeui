"""Textual actions, menu buttons, toolbars and the app that dispatches their events."""

from __future__ import annotations

import dataclasses
import functools
import threading
from collections import deque
from typing import TYPE_CHECKING, Any, TypeVar

from textual.app import App, ComposeResult
from textual.content import Content
from textual.widgets import Footer
from typing_extensions import override

from composeui.core._views.actions import OpenFileAction, SaveAction, SaveAsAction
from composeui.core.renderer import Renderer, ViewLike
from composeui.core.view import (
    ActionView,
    ButtonVariant,
    MainView,
    Menu,
    MenuButtonView,
    PickFileAction,
    SeparatorAction,
    ToolBar,
    View,
)
from composeui.textualcore._renderers.controls import _BUTTON_VARIANTS
from composeui.textualcore.textualrenderer import (
    TextualWidgetRenderer,
    _app_of,
    _call_on_app_thread,
    _refresh_tree,
)
from composeui.textualcore.widgets.composebutton import ComposeButton
from composeui.textualcore.widgets.composemenubutton import ComposeMenuPopup
from composeui.textualcore.widgets.composetoolbar import (
    ComposeToolbar,
    ComposeToolbarButton,
    ComposeToolbarSeparator,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from textual.widget import Widget


TNoopView = TypeVar("TNoopView", bound=ViewLike)


class _TextualNoopRenderer(Renderer[TNoopView, TNoopView]):
    """A renderer with no widget of its own - just a placeholder in the view tree.

    Used for `Menu`/`ActionView`/`SeparatorAction`, which don't render as widgets under
    Textual (see `_ComposeUIApp`/`TextualMainRenderer.open_file`). Still needs
    `is_visible`/`is_enabled` dispatch entries (even as no-ops) because `Menu.
    __attrs_post_init__` sets `is_visible = False` and `notify_renderer` would otherwise
    raise `MissingRefreshAttributeFunctionError` the first time either is set again.
    """

    def __init__(self, view: TNoopView) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "is_visible": self._noop,
                "is_enabled": self._noop,
            }
        )

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = self._view

    @staticmethod
    def _noop(_view: TNoopView, _rendered_object: TNoopView, _value: Any) -> None:
        pass


class TextualActionRenderer(_TextualNoopRenderer[ActionView]):
    """No widget of its own: key bindings + `Footer` entries, or toolbar buttons.

    `_ComposeUIApp` turns actions with a shortcut into key bindings, and a toolbar, or a
    router's for its pages' actions, shows them as buttons.
    """

    def __init__(self, view: ActionView) -> None:
        super().__init__(view)
        #: set once `_register_actions` has bound the action to a key
        self.app: _ComposeUIApp | None = None
        #: set by the toolbar showing the action (`TextualToolBarRenderer`, or
        #: `TextualRouterRenderer` for a page's action): its button
        self.button: ComposeToolbarButton | None = None
        #: set by the menu button listing the action: the action's key works only while it
        #: does, as on Qt and the web
        self.menu_button: ComposeButton | None = None
        self._refresh_dispatcher.update(
            {
                name: functools.partial(self._refresh_label, name)
                for name in ("text", "is_checkable", "is_checked")
            }
        )
        self._refresh_dispatcher.update(
            {
                "is_visible": self._refresh_button_visible,
                "is_enabled": self._refresh_button_enabled,
                "shortcut": self._refresh_shortcut,
                # nothing shows them: a toolbar button shows its text, the app reads data
                "icon": self._noop,
                "data": self._noop,
            }
        )
        if isinstance(view, PickFileAction):
            # read by the picker each time it opens
            self._refresh_dispatcher["extensions"] = self._noop

    @property
    def takes_input(self) -> bool:
        """Whether the user may trigger the action: as its menu button, if any, shows it.

        The entry and its button shown, the button enabled. A list opened earlier can still
        offer an entry hidden since, as its key can.
        """
        button = self.menu_button
        if button is None:
            return True
        return (
            self._view.is_visible
            and not button.is_disabled
            and all(node.display for node in button.ancestors_with_self)
        )

    def _refresh_label(
        self, name: str, view: ActionView, _rendered_object: ActionView, value: Any
    ) -> None:
        # called before the view stores `value`: the other fields come from the view
        state: dict[str, Any] = {
            "text": view.text,
            "is_checkable": view.is_checkable,
            "is_checked": view.is_checked,
            name: value,
        }
        if self.button is not None:
            button = self.button
            _call_on_app_thread(
                _app_of(button), functools.partial(_show_on_button, button, **state)
            )
        if self.app is None:
            return
        label = _action_label(**state)
        _call_on_app_thread(self.app, functools.partial(self.app.refresh_action, view, label))

    def _refresh_shortcut(
        self, view: ActionView, _rendered_object: ActionView, value: str | None
    ) -> None:
        if self.app is None:
            return  # not running yet: `_register_actions` binds the shortcut set by then
        app, previous = self.app, view.shortcut  # called before the view stores `value`
        _call_on_app_thread(app, functools.partial(app.rebind_action, view, previous, value))

    def _refresh_button_visible(
        self, _view: ActionView, _rendered_object: ActionView, value: bool
    ) -> None:
        if self.button is not None:
            button = self.button
            _call_on_app_thread(_app_of(button), lambda: setattr(button, "display", value))

    def _refresh_button_enabled(
        self, _view: ActionView, _rendered_object: ActionView, value: bool
    ) -> None:
        if self.button is not None:
            button = self.button
            _call_on_app_thread(_app_of(button), lambda: setattr(button, "disabled", not value))


def _show_on_button(
    button: ComposeToolbarButton, *, text: str, is_checkable: bool, is_checked: bool
) -> None:
    """Show an action on its toolbar button: its text, highlighted while checked."""
    button.label = Content(text)
    button.variant = "primary" if is_checkable and is_checked else "default"


def _action_label(*, text: str, is_checkable: bool, is_checked: bool) -> str:
    """Describe an action in the footer, with a check mark like the Qt and web menus."""
    return f"✓ {text}" if is_checkable and is_checked else text


class TextualSeparatorRenderer(_TextualNoopRenderer[SeparatorAction]):
    pass


class TextualMenuRenderer(_TextualNoopRenderer[Menu]):
    """No visual widget: a `Menu`'s children register themselves directly with the app."""

    def __init__(self, view: Menu) -> None:
        super().__init__(view)
        # nowhere to show it: its actions are key bindings
        self._refresh_dispatcher.update({"title": self._noop})


class TextualMenuButtonRenderer(TextualWidgetRenderer[MenuButtonView, ComposeButton]):
    """A button opening a popup list of its actions under it."""

    def __init__(self, view: MenuButtonView) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {"text": self._refresh_text, "variant": self._refresh_variant}
        )

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = button = ComposeButton()
            button.clicked.connect(self._open)
            for child_view in self._view.children_views:
                if isinstance(child_view.renderer, TextualActionRenderer):
                    child_view.renderer.menu_button = button

    def _open(self) -> None:
        """List the shown entries under the button, as they are now."""
        button = self._rendered_object
        assert button is not None
        shown = [
            child
            for child in self._view.children_views
            if isinstance(child, (ActionView, SeparatorAction)) and child.is_visible
        ]
        entries = [
            None
            if isinstance(child, SeparatorAction)
            else (
                _action_label(
                    text=child.text, is_checkable=child.is_checkable, is_checked=child.is_checked
                ),
                child.is_enabled,
            )
            for child in shown
        ]
        button.app.push_screen(
            ComposeMenuPopup(entries, button.region),
            functools.partial(self._pick, shown),
        )

    def _pick(self, shown: Sequence[View], index: int | None) -> None:
        if index is None:
            return
        action = shown[index]
        assert isinstance(action, ActionView)
        app = self._get_app()
        assert isinstance(app, _ComposeUIApp)
        app.trigger(action)

    @staticmethod
    def _refresh_text(_view: MenuButtonView, rendered_object: ComposeButton, value: str) -> None:
        # the triangle tells it from a plain button, as Qt's arrow and the web's chevron
        rendered_object.label = Content(f"{value} ▾")

    @staticmethod
    def _refresh_variant(
        _view: MenuButtonView, rendered_object: ComposeButton, value: ButtonVariant
    ) -> None:
        rendered_object.variant = _BUTTON_VARIANTS[value]


class TextualToolBarRenderer(TextualWidgetRenderer[ToolBar, ComposeToolbar]):
    """A row of buttons, one per action, docked at the top by the main renderer."""

    def __init__(self, view: ToolBar) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update({"title": self._noop})

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            widgets: list[Widget] = []
            for child_view in self._view.children_views:
                if isinstance(child_view, SeparatorAction):
                    widgets.append(ComposeToolbarSeparator())
                elif isinstance(child_view, ActionView) and isinstance(
                    child_view.renderer, TextualActionRenderer
                ):
                    button = ComposeToolbarButton()
                    button.triggered.connect(functools.partial(self._trigger, child_view))
                    child_view.renderer.button = button
                    widgets.append(button)
            self._rendered_object = ComposeToolbar(*widgets)

    def _trigger(self, action_view: ActionView) -> None:
        app = self._get_app()
        assert isinstance(app, _ComposeUIApp)
        app.trigger(action_view)

    @staticmethod
    def _noop(_view: ToolBar, _rendered_object: ComposeToolbar, _value: Any) -> None:
        pass  # a row of buttons has no title to show


def _to_textual_key(shortcut: str) -> str:
    """Convert a Qt-style shortcut (`"Ctrl+Shift+s"`) to Textual's key format (`"ctrl+shift+s"`)."""
    return "+".join(part.lower() for part in shortcut.split("+"))


# Actions that can show a blocking file-picker modal - see `_ComposeUIApp.action_trigger`.
_FILE_DIALOG_ACTIONS = (OpenFileAction, PickFileAction, SaveAction, SaveAsAction)


def _register_actions(app: _ComposeUIApp, root: View) -> None:
    """Turn every `ActionView` with a shortcut into a key binding, discoverable via `Footer`.

    Menus aren't rendered as widgets under Textual (see `TextualMenuRenderer`). Their
    actions are exposed as app-wide key bindings instead, mirroring the "Menu/Action
    style: key bindings + Footer" scope chosen for this backend.
    """
    views: deque[View] = deque([root])
    while views:
        current = views.popleft()
        if isinstance(current, ActionView):
            if current.shortcut is not None:
                app.bind_action(current, current.shortcut)
            # every action, a shortcut set later binding it then
            assert isinstance(current.renderer, TextualActionRenderer)
            current.renderer.app = app
        views.extend(current.children_views)


class _ComposeUIApp(App[None]):
    def __init__(self, view: MainView, root: Widget) -> None:
        self._view = view
        self._root = root
        self.registered_actions: dict[str, ActionView] = {}
        #: called once the app is mounted, e.g. to start a timer, which needs it running
        self.mounted_callbacks: list[Callable[[], None]] = []
        #: the file actions running on worker threads, which may be replacing the study
        self._file_workers = 0
        self._file_workers_lock = threading.Lock()
        super().__init__()

    def tick_autosave(self) -> None:
        """Tick the main view's autosave, unless a file action's worker runs.

        The worker may be replacing the study, e.g. Open loading one: the views would be read
        half replaced.
        """
        autosave = self._view._autosave  # noqa: SLF001 (the app's start took it)
        with self._file_workers_lock:
            runs_file_action = self._file_workers > 0
        if autosave is not None and not runs_file_action:
            autosave.tick()

    def _run_file_action(self, action_view: ActionView) -> None:
        try:
            action_view.triggered.emit()
        finally:
            with self._file_workers_lock:
                self._file_workers -= 1

    @override
    def compose(self) -> ComposeResult:
        yield self._root
        yield Footer()

    def on_mount(self) -> None:
        self.title = self._view.title
        _refresh_tree(self._view)
        _register_actions(self, self._view)
        autosave = self._view._autosave  # noqa: SLF001 (the app's start took it)
        if autosave is not None:
            self.set_interval(type(self._view).autosave_interval, self.tick_autosave)
            autosave.ask_restore()  # once mounted: its question is a screen
        for callback in self.mounted_callbacks:
            callback()

    @override
    async def action_quit(self) -> None:
        """Quit as the Exit action does, as Textual's Ctrl+Q has priority over its key."""
        if self._view.has_file_menu:
            self.trigger(self._view.file_menu.exit_app)  # what the app connected to it too
        else:
            self._view.close()  # its jobs canceled, as by Exit

    def action_trigger(self, action_id: str) -> None:
        self.trigger(self.registered_actions[action_id])

    def trigger(self, action_view: ActionView) -> None:
        """Trigger an action from its key binding or its toolbar button."""
        renderer = action_view.renderer
        # its key stays bound while its button is disabled or its page hidden
        if not action_view.is_enabled or (
            isinstance(renderer, TextualActionRenderer) and not renderer.takes_input
        ):
            return
        if isinstance(action_view, _FILE_DIALOG_ACTIONS):
            # `ask_open_filepath`/`ask_save_filepath` block waiting for a modal file
            # picker; blocking the app's own thread that way would freeze the very
            # loop that has to render and drive that modal, so this specific trigger
            # runs on a worker thread instead (`TextualMainRenderer.open_file`/
            # `save_file` bridge back via `call_from_thread`). Everything else
            # dispatches directly, matching Qt's immediate, synchronous `emit()`.
            with self._file_workers_lock:
                self._file_workers += 1
            self.run_worker(functools.partial(self._run_file_action, action_view), thread=True)
        else:
            action_view.triggered.emit()

    def bind_action(self, action_view: ActionView, shortcut: str) -> None:
        """Bind `shortcut` to an action, its text shown in the footer."""
        action_id = str(id(action_view))
        self.registered_actions[action_id] = action_view
        self.bind(
            _to_textual_key(shortcut),
            f"trigger({action_id!r})",
            description=_action_label(
                text=action_view.text,
                is_checkable=action_view.is_checkable,
                is_checked=action_view.is_checked,
            ),
        )

    def rebind_action(
        self, action_view: ActionView, previous: str | None, shortcut: str | None
    ) -> None:
        """Bind an action to `shortcut` instead of `previous`; `None` for no key."""
        if previous is not None:
            key = _to_textual_key(previous)
            action = f"trigger({str(id(action_view))!r})"
            bindings = self._bindings.key_to_bindings.get(key, [])
            bindings[:] = [binding for binding in bindings if binding.action != action]
            if not bindings:
                self._bindings.key_to_bindings.pop(key, None)
        if shortcut is not None:
            self.bind_action(action_view, shortcut)
        self.refresh_bindings()

    def refresh_action(self, action_view: ActionView, label: str) -> None:
        """Show `label` as an action's description in the footer."""
        if action_view.shortcut is None:
            return
        action = f"trigger({str(id(action_view))!r})"
        # `bind` would add a second binding: replace the existing one in place instead
        bindings = self._bindings.get_bindings_for_key(_to_textual_key(action_view.shortcut))
        for index, binding in enumerate(bindings):
            if binding.action == action:
                bindings[index] = dataclasses.replace(binding, description=label)
        self.refresh_bindings()

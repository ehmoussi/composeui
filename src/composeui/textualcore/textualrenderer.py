from __future__ import annotations

import contextlib
import dataclasses
import functools
from collections import deque
from typing import TYPE_CHECKING, Any, ClassVar, Generic, TypeVar, cast

from textual.app import App, ComposeResult
from textual.containers import Container, Grid, Horizontal, Vertical, VerticalScroll
from textual.content import Content
from textual.types import NoActiveAppError
from textual.validation import Integer, Number
from textual.widgets import ContentSwitcher, Footer, Label, ProgressBar, Static, TabPane
from textual_fspicker import FileOpen, FileSave
from textual_fspicker.path_filters import Filter, Filters
from typing_extensions import Protocol

from composeui.core import chartimage
from composeui.core.registry import RendererType
from composeui.core.renderer import (
    MainRenderer,
    NoRenderedObjectError,
    Renderer,
    RendererContainer,
    ViewLike,
)
from composeui.core.view import (
    ActionView,
    Align,
    ButtonVariant,
    CellKind,
    ChartKind,
    ChartView,
    DataTableByPosition,
    DialogKind,
    DialogView,
    ExpanderView,
    FormDialogView,
    FormLabelRowView,
    FormRowView,
    FormView,
    GridPosition,
    GridView,
    GroupFormView,
    HorizontalView,
    ListView,
    LogType,
    MainView,
    Menu,
    MetricView,
    OpenFileAction,
    Orientation,
    PageView,
    PickFileAction,
    ProgressBarView,
    Router,
    SaveAction,
    SaveAsAction,
    SelectionMode,
    SeparatorAction,
    SidebarView,
    SliderMixin,
    SplitterView,
    StatusBar,
    TabPage,
    TabView,
    ToolBar,
    TreeView,
    VerticalView,
    View,
    date_hint,
    replace_cell,
)
from composeui.textualcore.widgets.composebutton import ComposeButton
from composeui.textualcore.widgets.composechart import ComposeChart
from composeui.textualcore.widgets.composecheckbox import ComposeCheckbox
from composeui.textualcore.widgets.composecollapsible import ComposeCollapsible
from composeui.textualcore.widgets.composecombobox import ComposeCombobox
from composeui.textualcore.widgets.composedatatable import ComposeDataFilterTable
from composeui.textualcore.widgets.composedateinput import ComposeDateInput
from composeui.textualcore.widgets.composedialog import ComposeDialog
from composeui.textualcore.widgets.composefilepathinput import ComposeFilePathInput
from composeui.textualcore.widgets.composefiltertable import ComposeFilterTable
from composeui.textualcore.widgets.composeformdialog import ComposeFormDialog
from composeui.textualcore.widgets.composeinput import ComposeInput
from composeui.textualcore.widgets.composelist import ComposeList
from composeui.textualcore.widgets.composemarkdown import ComposeMarkdown
from composeui.textualcore.widgets.composemetric import ComposeMetric
from composeui.textualcore.widgets.composeradioset import ComposeRadioSet
from composeui.textualcore.widgets.composesidebar import ComposeSidebar
from composeui.textualcore.widgets.composeslider import ComposeSlider
from composeui.textualcore.widgets.composesplitter import ComposeSplitter
from composeui.textualcore.widgets.composetabbedcontent import ComposeTabbedContent
from composeui.textualcore.widgets.composetoolbar import (
    ComposeToolbar,
    ComposeToolbarButton,
    ComposeToolbars,
    ComposeToolbarSeparator,
)
from composeui.textualcore.widgets.composetree import ComposeTree

if TYPE_CHECKING:
    import datetime
    from collections.abc import Callable
    from pathlib import Path

    from textual.widget import AwaitMount, Widget
    from textual.widgets.button import ButtonVariant as ButtonVariantName

    from composeui.core.signal import Signal, SignalNoArgs
    from composeui.core.view import (
        CellStyle,
        CellWidget,
        HeaderGroup,
        NodeMark,
        ReferenceLine,
        Series,
        TreeNode,
        TreePath,
    )

TView = TypeVar("TView", bound=ViewLike)
TWidget = TypeVar("TWidget", bound="Widget")
TValue = TypeVar("TValue")


class NoTextualRendererObjectError(Exception):
    def __init__(self) -> None:
        super().__init__("Renderer should be inherited by TextualRenderer")


def _has_any_extension(filepath: Path, extensions: tuple[str, ...]) -> bool:
    return any(filepath.name.endswith(extension) for extension in extensions)


def _app_of(widget: Widget) -> App[Any] | None:
    """Get the app running `widget`, or None before it is mounted."""
    try:
        return widget.app
    except NoActiveAppError:
        return None


def _call_on_app_thread(app: App[Any] | None, callback: Callable[[], None]) -> None:
    """Marshal `callback` onto the thread running `app`'s event loop.

    `App.call_from_thread` raises `RuntimeError` both when the app isn't running yet
    and when it's called from the app's own thread (nothing to marshal in either
    case) - both fall back to calling directly, matching `Renderer`'s default.
    """
    if app is None:
        callback()
        return
    try:
        app.call_from_thread(callback)
    except RuntimeError:
        callback()


#: the class a row's field widget has while the row is invalid (`FormRowView.is_invalid`),
#: styled by the composeui widgets. Not Textual's own `-invalid`: `Input` resets that one
#: from its validators on every keystroke
ROW_INVALID_CLASS = "-row-invalid"


class TextualWidgetRenderer(Renderer[TView, TWidget]):
    #: whether the widget is a form row's field, showing the row as invalid
    _marks_invalid: ClassVar[bool] = False

    def __init__(self, view: TView) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "is_visible": self._refresh_visible,
                "is_enabled": self._refresh_enabled,
            }
        )
        if self._marks_invalid and isinstance(view, FormRowView):
            # only a row has these: the same renderer also draws a standalone field
            self._refresh_dispatcher.update(
                {
                    name: self._invalid_refresher(name)
                    for name in ("log_message", "log_type", "has_form_error")
                }
            )

    @property
    def widget(self) -> TWidget | None:
        return self._rendered_object

    def call_on_main_thread(self, callback: Callable[[], None]) -> None:
        _call_on_app_thread(self._get_app(), callback)

    def _get_app(self) -> App[Any] | None:
        if self._rendered_object is None:
            return None
        return _app_of(self._rendered_object)

    def refresh(self) -> None:
        # Textual widgets aren't thread-safe (see `App.call_from_thread`'s own
        # docstring) - state can legitimately change from a non-main thread (e.g.
        # `MainView.load_state` running as part of a worker-dispatched file-open
        # action, see `_ComposeUIApp.action_trigger`). `call_on_main_thread` already
        # falls back to a direct call when we're already on the right thread, so this
        # is a no-op in the common case.
        self.call_on_main_thread(self._refresh_if_mounted)

    def refresh_attribute(self, attr_name: str, value: Any) -> None:
        self.call_on_main_thread(
            functools.partial(self._refresh_attribute_if_mounted, attr_name, value)
        )

    def _is_waiting_to_mount(self) -> bool:
        """Tell whether the app runs but hasn't mounted the widget yet, e.g. on a screen not shown.

        Some widgets refuse their state until mounted (a `Select` its options); whatever
        mounts them later gives them their state then: the app's own mount, a list's new
        item, a form dialog's screen.
        """
        widget = self._rendered_object
        if widget is None or widget.is_attached:
            return False
        app = _app_of(widget)
        return app is not None and app.is_running

    def _refresh_if_mounted(self) -> None:
        if not self._is_waiting_to_mount():
            super().refresh()

    def _refresh_attribute_if_mounted(self, attr_name: str, value: Any) -> None:
        if not self._is_waiting_to_mount():
            super().refresh_attribute(attr_name, value)

    @staticmethod
    def _refresh_visible(_view: TView, rendered_object: TWidget, value: bool) -> None:
        rendered_object.display = value

    @staticmethod
    def _refresh_enabled(_view: TView, rendered_object: TWidget, value: bool) -> None:
        rendered_object.disabled = not value

    @staticmethod
    def _invalid_refresher(name: str) -> Callable[[TView, TWidget, Any], None]:
        """Mark the field once the row's attribute `name` changes to the given value."""

        def refresh(view: TView, rendered_object: TWidget, value: Any) -> None:
            is_invalid = isinstance(view, FormRowView) and view.is_invalid_once(name, value)
            rendered_object.set_class(is_invalid, ROW_INVALID_CLASS)

        return refresh


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
            if screen.is_current:
                screen.dismiss()  # no longer `self.screen`: `_answer` ignores it

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
        self, _view: DialogView, _rendered_object: DialogView, value: DialogKind
    ) -> None:
        if self.screen is not None:
            self.screen.reject_button.display = value is DialogKind.CONFIRM

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
    """A modal screen holding the form, installed once: pushed open, popped closed.

    The form's widgets are built once, so its screen is too, unlike a message's. OK is
    disabled while a check of the form fails; the view closes the dialog once it accepts
    the answer, so OK on a form refusing it leaves the screen up.
    """

    def __init__(self, view: FormDialogView) -> None:
        super().__init__(view)
        self._form_view = view
        self.form_screen: ComposeFormDialog | None = None
        self._refresh_dispatcher["is_accept_enabled"] = self._refresh_is_accept_enabled

    def render(self) -> None:
        if self._rendered_object is None:
            super().render()
            form = self._form_view.form.renderer
            if isinstance(form, TextualWidgetRenderer) and form.widget is not None:
                self.form_screen = ComposeFormDialog(form.widget)
                self.form_screen.answered.connect(self._answer_form)
                # its form's widgets mount with it, first pushed: their state only then
                self.form_screen.mounted.connect(self._refresh_screen)

    def _refresh_screen(self) -> None:
        _refresh_tree(self._form_view.form)
        self.refresh()  # the screen's title, text and buttons

    def _answer_form(self, answer: str) -> None:
        {"accept": self._view.accept, "reject": self._view.reject}.get(answer, self._view.dismiss)()

    def _refresh_visible(self, view: DialogView, _rendered_object: DialogView, value: bool) -> None:
        app, screen = self.app, self.form_screen
        # opened before the app runs: its mount refreshes the tree again
        if app is None or not app.is_running or screen is None:
            return
        if value and not screen.is_current:
            name = f"cui-{id(view)}-dialog"
            if not app.is_screen_installed(screen):
                app.install_screen(screen, name)
            app.push_screen(name)
        elif not value and screen.is_current:
            app.pop_screen()

    def _refresh_enabled(
        self, _view: DialogView, _rendered_object: DialogView, value: bool
    ) -> None:
        if self.form_screen is not None:
            self.form_screen.reject_button.disabled = not value
            self.form_screen.accept_button.disabled = not (
                value and self._form_view.is_accept_enabled
            )

    def _refresh_title(self, _view: DialogView, _rendered_object: DialogView, value: str) -> None:
        if self.form_screen is not None:
            self.form_screen.title_label.update(value)
            self.form_screen.title_label.display = value != ""

    def _refresh_text(self, _view: DialogView, _rendered_object: DialogView, value: str) -> None:
        if self.form_screen is not None:
            self.form_screen.text_label.update(value)
            self.form_screen.text_label.display = value != ""

    def _refresh_kind(self, _view: DialogView, _rendered_object: DialogView, _value: Any) -> None:
        pass  # always OK and Cancel: a form is confirmed or not

    def _refresh_accept_text(
        self, _view: DialogView, _rendered_object: DialogView, value: str
    ) -> None:
        if self.form_screen is not None:
            self.form_screen.accept_button.label = Content(value)

    def _refresh_reject_text(
        self, _view: DialogView, _rendered_object: DialogView, value: str
    ) -> None:
        if self.form_screen is not None:
            self.form_screen.reject_button.label = Content(value)

    def _refresh_is_accept_enabled(
        self, _view: DialogView, _rendered_object: DialogView, value: bool
    ) -> None:
        if self.form_screen is not None:
            self.form_screen.accept_button.disabled = not (value and self._view.is_enabled)


class InputViewLike(ViewLike, Protocol):
    placeholder: str
    text: str
    text_changed: Signal[str]
    text_edited: Signal[str]
    editing_finished: SignalNoArgs


class TextualInputRenderer(TextualWidgetRenderer[InputViewLike, ComposeInput]):
    _marks_invalid = True

    def __init__(self, view: InputViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "text": self._refresh_text,
                "placeholder": self._refresh_placeholder,
            }
        )

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = ComposeInput()
            self._rendered_object.value_changed.connect(self._update_text)
            self._rendered_object.value_submitted.connect(self._editing_finished)

    @staticmethod
    def _refresh_text(_view: InputViewLike, rendered_object: ComposeInput, value: str) -> None:
        rendered_object.value = value

    @staticmethod
    def _refresh_placeholder(
        _view: InputViewLike, rendered_object: ComposeInput, value: str
    ) -> None:
        rendered_object.placeholder = value

    def _update_text(self, text: str) -> None:
        with self.stop_refresh():
            self._view.text = text
        self._view.text_changed.emit(text)
        self._view.text_edited.emit(text)

    def _editing_finished(self) -> None:
        self._view.editing_finished.emit()


class FloatInputViewLike(ViewLike, Protocol):
    placeholder: str
    value: float | None
    minimum: float | None
    maximum: float | None
    decimals: int | None
    text_changed: Signal[str]
    text_edited: Signal[str]
    editing_finished: SignalNoArgs

    def shown_text(self, value: float | None, decimals: int | None) -> str: ...


class TextualFloatInputRenderer(TextualWidgetRenderer[FloatInputViewLike, ComposeInput]):
    _marks_invalid = True

    def __init__(self, view: FloatInputViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "value": self._refresh_value,
                "placeholder": self._refresh_placeholder,
                "minimum": self._refresh_minimum,
                "maximum": self._refresh_maximum,
                # shown, not enforced: Textual's `Number` validator only bounds min/max,
                # with no equivalent of Qt's `QDoubleValidator.setDecimals`
                "decimals": self._refresh_decimals,
            }
        )

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = ComposeInput()
            self._rendered_object.value_changed.connect(self._update_text)
            self._rendered_object.value_submitted.connect(self._editing_finished)

    @staticmethod
    def _refresh_value(
        view: FloatInputViewLike, rendered_object: ComposeInput, value: float | None
    ) -> None:
        rendered_object.value = view.shown_text(value, view.decimals)

    @staticmethod
    def _refresh_decimals(
        view: FloatInputViewLike, rendered_object: ComposeInput, value: int | None
    ) -> None:
        rendered_object.value = view.shown_text(view.value, value)

    @staticmethod
    def _refresh_placeholder(
        _view: FloatInputViewLike, rendered_object: ComposeInput, value: str
    ) -> None:
        rendered_object.placeholder = value

    @staticmethod
    def _refresh_minimum(
        _view: FloatInputViewLike, rendered_object: ComposeInput, value: float | None
    ) -> None:
        rendered_object.validators = [
            v for v in rendered_object.validators if not isinstance(v, Number)
        ]
        rendered_object.validators.append(Number(minimum=value, maximum=_view.maximum))

    @staticmethod
    def _refresh_maximum(
        _view: FloatInputViewLike, rendered_object: ComposeInput, value: float | None
    ) -> None:
        rendered_object.validators = [
            v for v in rendered_object.validators if not isinstance(v, Number)
        ]
        rendered_object.validators.append(Number(minimum=_view.minimum, maximum=value))

    def _update_text(self, text: str) -> None:
        # Textual reports the text the renderer set too: as shown for the view's value,
        # maybe rounded, it isn't the user's and leaves the value as it is.
        # Transient invalid text while typing (e.g. "-", "1.") is ignored.
        if text != self._view.shown_text(self._view.value, self._view.decimals):
            with self.stop_refresh(), contextlib.suppress(ValueError):
                self._view.value = float(text) if text != "" else None
        self._view.text_changed.emit(text)
        self._view.text_edited.emit(text)

    def _editing_finished(self) -> None:
        self._view.editing_finished.emit()


class IntInputViewLike(ViewLike, Protocol):
    placeholder: str
    value: int | None
    minimum: int | None
    maximum: int | None
    text_changed: Signal[str]
    text_edited: Signal[str]
    editing_finished: SignalNoArgs


class TextualIntInputRenderer(TextualWidgetRenderer[IntInputViewLike, ComposeInput]):
    """An input taking only a whole number; Textual has no spin box.

    As on the float input, a value out of `minimum`/`maximum` is marked invalid, not refused.
    """

    _marks_invalid = True

    def __init__(self, view: IntInputViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "value": self._refresh_value,
                "placeholder": self._refresh_placeholder,
                "minimum": self._refresh_range,
                "maximum": self._refresh_range,
            }
        )

    def render(self) -> None:
        if self._rendered_object is None:
            # `type="integer"` lets in only what can start an int: digits and a sign
            self._rendered_object = ComposeInput(type="integer")
            self._rendered_object.value_changed.connect(self._update_text)
            self._rendered_object.value_submitted.connect(self._editing_finished)

    @staticmethod
    def _refresh_value(
        _view: IntInputViewLike, rendered_object: ComposeInput, value: int | None
    ) -> None:
        rendered_object.value = str(value) if value is not None else ""

    @staticmethod
    def _refresh_placeholder(
        _view: IntInputViewLike, rendered_object: ComposeInput, value: str
    ) -> None:
        rendered_object.placeholder = value

    @staticmethod
    def _refresh_range(view: IntInputViewLike, rendered_object: ComposeInput, _value: Any) -> None:
        # `type="integer"` adds an `Integer` validator of its own, without a range
        rendered_object.validators = [
            v for v in rendered_object.validators if not isinstance(v, Number)
        ]
        rendered_object.validators.append(Integer(minimum=view.minimum, maximum=view.maximum))

    def _update_text(self, text: str) -> None:
        # transient invalid text while typing (e.g. "-"); ignore it
        with self.stop_refresh(), contextlib.suppress(ValueError):
            self._view.value = int(text) if text != "" else None
        self._view.text_changed.emit(text)
        self._view.text_edited.emit(text)

    def _editing_finished(self) -> None:
        self._view.editing_finished.emit()


class DateInputViewLike(ViewLike, Protocol):
    placeholder: str
    value: datetime.date | None
    minimum: datetime.date | None
    maximum: datetime.date | None
    date_format: str
    month_names: list[str]
    day_names: list[str]
    pick_text: str
    text_changed: Signal[str]
    text_edited: Signal[str]
    editing_finished: SignalNoArgs
    value_changed: Signal[datetime.date | None]


class TextualDateInputRenderer(TextualWidgetRenderer[DateInputViewLike, ComposeDateInput]):
    """A field typing the date as the view's `date_format` says, beside a calendar button.

    Textual has no date picker: the calendar is a screen of its own, its months and days
    named as the view's `month_names` and `day_names`, so in the main view's language.
    """

    _marks_invalid = True

    def __init__(self, view: DateInputViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "value": self._refresh_value,
                "placeholder": self._refresh_placeholder,
                "minimum": self._refresh_minimum,
                "maximum": self._refresh_maximum,
                "date_format": self._refresh_date_format,
                "month_names": self._refresh_month_names,
                "day_names": self._refresh_day_names,
                "pick_text": self._refresh_pick_text,
                # its calendar's keys move by month, its title naming the month shown
                "previous_month_text": lambda _view, _rendered_object, _value: None,
                "next_month_text": lambda _view, _rendered_object, _value: None,
            }
        )

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = ComposeDateInput()
            self._rendered_object.date_edited.connect(self._update_value)
            self._rendered_object.input.value_changed.connect(self._update_text)
            self._rendered_object.input.value_submitted.connect(self._view.editing_finished.emit)

    @staticmethod
    def _refresh_value(
        _view: DateInputViewLike, rendered_object: ComposeDateInput, value: datetime.date | None
    ) -> None:
        rendered_object.set_date(value)

    @staticmethod
    def _refresh_placeholder(
        view: DateInputViewLike, rendered_object: ComposeDateInput, value: str
    ) -> None:
        rendered_object.input.placeholder = date_hint(value, view.date_format)

    @staticmethod
    def _refresh_minimum(
        _view: DateInputViewLike, rendered_object: ComposeDateInput, value: datetime.date | None
    ) -> None:
        rendered_object.minimum = value
        rendered_object.input.validate(rendered_object.input.value)

    @staticmethod
    def _refresh_maximum(
        _view: DateInputViewLike, rendered_object: ComposeDateInput, value: datetime.date | None
    ) -> None:
        rendered_object.maximum = value
        rendered_object.input.validate(rendered_object.input.value)

    @staticmethod
    def _refresh_date_format(
        view: DateInputViewLike, rendered_object: ComposeDateInput, value: str
    ) -> None:
        rendered_object.set_date_format(value)
        rendered_object.input.placeholder = date_hint(view.placeholder, value)

    @staticmethod
    def _refresh_month_names(
        _view: DateInputViewLike, rendered_object: ComposeDateInput, value: list[str]
    ) -> None:
        rendered_object.month_names = list(value)

    @staticmethod
    def _refresh_day_names(
        _view: DateInputViewLike, rendered_object: ComposeDateInput, value: list[str]
    ) -> None:
        rendered_object.day_names = list(value)

    @staticmethod
    def _refresh_pick_text(
        _view: DateInputViewLike, rendered_object: ComposeDateInput, value: str
    ) -> None:
        rendered_object.button.tooltip = Content(value)

    def _update_value(self, value: datetime.date | None) -> None:
        with self.stop_refresh():
            self._view.value = value
        self._view.value_changed.emit(value)

    def _update_text(self, text: str) -> None:
        self._view.text_changed.emit(text)
        self._view.text_edited.emit(text)


class FilePathInputViewLike(InputViewLike, Protocol):
    extensions: dict[str, tuple[str, ...]]
    has_reload: bool
    browse_text: str
    reload_text: str
    path_picked: Signal[Path]
    reload_clicked: SignalNoArgs


class TextualFilePathInputRenderer(
    TextualWidgetRenderer[FilePathInputViewLike, ComposeFilePathInput]
):
    """A field typing a file's path, then a "…" button opening textual-fspicker's picker."""

    _marks_invalid = True

    def __init__(self, view: FilePathInputViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "text": self._refresh_text,
                "placeholder": self._refresh_placeholder,
                "extensions": self._refresh_extensions,
                "has_reload": self._refresh_has_reload,
                "browse_text": self._refresh_browse_text,
                "reload_text": self._refresh_reload_text,
            }
        )

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = ComposeFilePathInput()
            self._rendered_object.input.value_changed.connect(self._update_text)
            self._rendered_object.input.value_submitted.connect(self._view.editing_finished.emit)
            self._rendered_object.path_picked.connect(self._pick)
            self._rendered_object.reload_pressed.connect(self._view.reload_clicked.emit)

    @staticmethod
    def _refresh_text(
        _view: FilePathInputViewLike, rendered_object: ComposeFilePathInput, value: str
    ) -> None:
        rendered_object.input.value = value

    @staticmethod
    def _refresh_placeholder(
        _view: FilePathInputViewLike, rendered_object: ComposeFilePathInput, value: str
    ) -> None:
        rendered_object.input.placeholder = value

    @staticmethod
    def _refresh_extensions(
        _view: FilePathInputViewLike,
        rendered_object: ComposeFilePathInput,
        value: dict[str, tuple[str, ...]],
    ) -> None:
        rendered_object.extensions = dict(value)

    @staticmethod
    def _refresh_has_reload(
        _view: FilePathInputViewLike, rendered_object: ComposeFilePathInput, value: bool
    ) -> None:
        rendered_object.reload_button.display = value

    @staticmethod
    def _refresh_browse_text(
        _view: FilePathInputViewLike, rendered_object: ComposeFilePathInput, value: str
    ) -> None:
        rendered_object.browse_button.tooltip = Content(value)
        rendered_object.picker_title = value

    @staticmethod
    def _refresh_reload_text(
        _view: FilePathInputViewLike, rendered_object: ComposeFilePathInput, value: str
    ) -> None:
        rendered_object.reload_button.tooltip = Content(value)

    def _update_text(self, text: str) -> None:
        with self.stop_refresh():
            self._view.text = text
        self._view.text_changed.emit(text)
        self._view.text_edited.emit(text)

    def _pick(self, path: Path) -> None:
        # the field's change arrives later, as a message: the view has the path first
        with self.stop_refresh():
            self._view.text = str(path)
        self._view.path_picked.emit(path)


class SliderViewLike(ViewLike, Protocol):
    value: int
    minimum: int
    maximum: int
    step: int
    value_changed: Signal[int]


class TextualSliderRenderer(TextualWidgetRenderer[SliderViewLike, ComposeSlider]):
    _marks_invalid = True

    def __init__(self, view: SliderViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "value": self._refresh_value,
                "minimum": self._refresh_minimum,
                "maximum": self._refresh_maximum,
                "step": self._refresh_step,
            }
        )

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = ComposeSlider()
            self._rendered_object.moved.connect(self._update_value)

    @staticmethod
    def _refresh_value(view: SliderViewLike, rendered_object: ComposeSlider, value: int) -> None:
        TextualSliderRenderer._show(rendered_object, value, view.minimum, view.maximum, view.step)

    @staticmethod
    def _refresh_minimum(view: SliderViewLike, rendered_object: ComposeSlider, value: int) -> None:
        TextualSliderRenderer._show(rendered_object, view.value, value, view.maximum, view.step)

    @staticmethod
    def _refresh_maximum(view: SliderViewLike, rendered_object: ComposeSlider, value: int) -> None:
        TextualSliderRenderer._show(rendered_object, view.value, view.minimum, value, view.step)

    @staticmethod
    def _refresh_step(view: SliderViewLike, rendered_object: ComposeSlider, value: int) -> None:
        TextualSliderRenderer._show(rendered_object, view.value, view.minimum, view.maximum, value)

    @staticmethod
    def _show(
        rendered_object: ComposeSlider, value: int, minimum: int, maximum: int, step: int
    ) -> None:
        rendered_object.set_steps(
            minimum,
            step,
            SliderMixin.last_position(minimum, maximum, step),
            SliderMixin.position(value, minimum, maximum, step),
        )

    def _update_value(self, value: int) -> None:
        with self.stop_refresh():
            self._view.value = value
        self._view.value_changed.emit(value)


class LabelViewLike(ViewLike, Protocol):
    text: str


class TextualLabelRenderer(TextualWidgetRenderer[LabelViewLike, Label]):
    def __init__(self, view: LabelViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "text": self._refresh_text,
            }
        )

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = Label(markup=False)

    @staticmethod
    def _refresh_text(_view: LabelViewLike, rendered_object: Label, value: str) -> None:
        rendered_object.update(value)


class MarkdownViewLike(ViewLike, Protocol):
    text: str


class TextualMarkdownRenderer(TextualWidgetRenderer[MarkdownViewLike, ComposeMarkdown]):
    def __init__(self, view: MarkdownViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update({"text": self._refresh_text})

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = ComposeMarkdown()

    @staticmethod
    def _refresh_text(
        _view: MarkdownViewLike, rendered_object: ComposeMarkdown, value: str
    ) -> None:
        rendered_object.set_text(value)


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


class CheckBoxViewLike(ViewLike, Protocol):
    text: str
    is_checked: bool
    toggled: Signal[bool]


class TextualCheckBoxRenderer(TextualWidgetRenderer[CheckBoxViewLike, ComposeCheckbox]):
    _marks_invalid = True

    def __init__(self, view: CheckBoxViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "text": self._refresh_text,
                "is_checked": self._refresh_is_checked,
            }
        )

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = ComposeCheckbox()
            self._rendered_object.toggled.connect(self._update_checked)

    @staticmethod
    def _refresh_text(
        _view: CheckBoxViewLike, rendered_object: ComposeCheckbox, value: str
    ) -> None:
        rendered_object.label = Content(value)

    @staticmethod
    def _refresh_is_checked(
        _view: CheckBoxViewLike, rendered_object: ComposeCheckbox, value: bool
    ) -> None:
        rendered_object.set_checked(value)

    def _update_checked(self, is_checked: bool) -> None:
        with self.stop_refresh():
            self._view.is_checked = is_checked
        self._view.toggled.emit(is_checked)


class ButtonViewLike(ViewLike, Protocol):
    text: str
    variant: ButtonVariant
    clicked: SignalNoArgs


#: each button variant as Textual's
_BUTTON_VARIANTS: dict[ButtonVariant, ButtonVariantName] = {
    ButtonVariant.PRIMARY: "primary",
    ButtonVariant.SECONDARY: "default",
    ButtonVariant.DANGER: "error",
}


class TextualButtonRenderer(TextualWidgetRenderer[ButtonViewLike, ComposeButton]):
    def __init__(self, view: ButtonViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {"text": self._refresh_text, "variant": self._refresh_variant}
        )

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = ComposeButton()
            self._rendered_object.clicked.connect(self._view.clicked.emit)

    @staticmethod
    def _refresh_text(_view: ButtonViewLike, rendered_object: ComposeButton, value: str) -> None:
        rendered_object.label = Content(value)

    @staticmethod
    def _refresh_variant(
        _view: ButtonViewLike, rendered_object: ComposeButton, value: ButtonVariant
    ) -> None:
        rendered_object.variant = _BUTTON_VARIANTS[value]


class ProgressBarViewLike(ViewLike, Protocol):
    value: int
    maximum: int | None


class TextualProgressBarRenderer(TextualWidgetRenderer[ProgressBarViewLike, ProgressBar]):
    def __init__(self, view: ProgressBarViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {"value": self._refresh_value, "maximum": self._refresh_maximum}
        )

    def render(self) -> None:
        if self._rendered_object is None:
            # no time left: neither Qt nor the web estimates one
            self._rendered_object = ProgressBar(show_eta=False)

    @staticmethod
    def _refresh_value(view: ProgressBarViewLike, rendered_object: ProgressBar, value: int) -> None:
        rendered_object.update(progress=ProgressBarView.clamp(value, view.maximum))

    @staticmethod
    def _refresh_maximum(
        view: ProgressBarViewLike, rendered_object: ProgressBar, value: int | None
    ) -> None:
        # no total is Textual's own bar for a task of unknown length
        rendered_object.update(total=value, progress=ProgressBarView.clamp(view.value, value))


class ChartViewLike(ViewLike, Protocol):
    kind: ChartKind
    title: str
    x_title: str
    y_title: str
    x_unit: str
    y_unit: str
    series: list[Series]
    reference_lines: list[ReferenceLine]
    categories: list[str]
    x_log: bool
    y_log: bool
    save_image_text: str
    height: int | None


#: the pixels of a terminal's row, about: a chart's height is in pixels
PIXELS_PER_ROW = 16
#: the rows a chart takes at least, to show its axes and a curve between them
MIN_CHART_ROWS = 5


class TextualChartRenderer(TextualWidgetRenderer[ChartViewLike, ComposeChart]):
    def __init__(self, view: ChartViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "kind": self._refresh_kind,
                "title": self._refresh_title,
                "x_title": self._refresh_x_title,
                "x_unit": self._refresh_x_unit,
                "y_title": self._refresh_y_title,
                "y_unit": self._refresh_y_unit,
                "series": self._refresh_series,
                "reference_lines": self._refresh_reference_lines,
                "categories": self._refresh_categories,
                "x_log": self._refresh_x_log,
                "y_log": self._refresh_y_log,
                "save_image_text": self._refresh_save_image_text,
                "height": self._refresh_height,
            }
        )

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = ComposeChart()
            self._rendered_object.image_path_chosen.connect(self._save_image)

    @staticmethod
    def _refresh_kind(
        _view: ChartViewLike, rendered_object: ComposeChart, value: ChartKind
    ) -> None:
        rendered_object.kind = value
        rendered_object.refresh()

    # each refreshed with its new value, the view still holding the old one
    @staticmethod
    def _refresh_title(_view: ChartViewLike, rendered_object: ComposeChart, value: str) -> None:
        rendered_object.chart_title = value
        rendered_object.image_name = chartimage.image_name(value, "pdf")
        rendered_object.refresh()

    @staticmethod
    def _refresh_x_title(view: ChartViewLike, rendered_object: ComposeChart, value: str) -> None:
        rendered_object.x_label = ChartView.axis_label(value, view.x_unit)
        rendered_object.refresh()

    @staticmethod
    def _refresh_x_unit(view: ChartViewLike, rendered_object: ComposeChart, value: str) -> None:
        rendered_object.x_label = ChartView.axis_label(view.x_title, value)
        rendered_object.refresh()

    @staticmethod
    def _refresh_y_title(view: ChartViewLike, rendered_object: ComposeChart, value: str) -> None:
        rendered_object.y_label = ChartView.axis_label(value, view.y_unit)
        rendered_object.refresh()

    @staticmethod
    def _refresh_y_unit(view: ChartViewLike, rendered_object: ComposeChart, value: str) -> None:
        rendered_object.y_label = ChartView.axis_label(view.y_title, value)
        rendered_object.refresh()

    @staticmethod
    def _refresh_series(
        _view: ChartViewLike, rendered_object: ComposeChart, value: list[Series]
    ) -> None:
        rendered_object.series = value
        rendered_object.refresh()

    @staticmethod
    def _refresh_reference_lines(
        _view: ChartViewLike, rendered_object: ComposeChart, value: list[ReferenceLine]
    ) -> None:
        rendered_object.reference_lines = value
        rendered_object.refresh()

    @staticmethod
    def _refresh_categories(
        _view: ChartViewLike, rendered_object: ComposeChart, value: list[str]
    ) -> None:
        rendered_object.categories = value
        rendered_object.refresh()

    @staticmethod
    def _refresh_x_log(_view: ChartViewLike, rendered_object: ComposeChart, value: bool) -> None:
        rendered_object.x_log = value
        rendered_object.refresh()

    @staticmethod
    def _refresh_y_log(_view: ChartViewLike, rendered_object: ComposeChart, value: bool) -> None:
        rendered_object.y_log = value
        rendered_object.refresh()

    @staticmethod
    def _refresh_save_image_text(
        _view: ChartViewLike, rendered_object: ComposeChart, value: str
    ) -> None:
        rendered_object.set_save_image_text(value)

    @staticmethod
    def _refresh_height(
        _view: ChartViewLike, rendered_object: ComposeChart, value: int | None
    ) -> None:
        # None: the widget's own CSS height; its minimum too, under a smaller height
        rows = None if value is None else max(MIN_CHART_ROWS, round(value / PIXELS_PER_ROW))
        rendered_object.styles.height = rows
        rendered_object.styles.min_height = rows

    def _save_image(self, path: Path) -> None:
        """Save the whole chart's image: a terminal has no zoom."""
        if isinstance(self._view, ChartView):
            chartimage.save_chart_image(self._view, path)


class MetricViewLike(ViewLike, Protocol):
    label: str
    value: str
    delta: float | None
    delta_text: str


class TextualMetricRenderer(TextualWidgetRenderer[MetricViewLike, ComposeMetric]):
    def __init__(self, view: MetricViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "label": self._refresh_label,
                "value": self._refresh_value,
                "delta": self._refresh_delta,
                "delta_text": self._refresh_delta_text,
            }
        )

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = ComposeMetric()

    @staticmethod
    def _refresh_label(_view: MetricViewLike, rendered_object: ComposeMetric, value: str) -> None:
        rendered_object.label.update(value)

    @staticmethod
    def _refresh_value(_view: MetricViewLike, rendered_object: ComposeMetric, value: str) -> None:
        rendered_object.value.update(value)

    @staticmethod
    def _refresh_delta(
        view: MetricViewLike, rendered_object: ComposeMetric, value: float | None
    ) -> None:
        TextualMetricRenderer._show_badge(rendered_object, value, view.delta_text)

    @staticmethod
    def _refresh_delta_text(
        view: MetricViewLike, rendered_object: ComposeMetric, value: str
    ) -> None:
        TextualMetricRenderer._show_badge(rendered_object, view.delta, value)

    @staticmethod
    def _show_badge(rendered_object: ComposeMetric, delta: float | None, delta_text: str) -> None:
        if delta is None:
            rendered_object.set_delta("", 0)
        else:
            sign = (delta > 0) - (delta < 0)
            rendered_object.set_delta(MetricView.badge(delta, delta_text), sign)


class DataTableViewLike(ViewLike, Protocol):
    texts: dict[str, str]
    export_filename: str
    sort_column: str | None
    sort_descending: bool
    search: str
    filters: dict[str, str]
    filterable_columns: list[str]
    filter_texts: dict[str, str]

    @property
    def headers(self) -> list[str]: ...
    @property
    def column_names(self) -> list[str]: ...
    @property
    def row_count(self) -> int: ...
    def rows(self, start: int, stop: int) -> list[tuple[Any, list[str]]]: ...
    def sort_by(self, column: str) -> None: ...
    def is_selected(self, row_id: Any) -> bool: ...
    def select_at(self, position: int) -> None: ...
    def extend_to(self, position: int) -> None: ...
    def activate_at(self, position: int) -> None: ...
    @property
    def count_text(self) -> str: ...
    def header(self, column: str) -> str: ...
    def filter_error(self, column: str, text: str) -> str | None: ...
    def filter_takes_pattern(self, column: str) -> bool: ...
    def filter_placeholder(self, column: str, *, is_pattern: bool = False) -> str: ...
    def filter_chip(self, column: str) -> str: ...
    def selection_text(self) -> str: ...
    def export_csv(self, path: Path) -> None: ...


class TextualDataTableRenderer(TextualWidgetRenderer[DataTableViewLike, ComposeDataFilterTable]):
    """A large table: Textual asks the view for the lines it draws, as the user scrolls.

    A click on a header sorts by its column (`DataTableView.sort_by`). A click on a row,
    or Space on the cursor's, selects it (`select_at`), Shift extending the selection
    (`extend_to`); a double click or Enter activates it (`activate_at`).

    Its filter bar (`ComposeFilterBar`) searches it, and filters the columns of
    `filterable_columns`: the bar knows them by their position among the source's.
    Ctrl+C copies the selected rows to the clipboard (`DataTableView.selection_text`),
    through the terminal. Its key `e` asks where to write the rows as CSV (`export_csv`).
    While a job orders the rows (`is_ordering`), Textual's loading indicator covers them.
    """

    def __init__(self, view: DataTableViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "source": self._refresh_source,
                "row_count": self._reset,
                "column_formats": self._repaint,
                "filter_texts": self._refresh_filter_texts,
                "filterable_columns": self._refresh_filterable_columns,
                "search": self._refresh_search,
                "filters": self._refresh_filters,
                # shown with the order they give, which the view sends as `row_count`
                "sort_column": lambda _view, _table, _value: None,
                "sort_descending": lambda _view, _table, _value: None,
                # each click asks the view, which knows the mode
                "selection_mode": lambda _view, _table, _value: None,
                "selected_ids": self._repaint,
                "texts": self._refresh_texts,
                "export_filename": self._refresh_export_filename,
                "is_ordering": self._refresh_is_ordering,
            }
        )

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = ComposeDataFilterTable(self._view)
            table, bar = self._rendered_object.table, self._rendered_object.bar
            columns = DataTableByPosition(self._view)
            table.header_clicked.connect(columns.sort_by)
            table.row_clicked.connect(
                lambda position, is_extended: columns.select(position, is_extended=is_extended)
            )
            table.row_activated.connect(self._view.activate_at)
            table.copy_requested.connect(self._copy)
            table.export_path_chosen.connect(self._view.export_csv)
            bar.check = columns.filter_error
            bar.placeholder = lambda column, is_pattern: columns.filter_placeholder(
                column, is_pattern=is_pattern
            )
            bar.takes_pattern = columns.filter_takes_pattern
            bar.search_edited.connect(self._update_search)
            bar.filter_added.connect(columns.add_filter)
            bar.filter_removed.connect(columns.remove_filter)
            bar.filters_cleared.connect(columns.clear_filters)

    @classmethod
    def _refresh_source(
        cls, view: DataTableViewLike, rendered_object: ComposeDataFilterTable, value: Any
    ) -> None:
        """Show the new source's columns in the bar, then its rows."""
        cls._refresh_filterable_columns(view, rendered_object, view.filterable_columns)
        cls._refresh_filters(view, rendered_object, view.filters)
        cls._reset(view, rendered_object, value)

    @staticmethod
    def _reset(
        view: DataTableViewLike, rendered_object: ComposeDataFilterTable, _value: Any
    ) -> None:
        """Show a new order of the rows: the sort mark, the count, and no row if none."""
        sort = DataTableByPosition(view).sort
        rendered_object.table.set_sort(sort)
        rendered_object.table.reset()
        rendered_object.bar.set_count(view.count_text)
        rendered_object.empty.display = view.row_count == 0 and view.count_text != ""

    @staticmethod
    def _refresh_export_filename(
        _view: DataTableViewLike, rendered_object: ComposeDataFilterTable, value: str
    ) -> None:
        rendered_object.table.export_filename = value

    @staticmethod
    def _refresh_is_ordering(
        _view: DataTableViewLike, rendered_object: ComposeDataFilterTable, value: bool
    ) -> None:
        rendered_object.table.loading = value

    @staticmethod
    def _refresh_texts(
        _view: DataTableViewLike, rendered_object: ComposeDataFilterTable, value: dict[str, str]
    ) -> None:
        # "empty": the web's; here the headers stay, over no row
        rendered_object.table.set_export_text(value.get("export", ""))

    @staticmethod
    def _refresh_filter_texts(
        view: DataTableViewLike, rendered_object: ComposeDataFilterTable, value: dict[str, str]
    ) -> None:
        rendered_object.bar.set_texts(value)
        rendered_object.bar.set_count(view.count_text)
        rendered_object.empty.update(value.get("no_match", ""))

    @staticmethod
    def _refresh_filterable_columns(
        view: DataTableViewLike, rendered_object: ComposeDataFilterTable, value: list[str]
    ) -> None:
        columns = DataTableByPosition(view).bar_columns(value)
        rendered_object.bar.set_columns(columns)
        rendered_object.bar.display = len(columns) > 0

    @staticmethod
    def _refresh_search(
        _view: DataTableViewLike, rendered_object: ComposeDataFilterTable, value: str
    ) -> None:
        rendered_object.bar.set_search(value)

    @staticmethod
    def _refresh_filters(
        view: DataTableViewLike, rendered_object: ComposeDataFilterTable, value: dict[str, str]
    ) -> None:
        rendered_object.bar.set_filters(DataTableByPosition(view).chips(value))

    def _copy(self) -> None:
        app = self._get_app()
        if app is not None:
            app.copy_to_clipboard(self._view.selection_text())

    def _update_search(self, text: str) -> None:
        with self.stop_refresh():
            self._view.search = text

    @staticmethod
    def _repaint(
        _view: DataTableViewLike, rendered_object: ComposeDataFilterTable, _value: Any
    ) -> None:
        rendered_object.table.repaint()


class TableViewLike(ViewLike, Protocol):
    headers: list[str]
    filter_texts: dict[str, str]
    selection_mode: SelectionMode
    rows: list[list[str]]
    sortable_columns: list[int]
    filterable_columns: list[int]
    sort_column: int | None
    sort_descending: bool
    search: str
    filters: dict[int, str]
    selected_rows: list[int]
    shown_rows: list[int]
    selection_changed: Signal[list[int]]
    editable_columns: list[int]
    cell_edited: Signal[int, int, str]
    cell_widgets: dict[int, CellWidget]
    cell_clicked: Signal[int, int]
    cell_styles: dict[tuple[int, int], CellStyle]
    header_groups: list[HeaderGroup]
    row_headers: list[str]

    def emit_cell_edited(self, row: int, column: int, text: str) -> None: ...
    def mark_text(self, mark: NodeMark) -> str: ...
    def shown_cell_styles(self) -> dict[tuple[int, int], CellStyle]: ...
    def column_checked(self, column: int) -> bool | None: ...
    def check_all(self, column: int, *, is_checked: bool) -> None: ...
    def sort_by(self, column: int) -> None: ...
    def filter_error(self, column: int, text: str) -> str | None: ...
    def filter_placeholder(self, column: int, *, is_pattern: bool = False) -> str: ...
    def filter_takes_pattern(self, column: int) -> bool: ...
    def filter_chip(self, column: int) -> str: ...


class TextualTableRenderer(TextualWidgetRenderer[TableViewLike, ComposeFilterTable]):
    """A table under its filter bar; the table shows `shown_rows`, in their order.

    The widgets know the rows only as shown: their indexes map back to `rows` through
    `shown_rows`.
    """

    def __init__(self, view: TableViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "headers": self._refresh_headers,
                "filter_texts": self._refresh_filter_texts,
                "selection_mode": self._refresh_selection_mode,
                # shown with `shown_rows`, which the view always sends next
                "rows": lambda _view, _table, _value: None,
                "sortable_columns": self._refresh_sort,
                "filterable_columns": self._refresh_filterable_columns,
                "sort_column": self._refresh_sort,
                "sort_descending": self._refresh_sort,
                "search": self._refresh_search,
                "filters": self._refresh_filters,
                "selected_rows": self._refresh_selected_rows,
                "shown_rows": self._refresh_shown_rows,
                "editable_columns": self._refresh_editable_columns,
                "cell_widgets": self._refresh_cell_widgets,
                "cell_styles": self._refresh_looks,
                "header_groups": self._refresh_header_groups,
                "row_headers": self._refresh_looks,
                # a terminal's cell has no tooltip: the mark's glyph says it
                "done_text": lambda _view, _table, _value: None,
                "warning_text": lambda _view, _table, _value: None,
                "error_text": lambda _view, _table, _value: None,
            }
        )

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = ComposeFilterTable()
            table, bar = self._rendered_object.table, self._rendered_object.bar
            table.selected_rows_changed.connect(self._update_selected_rows)
            table.cell_edited.connect(self._update_cell)
            table.cell_clicked.connect(self._click_cell)
            table.check_all_clicked.connect(self._check_all)
            table.header_clicked.connect(self._sort_by)
            bar.check = self._view.filter_error
            bar.placeholder = lambda column, is_pattern: self._view.filter_placeholder(
                column, is_pattern=is_pattern
            )
            bar.takes_pattern = self._view.filter_takes_pattern
            bar.search_edited.connect(self._update_search)
            bar.filter_added.connect(self._add_filter)
            bar.filter_removed.connect(self._remove_filter)
            bar.filters_cleared.connect(self._clear_filters)

    @classmethod
    def _refresh_headers(
        cls, view: TableViewLike, rendered_object: ComposeFilterTable, _value: list[str]
    ) -> None:
        cls._refresh_shown_rows(view, rendered_object, view.shown_rows)
        cls._refresh_filterable_columns(view, rendered_object, view.filterable_columns)
        cls._refresh_filters(view, rendered_object, view.filters)

    @staticmethod
    def _refresh_filter_texts(
        view: TableViewLike, rendered_object: ComposeFilterTable, value: dict[str, str]
    ) -> None:
        rendered_object.bar.set_texts(value)
        rendered_object.bar.set_count(_count_text(view, view.shown_rows))
        rendered_object.empty.update(value.get("no_match", ""))

    @staticmethod
    def _refresh_selection_mode(
        _view: TableViewLike, rendered_object: ComposeFilterTable, value: SelectionMode
    ) -> None:
        rendered_object.table.set_multiple_selection(is_multiple=value is SelectionMode.MULTIPLE)

    @staticmethod
    def _refresh_sort(
        view: TableViewLike, rendered_object: ComposeFilterTable, _value: Any
    ) -> None:
        is_sorted = view.sort_column is not None and view.sort_column in view.sortable_columns
        sort = (view.sort_column, view.sort_descending) if is_sorted else None
        rendered_object.table.set_sort(cast("tuple[int, bool] | None", sort))

    @staticmethod
    def _refresh_filterable_columns(
        view: TableViewLike, rendered_object: ComposeFilterTable, value: list[int]
    ) -> None:
        columns = [(column, view.headers[column]) for column in value if column < len(view.headers)]
        rendered_object.bar.set_columns(columns)
        rendered_object.bar.display = len(columns) > 0

    @staticmethod
    def _refresh_search(
        _view: TableViewLike, rendered_object: ComposeFilterTable, value: str
    ) -> None:
        rendered_object.bar.set_search(value)

    @staticmethod
    def _refresh_filters(
        view: TableViewLike, rendered_object: ComposeFilterTable, value: dict[int, str]
    ) -> None:
        rendered_object.bar.set_filters(
            [
                (column, view.filter_chip(column), text, view.headers[column])
                for column, text in sorted(value.items())
                if column < len(view.headers)
            ]
        )

    @staticmethod
    def _positions(view: TableViewLike, rows: list[int]) -> list[int]:
        """Get where `rows` show, in order."""
        positions = {row: position for position, row in enumerate(view.shown_rows)}
        return sorted(positions[row] for row in rows if row in positions)

    @classmethod
    def _refresh_selected_rows(
        cls, view: TableViewLike, rendered_object: ComposeFilterTable, value: list[int]
    ) -> None:
        rendered_object.table.set_selected_rows(cls._positions(view, value))

    @classmethod
    def _refresh_shown_rows(
        cls, view: TableViewLike, rendered_object: ComposeFilterTable, value: list[int]
    ) -> None:
        rendered_object.table.fill(
            view.headers,
            [view.rows[row] for row in value],
            cls._positions(view, view.selected_rows),
            view.shown_cell_styles(),
            [view.row_headers[row] if row < len(view.row_headers) else "" for row in value]
            if len(view.row_headers) > 0
            else [],
        )
        rendered_object.bar.set_count(_count_text(view, value))
        rendered_object.empty.display = len(value) == 0 and len(view.rows) > 0
        cls._refresh_checked_columns(view, rendered_object)

    @staticmethod
    def _refresh_checked_columns(
        view: TableViewLike,
        rendered_object: ComposeFilterTable,
        *,
        cell_widgets: dict[int, CellWidget] | None = None,
    ) -> None:
        """Show each check-all box; with the new widgets, which the view doesn't hold yet."""
        widgets = view.cell_widgets if cell_widgets is None else cell_widgets
        rendered_object.table.set_checked_columns(
            {
                column: view.column_checked(column)
                for column, widget in widgets.items()
                if widget.kind is CellKind.CHECK_BOX and widget.check_all
            }
        )

    @staticmethod
    def _refresh_editable_columns(
        _view: TableViewLike, rendered_object: ComposeFilterTable, value: list[int]
    ) -> None:
        rendered_object.table.editable_columns = value

    @classmethod
    def _refresh_cell_widgets(
        cls, view: TableViewLike, rendered_object: ComposeFilterTable, value: dict[int, CellWidget]
    ) -> None:
        rendered_object.table.set_cell_widgets(value)
        cls._refresh_checked_columns(view, rendered_object, cell_widgets=value)

    @classmethod
    def _refresh_looks(
        cls, view: TableViewLike, rendered_object: ComposeFilterTable, _value: Any
    ) -> None:
        cls._refresh_shown_rows(view, rendered_object, view.shown_rows)

    @staticmethod
    def _refresh_header_groups(
        _view: TableViewLike, rendered_object: ComposeFilterTable, value: list[HeaderGroup]
    ) -> None:
        rendered_object.table.set_header_groups(value)

    def _update_selected_rows(self, positions: list[int]) -> None:
        shown = self._view.shown_rows
        rows = sorted(shown[position] for position in positions)
        with self.stop_refresh():
            self._view.selected_rows = rows
        self._view.selection_changed.emit(rows)

    def _update_cell(self, position: int, column: int, text: str) -> None:
        rows, row = self._view.rows, self._view.shown_rows[position]
        self._view.emit_cell_edited(row, column, text)
        if self._view.rows is rows:
            with self.stop_refresh():
                self._view.rows = replace_cell(rows, row, column, text)
        if self._rendered_object is not None:  # a check-all box follows its column's
            self._refresh_checked_columns(self._view, self._rendered_object)

    def _click_cell(self, position: int, column: int) -> None:
        self._view.cell_clicked.emit(self._view.shown_rows[position], column)

    def _check_all(self, column: int) -> None:
        if column in self._view.editable_columns:
            self._view.check_all(column, is_checked=self._view.column_checked(column) is not True)

    def _sort_by(self, column: int) -> None:
        if column in self._view.sortable_columns:
            self._view.sort_by(column)

    def _update_search(self, text: str) -> None:
        with self.stop_refresh():
            self._view.search = text

    def _add_filter(self, column: int, text: str) -> None:
        self._view.filters = {**self._view.filters, column: text}

    def _remove_filter(self, column: int) -> None:
        self._view.filters = {
            other: text for other, text in self._view.filters.items() if other != column
        }

    def _clear_filters(self) -> None:
        self._view.filters = {}


def _count_text(view: TableViewLike, shown: list[int]) -> str:
    """Count the rows shown, while the search or the filters hide some."""
    if len(shown) == len(view.rows):
        return ""
    return view.filter_texts.get("count", "").format(shown=len(shown), total=len(view.rows))


class ValuesViewLike(ViewLike, Protocol, Generic[TValue]):
    value: TValue | None
    values: dict[str, TValue]
    value_changed: Signal[TValue | None]


class TextualRadioGroupRenderer(
    TextualWidgetRenderer[ValuesViewLike[TValue], ComposeRadioSet[TValue]], Generic[TValue]
):
    _marks_invalid = True

    def __init__(self, view: ValuesViewLike[TValue]) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "value": self._refresh_value,
                "values": self._refresh_values,
            }
        )

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = ComposeRadioSet(self._view.values)
            self._rendered_object.value_changed.connect(self._update_value)

    @staticmethod
    def _refresh_value(
        _view: ValuesViewLike[TValue], rendered_object: ComposeRadioSet[TValue], value: Any
    ) -> None:
        # `set_values`'s rebuild (remove_children/mount) is asynchronous; selecting
        # synchronously right after races with it and corrupts RadioSet's own
        # bookkeeping (see `_refresh_values`) - defer until the rebuild has landed.
        rendered_object.call_after_refresh(rendered_object.set_value, value)

    @staticmethod
    def _refresh_values(
        view: ValuesViewLike[TValue],
        rendered_object: ComposeRadioSet[TValue],
        values: dict[str, Any],
    ) -> None:
        # rebuilding leaves nothing selected, even if `view.value` didn't itself change
        # (and so wouldn't otherwise trigger its own refresh) - reapply it explicitly
        rendered_object.set_values(values)
        rendered_object.call_after_refresh(rendered_object.set_value, view.value)

    def _update_value(self, value: TValue | None) -> None:
        with self.stop_refresh():
            self._view.value = value
        self._view.value_changed.emit(value)


class TextualComboboxRenderer(
    TextualWidgetRenderer[ValuesViewLike[TValue], ComposeCombobox[TValue]], Generic[TValue]
):
    _marks_invalid = True

    def __init__(self, view: ValuesViewLike[TValue]) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "value": self._refresh_value,
                "values": self._refresh_values,
            }
        )

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = ComposeCombobox(self._view.values)
            self._rendered_object.value_changed.connect(self._update_value)

    @staticmethod
    def _refresh_value(
        _view: ValuesViewLike[TValue], rendered_object: ComposeCombobox[TValue], value: Any
    ) -> None:
        rendered_object.call_after_refresh(rendered_object.set_value, value)

    @staticmethod
    def _refresh_values(
        view: ValuesViewLike[TValue],
        rendered_object: ComposeCombobox[TValue],
        values: dict[str, Any],
    ) -> None:
        rendered_object.set_values(values)
        rendered_object.call_after_refresh(rendered_object.set_value, view.value)

    def _update_value(self, value: TValue | None) -> None:
        with self.stop_refresh():
            self._view.value = value
        self._view.value_changed.emit(value)


class LogViewLike(ViewLike, Protocol):
    log_message: str
    log_type: LogType


class TextualLogRenderer(TextualWidgetRenderer[LogViewLike, Label]):
    def __init__(self, view: LogViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "log_message": self._refresh_log_message,
                "log_type": self._refresh_log_type,
            }
        )

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = Label(markup=False)
            # default `width: auto` sizes to the unwrapped text - fine for a short
            # label, but a long validation message would silently overflow past the
            # terminal width and get clipped instead of wrapping.
            self._rendered_object.styles.width = "1fr"

    @staticmethod
    def _refresh_log_message(_view: LogViewLike, rendered_object: Label, value: str) -> None:
        rendered_object.display = value != ""
        rendered_object.update(value)

    @staticmethod
    def _refresh_log_type(_view: LogViewLike, rendered_object: Label, value: LogType) -> None:
        if value == LogType.ERROR:
            rendered_object.styles.color = "red"
        elif value == LogType.WARNING:
            rendered_object.styles.color = "orange"
        else:
            rendered_object.styles.color = None


class TextualStatusBarRenderer(TextualWidgetRenderer[StatusBar, Static]):
    def __init__(self, view: StatusBar) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "message": self._refresh_message,
            }
        )

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = Static(markup=False)
            self._rendered_object.styles.dock = "bottom"

    @staticmethod
    def _refresh_message(_view: StatusBar, rendered_object: Static, value: str) -> None:
        rendered_object.update(value)


class TextualFormRenderer(TextualWidgetRenderer[FormView, Vertical]):
    def render(self) -> None:
        if self._rendered_object is None:
            rows: list[Widget] = []
            for field_row in self._view.field_rows:
                if isinstance(field_row, FormRowView) and isinstance(
                    field_row.renderer, RendererContainer
                ):
                    row_widgets: list[Widget] = []
                    if isinstance(field_row, FormLabelRowView):
                        row_widgets.append(self._get_label_widget(field_row.renderer))
                    row_widgets.append(self._get_field_widget(field_row.renderer))
                    row_widgets.append(self._get_log_widget(field_row.renderer))
                    row = Vertical(*row_widgets)
                    # `Vertical`'s default `height: 1fr` stretches to fill its parent
                    # instead of sizing to its content, which quietly defeats
                    # `VerticalScroll` (nothing ever appears to overflow the viewport).
                    row.styles.height = "auto"
                    rows.append(row)
                elif (
                    isinstance(field_row.renderer, TextualWidgetRenderer)
                    and field_row.renderer.widget is not None
                ):
                    rows.append(field_row.renderer.widget)
            if (
                isinstance(self._view.log_view.renderer, TextualWidgetRenderer)
                and self._view.log_view.renderer.widget is not None
            ):
                rows.append(self._view.log_view.renderer.widget)
            self._rendered_object = Vertical(*rows)
            self._rendered_object.styles.height = "auto"

    def _get_field_widget(self, field_row_renderer: RendererContainer[View]) -> Widget:
        try:
            field_renderer = field_row_renderer.get_renderer("field")
        except KeyError as e:
            msg = f"The field renderer is missing in the row of the form {self._view}"
            raise ValueError(msg) from e
        if not isinstance(field_renderer, TextualWidgetRenderer) or field_renderer.widget is None:
            raise NoTextualRendererObjectError
        return field_renderer.widget

    def _get_log_widget(self, field_row_renderer: RendererContainer[View]) -> Widget:
        try:
            log_renderer = field_row_renderer.get_renderer("log")
        except KeyError as e:
            msg = f"The log renderer is missing in the row of the form {self._view}"
            raise ValueError(msg) from e
        if not isinstance(log_renderer, TextualLogRenderer) or log_renderer.widget is None:
            raise NoTextualRendererObjectError
        return log_renderer.widget

    def _get_label_widget(self, field_row_renderer: RendererContainer[View]) -> Widget:
        try:
            label_renderer = field_row_renderer.get_renderer("label")
        except KeyError as e:
            msg = f"The label renderer is missing in the row of the form {self._view}"
            raise ValueError(msg) from e
        if not isinstance(label_renderer, TextualFormLabelRenderer) or (
            label_renderer.widget is None
        ):
            raise NoRenderedObjectError
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
        if is_first_render and self._rendered_object is not None:
            # `border_title` has no effect without an actual border to attach it to -
            # without this, every group (e.g. pipeform.py's "Main Pipe"/"Incident Pipe")
            # renders as a plain, undecorated box indistinguishable from the rest of
            # the form, and adjacent groups run into each other with no separation.
            self._rendered_object.styles.border = ("round", "gray")
            self._rendered_object.styles.padding = (0, 1)

    @staticmethod
    def _refresh_title(view: FormView, rendered_object: Vertical, value: str) -> None:
        if isinstance(view, GroupFormView):
            rendered_object.border_title = Content(value)


class TextualPageRenderer(TextualWidgetRenderer[PageView, Vertical]):
    """A page's views in a column, like the screen's own."""

    def render(self) -> None:
        if self._rendered_object is None:
            widgets = [
                view.renderer.widget
                for view in self._view.content_views
                if isinstance(view.renderer, TextualWidgetRenderer)
                and view.renderer.widget is not None
            ]
            self._rendered_object = Vertical(*widgets)
            self._rendered_object.styles.height = "auto"


class TextualHorizontalRenderer(TextualWidgetRenderer[HorizontalView, Horizontal]):
    """Views side by side, each as wide as its share of the row."""

    def render(self) -> None:
        if self._rendered_object is None:
            widgets: list[Widget] = []
            for view, stretch in self._view.stretched_views:
                if (
                    isinstance(view.renderer, TextualWidgetRenderer)
                    and view.renderer.widget is not None
                ):
                    # no share: as wide as its content
                    view.renderer.widget.styles.width = f"{stretch}fr" if stretch > 0 else "auto"
                    widgets.append(view.renderer.widget)
            self._rendered_object = Horizontal(*widgets)
            self._rendered_object.styles.height = "auto"
            if self._view.align is Align.END:
                self._rendered_object.styles.align_horizontal = "right"


class TextualVerticalRenderer(TextualWidgetRenderer[VerticalView, Vertical]):
    """Views one above the other, at the top of the column."""

    def render(self) -> None:
        if self._rendered_object is None:
            widgets = [
                view.renderer.widget
                for view in self._view.children_views
                if isinstance(view.renderer, TextualWidgetRenderer)
                and view.renderer.widget is not None
            ]
            self._rendered_object = Vertical(*widgets)
            self._rendered_object.styles.height = "auto"


class TextualSplitterRenderer(TextualWidgetRenderer[SplitterView, ComposeSplitter]):
    """The panes in a row or a column, a handle between two the user drags or moves by keys."""

    def __init__(self, view: SplitterView) -> None:
        super().__init__(view)
        self._refresh_dispatcher["sizes"] = self._refresh_sizes
        # names a border on the web only
        self._refresh_dispatcher["border_text"] = lambda _view, _splitter, _value: None

    def render(self) -> None:
        if self._rendered_object is None:
            panes = [
                view.renderer.widget
                for view in self._view.panes
                if isinstance(view.renderer, TextualWidgetRenderer)
                and view.renderer.widget is not None
            ]
            self._rendered_object = ComposeSplitter(
                *panes, is_vertical=self._view.orientation is Orientation.VERTICAL
            )
            self._rendered_object.resized.connect(self._update_sizes)

    @staticmethod
    def _refresh_sizes(
        _view: SplitterView, rendered_object: ComposeSplitter, value: list[int]
    ) -> None:
        rendered_object.set_sizes(value)

    def _update_sizes(self, lengths: list[int]) -> None:
        sizes = self._view.shares_of(lengths)
        if sizes == self._view.sizes:  # a click, or a move against a pane's minimum
            return
        with self.stop_refresh():
            self._view.sizes = sizes
        self._view.resized.emit(sizes)


class TextualExpanderRenderer(TextualWidgetRenderer[ExpanderView, ComposeCollapsible]):
    """Textual's collapsible: its title, then the views one above the other while expanded."""

    def __init__(self, view: ExpanderView) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {"title": self._refresh_title, "is_expanded": self._refresh_is_expanded}
        )

    def render(self) -> None:
        if self._rendered_object is None:
            widgets = [
                view.renderer.widget
                for view in self._view.children_views
                if isinstance(view.renderer, TextualWidgetRenderer)
                and view.renderer.widget is not None
            ]
            self._rendered_object = ComposeCollapsible(*widgets)
            self._rendered_object.toggled.connect(self._update_expanded)

    @staticmethod
    def _refresh_title(
        _view: ExpanderView, rendered_object: ComposeCollapsible, value: str
    ) -> None:
        rendered_object.title = value

    @staticmethod
    def _refresh_is_expanded(
        _view: ExpanderView, rendered_object: ComposeCollapsible, value: bool
    ) -> None:
        rendered_object.set_expanded(value)

    def _update_expanded(self, is_expanded: bool) -> None:
        with self.stop_refresh():
            self._view.is_expanded = is_expanded
        self._view.toggled.emit(is_expanded)


class TextualSidebarRenderer(TextualWidgetRenderer[SidebarView, ComposeSidebar]):
    """A column on the screen's left: its title and an arrow retracting it, then its views."""

    def __init__(self, view: SidebarView) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "title": self._refresh_title,
                "toggle_text": self._refresh_toggle_text,
                "is_expanded": self._refresh_is_expanded,
            }
        )

    def render(self) -> None:
        if self._rendered_object is None:
            widgets = [
                view.renderer.widget
                for view in self._view.children_views
                if isinstance(view.renderer, TextualWidgetRenderer)
                and view.renderer.widget is not None
            ]
            self._rendered_object = ComposeSidebar(*widgets)
            self._rendered_object.toggled.connect(self._update_expanded)

    @staticmethod
    def _refresh_title(_view: SidebarView, rendered_object: ComposeSidebar, value: str) -> None:
        rendered_object.set_title(value)

    @staticmethod
    def _refresh_toggle_text(
        _view: SidebarView, rendered_object: ComposeSidebar, value: str
    ) -> None:
        rendered_object.toggle.tooltip = Content(value)

    @staticmethod
    def _refresh_is_expanded(
        _view: SidebarView, rendered_object: ComposeSidebar, value: bool
    ) -> None:
        rendered_object.set_expanded(value)

    def _update_expanded(self, is_expanded: bool) -> None:
        with self.stop_refresh():
            self._view.is_expanded = is_expanded
        self._view.toggled.emit(is_expanded)


class TextualListRenderer(TextualWidgetRenderer["ListView[Any]", ComposeList]):
    """The records' views one above the other, added, moved and removed as they change.

    Widgets only mount in a running app: the column is put in step with the records once
    it is mounted (`_refresh_tree` refreshes it then too), a record's widget built since
    mounted next to its neighbours, then given its view's state.
    """

    def __init__(self, view: ListView[Any]) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update({"item_views": self._refresh_item_views})

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = ComposeList(*self._widgets(self._view.item_views))

    @staticmethod
    def _widgets(views: list[View]) -> list[Widget]:
        """Get the views' widgets, rendering the views built since the list was."""
        widgets: list[Widget] = []
        for view in views:
            if view.renderer is None:
                view.render(RendererType.TEXTUAL)
            if (
                isinstance(view.renderer, TextualWidgetRenderer)
                and view.renderer.widget is not None
            ):
                widgets.append(view.renderer.widget)
        return widgets

    @staticmethod
    def _refresh_item_views(_view: ListView[Any], column: ComposeList, value: list[View]) -> None:
        widgets = TextualListRenderer._widgets(value)
        if not column.is_attached:
            return  # put in step once mounted
        for child in list(column.children):
            if child not in widgets:
                child.remove()  # its record is gone
        previous: Widget | None = None
        for view, widget in zip(value, widgets):
            if widget.parent is column:
                if previous is not None:
                    column.move_child(widget, after=previous)
                elif column.children[0] is not widget:
                    column.move_child(widget, before=0)
            else:
                if previous is not None:
                    mounting = column.mount(widget, after=previous)
                elif len(column.children) > 0:
                    mounting = column.mount(widget, before=0)
                else:
                    mounting = column.mount(widget)
                column.call_next(TextualListRenderer._refresh_once_mounted, mounting, view)
            previous = widget

    @staticmethod
    async def _refresh_once_mounted(mounting: AwaitMount, view: View) -> None:
        """Give `view`'s widgets its state once mounted: Textual's widgets take it only then."""
        await mounting
        _refresh_tree(view)


class TextualTreeRenderer(TextualWidgetRenderer[TreeView, ComposeTree]):
    def __init__(self, view: TreeView) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "nodes": self._refresh_nodes,
                "expanded": self._refresh_expanded,
                "selected": self._refresh_selected,
                # a terminal shows the marks' glyphs, not their names
                "done_text": lambda _view, _rendered_object, _value: None,
                "warning_text": lambda _view, _rendered_object, _value: None,
                "error_text": lambda _view, _rendered_object, _value: None,
            }
        )

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = ComposeTree()
            self._rendered_object.selected.connect(self._update_selected)
            self._rendered_object.toggled.connect(self._update_expanded)

    @staticmethod
    def _refresh_nodes(view: TreeView, rendered_object: ComposeTree, value: list[TreeNode]) -> None:
        # the view's, already kept to those still in the nodes
        rendered_object.set_nodes(value, view.expanded, view.selected)

    @staticmethod
    def _refresh_expanded(
        _view: TreeView, rendered_object: ComposeTree, value: list[TreePath]
    ) -> None:
        rendered_object.set_expanded(value)

    @staticmethod
    def _refresh_selected(
        _view: TreeView, rendered_object: ComposeTree, value: TreePath | None
    ) -> None:
        rendered_object.set_selected(value)

    def _update_selected(self, path: TreePath) -> None:
        with self.stop_refresh():
            self._view.selected = path
        self._view.selection_changed.emit(path)

    def _update_expanded(self, path: TreePath, is_expanded: bool) -> None:
        with self.stop_refresh():
            self._view.expanded = self._view.expanded_with(path, is_expanded=is_expanded)
        self._view.toggled.emit(path, is_expanded)


class TextualTabPageRenderer(TextualWidgetRenderer[TabPage, TabPane]):
    """A tab's views in a pane; its title, visibility and enabled state are its tab's."""

    def __init__(self, view: TabPage) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "title": self._refresh_title,
                "is_visible": self._refresh_tab_visible,
                "is_enabled": self._refresh_tab_enabled,
            }
        )

    def render(self) -> None:
        if self._rendered_object is None:
            widgets = [
                view.renderer.widget
                for view in self._view.children_views
                if isinstance(view.renderer, TextualWidgetRenderer)
                and view.renderer.widget is not None
            ]
            # an id: the tabs tell their panes by it
            self._rendered_object = TabPane(
                Content(self._view.title), *widgets, id=f"cui-{id(self._view)}-tab"
            )

    @staticmethod
    def _tabs(pane: TabPane) -> ComposeTabbedContent | None:
        """Get the tabs `pane` is a tab of, once mounted."""
        if not pane.is_attached:
            return None
        return next((a for a in pane.ancestors if isinstance(a, ComposeTabbedContent)), None)

    @staticmethod
    def _refresh_title(_view: TabPage, rendered_object: TabPane, value: str) -> None:
        tabs = TextualTabPageRenderer._tabs(rendered_object)
        if tabs is not None:
            tabs.get_tab(rendered_object).label = Content(value)

    @staticmethod
    def _refresh_tab_visible(_view: TabPage, rendered_object: TabPane, value: bool) -> None:
        # not the pane's own display: only the current tab's pane shows
        tabs = TextualTabPageRenderer._tabs(rendered_object)
        if tabs is not None and rendered_object.id is not None:
            if value:
                tabs.show_tab(rendered_object.id)
            else:
                tabs.hide_tab(rendered_object.id)

    @staticmethod
    def _refresh_tab_enabled(_view: TabPage, rendered_object: TabPane, value: bool) -> None:
        rendered_object.disabled = not value  # its tab follows


class TextualTabsRenderer(TextualWidgetRenderer[TabView, ComposeTabbedContent]):
    """Textual's tabbed content: the tabs in a row, the current one's pane under them."""

    def __init__(self, view: TabView) -> None:
        super().__init__(view)
        self._refresh_dispatcher["current_index"] = self._refresh_current_index

    def render(self) -> None:
        if self._rendered_object is None:
            panes = [
                tab.renderer.widget
                for tab in self._view.tabs
                if isinstance(tab.renderer, TextualTabPageRenderer)
                and tab.renderer.widget is not None
            ]
            self._rendered_object = ComposeTabbedContent(*panes)
            self._rendered_object.picked.connect(self._update_current_index)

    @staticmethod
    def _pane_id(tab: TabPage) -> str | None:
        """Get the id of `tab`'s pane, which the tabs tell it by."""
        renderer = tab.renderer
        if isinstance(renderer, TextualTabPageRenderer) and renderer.widget is not None:
            return renderer.widget.id
        return None

    @staticmethod
    def _refresh_current_index(
        view: TabView, rendered_object: ComposeTabbedContent, value: int
    ) -> None:
        pane_id = TextualTabsRenderer._pane_id(view.tabs[value])
        if pane_id is not None and rendered_object.is_attached:
            rendered_object.set_active(pane_id)

    @staticmethod
    def _index(view: TabView, pane_id: str) -> int | None:
        """Get the index of the tab whose pane is `pane_id`."""
        ids = [TextualTabsRenderer._pane_id(tab) for tab in view.tabs]
        return ids.index(pane_id) if pane_id in ids else None

    def _update_current_index(self, pane: TabPane) -> None:
        index = self._index(self._view, pane.id or "")
        if index is None or index == self._view.current_index:
            return
        with self.stop_refresh():
            self._view.current_index = index
        self._view.current_changed.emit(index)


class TextualGridRenderer(TextualWidgetRenderer[GridView, Grid]):
    """Views in a grid's cells: equally wide columns, rows as tall as their views.

    Textual's grid flows its widgets into the next free cell: each view sits in a cell
    widget, empty for cells no view takes, so a hidden view leaves its cell in place.
    """

    def render(self) -> None:
        if self._rendered_object is None:
            at_cell = {
                (position.row, position.column): (view, position)
                for view, position in self._view.positioned_views
            }
            taken: set[tuple[int, int]] = set()
            cells: list[Widget] = []
            for row in range(self._view.row_count):
                for column in range(self._view.column_count):
                    if (row, column) in taken:
                        continue
                    view, position = at_cell.get((row, column), (None, GridPosition(row, column)))
                    taken.update(position.cells)
                    cell = Container()
                    if (
                        view is not None
                        and isinstance(view.renderer, TextualWidgetRenderer)
                        and view.renderer.widget is not None
                    ):
                        # with no share of a row, as wide as its content
                        view.renderer.widget.styles.width = (
                            "1fr" if view.default_stretch > 0 else "auto"
                        )
                        cell = Container(view.renderer.widget)
                    cell.styles.row_span = position.row_span
                    cell.styles.column_span = position.column_span
                    cell.styles.height = "auto"
                    cells.append(cell)
            self._rendered_object = Grid(*cells)
            self._rendered_object.styles.grid_size_columns = self._view.column_count
            self._rendered_object.styles.grid_columns = "1fr"
            self._rendered_object.styles.grid_rows = "auto"
            self._rendered_object.styles.height = "auto"


class TextualRouterRenderer(TextualWidgetRenderer[Router, ContentSwitcher]):
    """The pages, one shown at a time, and a toolbar of their actions docked at the top.

    Each page sits in a slot of its own: the switcher shows and hides its slots, which
    leaves the page's own `is_visible` to the page.
    """

    def __init__(self, view: Router) -> None:
        super().__init__(view)
        #: the toolbar of the pages' actions, docked by the main renderer
        self.toolbar: ComposeToolbar | None = None
        self._refresh_dispatcher.update({"current_route": self._refresh_current_route})

    def render(self) -> None:
        if self._rendered_object is None:
            buttons: list[Widget] = []
            slots: list[Widget] = []
            for page in self._view.pages:
                if isinstance(page.action.renderer, TextualActionRenderer):
                    button = ComposeToolbarButton()
                    button.triggered.connect(page.action.triggered.emit)
                    page.action.renderer.button = button
                    buttons.append(button)
                page_widgets = (
                    [page.renderer.widget]
                    if isinstance(page.renderer, TextualPageRenderer)
                    and page.renderer.widget is not None
                    else []
                )
                slot = Vertical(*page_widgets, id=_slot_id(page.route))
                slot.styles.height = "auto"
                slots.append(slot)
            self.toolbar = ComposeToolbar(*buttons)
            self._rendered_object = ContentSwitcher(
                *slots, initial=_slot_id(self._view.current_route)
            )

    @staticmethod
    def _refresh_current_route(_view: Router, rendered_object: ContentSwitcher, value: str) -> None:
        rendered_object.current = _slot_id(value)


class TextualToolBarRenderer(TextualWidgetRenderer[ToolBar, ComposeToolbar]):
    """A row of buttons, one per action, docked at the top by the main renderer."""

    def __init__(self, view: ToolBar) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update({"title": self._noop})

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
        if isinstance(app, _ComposeUIApp):
            app.trigger(action_view)

    @staticmethod
    def _noop(_view: ToolBar, _rendered_object: ComposeToolbar, _value: Any) -> None:
        pass  # a row of buttons has no title to show


def _slot_id(route: str) -> str:
    """Get the id of a page's slot in its router's switcher (routes are valid ids)."""
    return f"page-{route}"


def _refresh_tree(root: View) -> None:
    """Push each view's current state into its already-built (default) widget.

    Widgets are constructed bottom-up before the app runs (mirroring the Qt
    backend), but Textual reactives like `Input.value` need a running app to be
    *set* at all - so unlike Qt, the initial state can't be pushed in during that
    same construction pass. This walks the tree once the app has mounted, when it's
    finally safe to do so.
    """
    views: deque[View] = deque([root])
    while views:
        current = views.popleft()
        if isinstance(current.renderer, (Renderer, RendererContainer)):
            current.renderer.refresh()
        views.extend(current.children_views)


def _to_textual_key(shortcut: str) -> str:
    """Convert a Qt-style shortcut (`"Ctrl+Shift+s"`) to Textual's key format (`"ctrl+shift+s"`)."""
    return "+".join(part.lower() for part in shortcut.split("+"))


# Actions that can show a blocking file-picker modal - see `_ComposeUIApp.action_trigger`.
_FILE_DIALOG_ACTIONS = (OpenFileAction, PickFileAction, SaveAction, SaveAsAction)


def _register_actions(app: _ComposeUIApp, root: View) -> None:
    """Turn every `ActionView` with a shortcut into a key binding, discoverable via `Footer`.

    Menus aren't rendered as widgets under Textual (see `TextualMenuRenderer`); their
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
            if isinstance(current.renderer, TextualActionRenderer):
                current.renderer.app = app
        views.extend(current.children_views)


class _ComposeUIApp(App[None]):
    def __init__(self, view: MainView, root: Widget) -> None:
        self._view = view
        self._root = root
        self.registered_actions: dict[str, ActionView] = {}
        #: called once the app is mounted, e.g. to start a timer, which needs it running
        self.mounted_callbacks: list[Callable[[], None]] = []
        super().__init__()

    def compose(self) -> ComposeResult:
        yield self._root
        yield Footer()

    def on_mount(self) -> None:
        self.title = self._view.title
        _refresh_tree(self._view)
        _register_actions(self, self._view)
        for callback in self.mounted_callbacks:
            callback()

    def action_trigger(self, action_id: str) -> None:
        action_view = self.registered_actions.get(action_id)
        if action_view is not None:
            self.trigger(action_view)

    def trigger(self, action_view: ActionView) -> None:
        """Trigger an action from its key binding or its toolbar button."""
        if isinstance(action_view, _FILE_DIALOG_ACTIONS):
            # `ask_open_filepath`/`ask_save_filepath` block waiting for a modal file
            # picker; blocking the app's own thread that way would freeze the very
            # loop that has to render and drive that modal, so this specific trigger
            # runs on a worker thread instead (`TextualMainRenderer.open_file`/
            # `save_file` bridge back via `call_from_thread`). Everything else
            # dispatches directly, matching Qt's immediate, synchronous `emit()`.
            self.run_worker(action_view.triggered.emit, thread=True)
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


class TextualMainRenderer(MainRenderer[MainView, _ComposeUIApp]):
    def __init__(self, view: MainView) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "title": self._refresh_title,
                "is_visible": self._noop,
                "is_enabled": self._noop,
                "minimum_width": self._noop,
                "minimum_height": self._noop,
                "state_filepath": self._noop,
            }
        )

    @property
    def app(self) -> _ComposeUIApp | None:
        return self._rendered_object

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = _ComposeUIApp(self._view, self._root_widget())
            views: deque[View] = deque(self._view.children_views)
            while views:
                view = views.popleft()
                if isinstance(view.renderer, TextualDialogRenderer):
                    view.renderer.app = self._rendered_object
                views.extend(view.children_views)
            self.refresh()

    def _root_widget(self) -> Widget:
        """Lay out the screen: the toolbars and the status bar docked, the rest scrolling.

        `StatusBar` is docked to the real bottom of the terminal (see
        `TextualStatusBarRenderer`) and the toolbars to the top; everything else goes in
        a `VerticalScroll` so content taller than the screen stays reachable instead of
        clipped, beside the sidebar, if any, scrolling on its own.
        """
        scrollable: list[Widget] = []
        toolbars: list[Widget] = []
        docked: list[Widget] = []
        sidebars: list[Widget] = []
        for child_view in self._view.children_views:
            if not (
                isinstance(child_view.renderer, TextualWidgetRenderer)
                and child_view.renderer.widget is not None
            ):
                continue
            widget = child_view.renderer.widget
            if isinstance(child_view, StatusBar):
                docked.append(widget)
            elif isinstance(child_view, ToolBar):
                toolbars.append(widget)
            elif isinstance(child_view, SidebarView):
                sidebars.append(widget)
            elif isinstance(child_view.renderer, TextualRouterRenderer):
                if child_view.renderer.toolbar is not None:
                    toolbars.append(child_view.renderer.toolbar)
                scrollable.append(widget)
            else:
                scrollable.append(widget)
        if len(toolbars) > 0:
            docked.append(ComposeToolbars(*toolbars))
        content: Widget = VerticalScroll(*scrollable)
        if len(sidebars) > 0:
            # beside the content, scrolling on its own: shown whatever the page
            content = Horizontal(*sidebars, content)
        return Vertical(content, *docked)

    def call_on_main_thread(self, callback: Callable[[], None]) -> None:
        _call_on_app_thread(self._rendered_object, callback)

    def refresh(self) -> None:
        # see `TextualWidgetRenderer.refresh` - same cross-thread hazard applies here.
        self.call_on_main_thread(super().refresh)

    def refresh_attribute(self, attr_name: str, value: Any) -> None:
        self.call_on_main_thread(functools.partial(super().refresh_attribute, attr_name, value))

    def close(self) -> None:
        if self._rendered_object is not None:
            self._rendered_object.exit()

    def open_file(self) -> Path | None:
        """Return an existing file selected by the user.

        Must be called from a worker thread (see `_ComposeUIApp.action_trigger`):
        `call_from_thread` blocks the calling thread while the modal runs on the
        app's own thread, which would deadlock if they were the same thread.
        """
        if self._rendered_object is None:
            raise NoTextualRendererObjectError
        app = self._rendered_object

        async def _show() -> Path | None:
            return await app.push_screen_wait(FileOpen(filters=self._build_filters()))

        # mypy can't resolve `call_from_thread`'s `CallThreadReturnType` from an async
        # callback; the return type is verified manually via `_show`'s own annotation.
        result = cast("Path | None", app.call_from_thread(_show))  # type: ignore[arg-type]
        return self._apply_default_extension(result)

    def save_file(self) -> Path | None:
        """Return a file path selected by the user to save to.

        See `open_file` for why this must be called from a worker thread.
        """
        if self._rendered_object is None:
            raise NoTextualRendererObjectError
        app = self._rendered_object

        async def _show() -> Path | None:
            return await app.push_screen_wait(FileSave(filters=self._build_filters()))

        # mypy can't resolve `call_from_thread`'s `CallThreadReturnType` from an async
        # callback; the return type is verified manually via `_show`'s own annotation.
        result = cast("Path | None", app.call_from_thread(_show))  # type: ignore[arg-type]
        return self._apply_default_extension(result)

    def _build_filters(self) -> Filters:
        return Filters(
            *(
                Filter(name, functools.partial(_has_any_extension, extensions=extensions))
                for name, extensions in self._view.file_view.extensions.items()
            )
        )

    def _apply_default_extension(self, filepath: Path | None) -> Path | None:
        if filepath is None:
            return None
        all_extensions: tuple[str, ...] = tuple(
            e for exts in self._view.file_view.extensions.values() for e in exts
        )
        if all_extensions and not _has_any_extension(filepath, all_extensions):
            filepath = filepath.with_name(filepath.name + all_extensions[0])
        return filepath

    @staticmethod
    def _refresh_title(_view: MainView, rendered_object: _ComposeUIApp, value: str) -> None:
        rendered_object.title = value

    @staticmethod
    def _noop(_view: MainView, _rendered_object: _ComposeUIApp, _value: Any) -> None:
        pass


#: renderer keys of the Textual backend, looked up by `composeui.core.registry.create_renderer`
RENDERERS: dict[str, Callable[[Any], Renderer[Any, Any]]] = {
    "action": TextualActionRenderer,
    "button": TextualButtonRenderer,
    "chart": TextualChartRenderer,
    "checkbox": TextualCheckBoxRenderer,
    "combobox": TextualComboboxRenderer,
    "data_table": TextualDataTableRenderer,
    "date_input": TextualDateInputRenderer,
    "file_path_input": TextualFilePathInputRenderer,
    "dialog": TextualDialogRenderer,
    "expander": TextualExpanderRenderer,
    "float_input": TextualFloatInputRenderer,
    "int_input": TextualIntInputRenderer,
    "form": TextualFormRenderer,
    "form_dialog": TextualFormDialogRenderer,
    "form_label": TextualFormLabelRenderer,
    "grid": TextualGridRenderer,
    "group_form": TextualGroupFormRenderer,
    "horizontal": TextualHorizontalRenderer,
    "input": TextualInputRenderer,
    "label": TextualLabelRenderer,
    "list": TextualListRenderer,
    "log": TextualLogRenderer,
    "main": TextualMainRenderer,
    "markdown": TextualMarkdownRenderer,
    "menu": TextualMenuRenderer,
    "metric": TextualMetricRenderer,
    "page": TextualPageRenderer,
    "progress_bar": TextualProgressBarRenderer,
    "slider": TextualSliderRenderer,
    "radio_group": TextualRadioGroupRenderer,
    "router": TextualRouterRenderer,
    "separator": TextualSeparatorRenderer,
    "sidebar": TextualSidebarRenderer,
    "splitter": TextualSplitterRenderer,
    "status_bar": TextualStatusBarRenderer,
    "table": TextualTableRenderer,
    "tab_page": TextualTabPageRenderer,
    "tabs": TextualTabsRenderer,
    "toolbar": TextualToolBarRenderer,
    "tree": TextualTreeRenderer,
    "vertical": TextualVerticalRenderer,
}

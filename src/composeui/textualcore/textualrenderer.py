from __future__ import annotations

import contextlib
import functools
from collections import deque
from typing import TYPE_CHECKING, Any, Generic, TypeVar, cast

from textual.app import App, ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.types import NoActiveAppError
from textual.validation import Number
from textual.widgets import Footer, Label, Static
from textual_fspicker import FileOpen, FileSave
from textual_fspicker.path_filters import Filter, Filters
from typing_extensions import Protocol

from composeui.core.renderer import (
    MainRenderer,
    NoRenderedObjectError,
    Renderer,
    RendererContainer,
    ViewLike,
)
from composeui.core.view import (
    ActionView,
    FormLabelRowView,
    FormRowView,
    FormView,
    GroupFormView,
    LogType,
    MainView,
    Menu,
    OpenFileAction,
    SaveAction,
    SaveAsAction,
    SeparatorAction,
    StatusBar,
    View,
)
from composeui.textualcore.widgets.composecombobox import ComposeCombobox
from composeui.textualcore.widgets.composeinput import ComposeInput
from composeui.textualcore.widgets.composeradioset import ComposeRadioSet

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from textual.widget import Widget

    from composeui.core.signal import Signal, SignalNoArgs

TView = TypeVar("TView", bound=ViewLike)
TWidget = TypeVar("TWidget", bound="Widget")
TValue = TypeVar("TValue")


class NoTextualRendererObjectError(Exception):
    def __init__(self) -> None:
        super().__init__("Renderer should be inherited by TextualRenderer")


def _has_any_extension(filepath: Path, extensions: tuple[str, ...]) -> bool:
    return any(filepath.name.endswith(extension) for extension in extensions)


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


class TextualWidgetRenderer(Renderer[TView, TWidget]):
    def __init__(self, view: TView) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "is_visible": self._refresh_visible,
                "is_enabled": self._refresh_enabled,
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
        try:
            return self._rendered_object.app
        except NoActiveAppError:
            return None

    def refresh(self) -> None:
        # Textual widgets aren't thread-safe (see `App.call_from_thread`'s own
        # docstring) - state can legitimately change from a non-main thread (e.g.
        # `MainView.load_state` running as part of a worker-dispatched file-open
        # action, see `_ComposeUIApp.action_trigger`). `call_on_main_thread` already
        # falls back to a direct call when we're already on the right thread, so this
        # is a no-op in the common case.
        self.call_on_main_thread(super().refresh)

    def refresh_attribute(self, attr_name: str, value: Any) -> None:
        self.call_on_main_thread(functools.partial(super().refresh_attribute, attr_name, value))

    @staticmethod
    def _refresh_visible(_view: TView, rendered_object: TWidget, value: bool) -> None:
        rendered_object.display = value

    @staticmethod
    def _refresh_enabled(_view: TView, rendered_object: TWidget, value: bool) -> None:
        rendered_object.disabled = not value


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

    @staticmethod
    def _update_state(view: TNoopView, rendered_object: TNoopView) -> None:
        pass  # nothing user-editable to read back


class TextualActionRenderer(_TextualNoopRenderer[ActionView]):
    """No visual widget: `_ComposeUIApp` turns actions into key bindings + `Footer` entries."""


class TextualSeparatorRenderer(_TextualNoopRenderer[SeparatorAction]):
    pass


class TextualMenuRenderer(_TextualNoopRenderer[Menu]):
    """No visual widget: a `Menu`'s children register themselves directly with the app."""


class InputViewLike(ViewLike, Protocol):
    placeholder: str
    text: str
    text_changed: Signal[str]
    text_edited: Signal[str]
    editing_finished: SignalNoArgs


class TextualInputRenderer(TextualWidgetRenderer[InputViewLike, ComposeInput]):
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

    @staticmethod
    def _update_state(view: InputViewLike, rendered_object: ComposeInput) -> None:
        view.text = rendered_object.value
        view.placeholder = rendered_object.placeholder

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


class TextualFloatInputRenderer(TextualWidgetRenderer[FloatInputViewLike, ComposeInput]):
    def __init__(self, view: FloatInputViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "value": self._refresh_value,
                "placeholder": self._refresh_placeholder,
                "minimum": self._refresh_minimum,
                "maximum": self._refresh_maximum,
                # No widget-level equivalent of Qt's `QDoubleValidator.setDecimals`:
                # Textual's `Number` validator only bounds min/max, so `decimals` is
                # tracked on the view but not enforced by the rendered widget.
            }
        )

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = ComposeInput()
            self._rendered_object.value_changed.connect(self._update_text)
            self._rendered_object.value_submitted.connect(self._editing_finished)

    @staticmethod
    def _refresh_value(
        _view: FloatInputViewLike, rendered_object: ComposeInput, value: float | None
    ) -> None:
        rendered_object.value = str(value) if value is not None else ""

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

    @staticmethod
    def _update_state(view: FloatInputViewLike, rendered_object: ComposeInput) -> None:
        text = rendered_object.value
        view.value = float(text) if text != "" else None
        view.placeholder = rendered_object.placeholder

    def _update_text(self, text: str) -> None:
        # transient invalid text while typing (e.g. "-", "1."); ignore it
        with self.stop_refresh(), contextlib.suppress(ValueError):
            self._view.value = float(text) if text != "" else None
        self._view.text_changed.emit(text)
        self._view.text_edited.emit(text)

    def _editing_finished(self) -> None:
        self._view.editing_finished.emit()


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
            self._rendered_object = Label()

    @staticmethod
    def _refresh_text(_view: LabelViewLike, rendered_object: Label, value: str) -> None:
        rendered_object.update(value)

    @staticmethod
    def _update_state(view: LabelViewLike, rendered_object: Label) -> None:
        pass  # a Label's text isn't user-editable; nothing to read back


class TextualFormLabelRenderer(TextualWidgetRenderer[FormLabelRowView, Label]):
    def __init__(self, view: FormLabelRowView) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "label": self._refresh_text,
            }
        )

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = Label()

    @staticmethod
    def _refresh_text(_view: FormLabelRowView, rendered_object: Label, value: str) -> None:
        rendered_object.update(value)

    @staticmethod
    def _update_state(view: FormLabelRowView, rendered_object: Label) -> None:
        pass  # a Label's text isn't user-editable; nothing to read back


class ValuesViewLike(ViewLike, Protocol, Generic[TValue]):
    value: TValue | None
    values: dict[str, TValue]
    value_changed: Signal[TValue | None]


class TextualRadioGroupRenderer(
    TextualWidgetRenderer[ValuesViewLike[TValue], ComposeRadioSet[TValue]], Generic[TValue]
):
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

    @staticmethod
    def _update_state(
        view: ValuesViewLike[TValue], rendered_object: ComposeRadioSet[TValue]
    ) -> None:
        view.value = rendered_object.value()

    def _update_value(self, value: TValue | None) -> None:
        with self.stop_refresh():
            self._view.value = value
        self._view.value_changed.emit(value)


class TextualComboboxRenderer(
    TextualWidgetRenderer[ValuesViewLike[TValue], ComposeCombobox[TValue]], Generic[TValue]
):
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

    @staticmethod
    def _update_state(
        view: ValuesViewLike[TValue], rendered_object: ComposeCombobox[TValue]
    ) -> None:
        view.value = rendered_object.current_value()

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
            self._rendered_object = Label()
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

    @staticmethod
    def _update_state(view: LogViewLike, rendered_object: Label) -> None:
        pass  # a Label's text isn't user-editable; nothing to read back


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
            self._rendered_object = Static()
            self._rendered_object.styles.dock = "bottom"

    @staticmethod
    def _refresh_message(_view: StatusBar, rendered_object: Static, value: str) -> None:
        rendered_object.update(value)

    @staticmethod
    def _update_state(view: StatusBar, rendered_object: Static) -> None:
        pass  # a Static's text isn't user-editable; nothing to read back


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

    @staticmethod
    def _update_state(view: FormView, rendered_object: Vertical) -> None:
        pass  # a form container has no user-editable state of its own


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
            rendered_object.border_title = value


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
_FILE_DIALOG_ACTIONS = (OpenFileAction, SaveAction, SaveAsAction)


def _register_actions(app: _ComposeUIApp, root: View) -> None:
    """Turn every `ActionView` with a shortcut into a key binding, discoverable via `Footer`.

    Menus aren't rendered as widgets under Textual (see `TextualMenuRenderer`); their
    actions are exposed as app-wide key bindings instead, mirroring the "Menu/Action
    style: key bindings + Footer" scope chosen for this backend.
    """
    views: deque[View] = deque([root])
    while views:
        current = views.popleft()
        if isinstance(current, ActionView) and current.shortcut is not None:
            action_id = str(id(current))
            app.registered_actions[action_id] = current
            app.bind(
                _to_textual_key(current.shortcut),
                f"trigger({action_id!r})",
                description=current.text,
            )
        views.extend(current.children_views)


class _ComposeUIApp(App[None]):
    def __init__(self, view: MainView, root: Widget) -> None:
        self._view = view
        self._root = root
        self.registered_actions: dict[str, ActionView] = {}
        super().__init__()

    def compose(self) -> ComposeResult:
        yield self._root
        yield Footer()

    def on_mount(self) -> None:
        self.title = self._view.title
        _refresh_tree(self._view)
        _register_actions(self, self._view)

    def action_trigger(self, action_id: str) -> None:
        action_view = self.registered_actions.get(action_id)
        if action_view is None:
            return
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
            # `StatusBar` is docked to the real bottom of the terminal (see
            # `TextualStatusBarRenderer`); everything else goes in a `VerticalScroll`
            # so content taller than the screen stays reachable instead of clipped.
            scrollable: list[Widget] = []
            docked: list[Widget] = []
            for child_view in self._view.children_views:
                if not (
                    isinstance(child_view.renderer, TextualWidgetRenderer)
                    and child_view.renderer.widget is not None
                ):
                    continue
                widget = child_view.renderer.widget
                if isinstance(child_view, StatusBar):
                    docked.append(widget)
                else:
                    scrollable.append(widget)
            root = Vertical(VerticalScroll(*scrollable), *docked)
            self._rendered_object = _ComposeUIApp(self._view, root)
            self.refresh()

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

    @staticmethod
    def _update_state(view: MainView, rendered_object: _ComposeUIApp) -> None:
        view.title = rendered_object.title


#: renderer keys of the Textual backend, looked up by `composeui.core.registry.create_renderer`
RENDERERS: dict[str, Callable[[Any], Renderer[Any, Any]]] = {
    "action": TextualActionRenderer,
    "combobox": TextualComboboxRenderer,
    "float_input": TextualFloatInputRenderer,
    "form": TextualFormRenderer,
    "form_label": TextualFormLabelRenderer,
    "group_form": TextualGroupFormRenderer,
    "input": TextualInputRenderer,
    "label": TextualLabelRenderer,
    "log": TextualLogRenderer,
    "main": TextualMainRenderer,
    "menu": TextualMenuRenderer,
    "radio_group": TextualRadioGroupRenderer,
    "separator": TextualSeparatorRenderer,
    "status_bar": TextualStatusBarRenderer,
}

# from __future__ import annotations

import enum
import functools
import json
import logging
import re
import sys
import threading
from collections import deque
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Generic,
    Optional,
    TypeVar,
    Union,
    cast,
    get_args,
    get_origin,
    overload,
)

import attrs
import cattrs
from cattrs.gen import AttributeOverride, make_dict_unstructure_fn, override
from typing_extensions import Unpack, dataclass_transform

from composeui.core import study
from composeui.core.model import InvalidStateError
from composeui.core.registry import RendererType, create_renderer
from composeui.core.renderer import MainRenderer, Renderer, RendererContainer
from composeui.core.signal import Signal, SignalNoArgs

if TYPE_CHECKING:
    from attrs import AttrsInstance

    from composeui.core.model import Model


LOGGER = logging.getLogger("COMPOSEUI_VIEW")
_STREAM_HANDLER = logging.StreamHandler(sys.stdout)
_STREAM_HANDLER.setFormatter(logging.Formatter("%(asctime)s: %(message)s", "%Y-%m-%d %H:%M:%S"))
LOGGER.addHandler(_STREAM_HANDLER)


CONVERTER = cattrs.Converter()

_OMITTED_TYPES = (Signal, Renderer, RendererContainer, threading.Timer)
#: Field metadata key for fields that must skip (de)serialization but aren't one of
#: `_OMITTED_TYPES` - e.g. `Validator` fields, whose type (bare/`Optional`/`list`-
#: wrapped `Callable`) isn't a single class `_is_omitted_type` can match generically.
OMIT = "omit"
#: Field metadata key for a view field of a `HorizontalView`: its share of the row's
#: width, against its siblings' (its view's `default_stretch` when unset); 0 keeps it
#: as wide as its content
STRETCH = "stretch"
#: what applying structurally wrong state can raise (from cattrs or a field's own
#: conversion, e.g. `float("abc")`)
_BAD_STATE_ERRORS = (
    ValueError,
    TypeError,
    KeyError,
    AttributeError,
    cattrs.BaseValidationError,
    cattrs.StructureHandlerNotFoundError,
)


def _is_omitted_type(tp: Any) -> bool:
    """Check whether a (possibly generic/Optional/Union) type is or wraps an omitted type."""
    origin = get_origin(tp)
    if origin is Union:
        return any(_is_omitted_type(arg) for arg in get_args(tp))
    cls = origin if origin is not None else tp
    # a dialog is what the app asks the user, not study data
    return isinstance(cls, type) and issubclass(cls, (*_OMITTED_TYPES, DialogView))


def _is_omitted_field(f: "attrs.Attribute[Any]") -> bool:
    """Check whether `f` should skip (de)serialization: by type, or by `OMIT` tag."""
    return _is_omitted_type(f.type) or bool(f.metadata.get(OMIT, False))


@CONVERTER.register_unstructure_hook_factory(attrs.has)
def _omit_renderer_and_signals(
    cls: "type[AttrsInstance]",
) -> Callable[[Any], dict[str, Any]]:
    attrs.resolve_types(cls)
    overrides: dict[str, AttributeOverride] = {
        str(f.name): override(omit=True) for f in attrs.fields(cls) if _is_omitted_field(f)
    }
    unstructure = make_dict_unstructure_fn(
        cls,
        CONVERTER,
        # every field, even one equal to its attrs default: views set their starting
        # state in `__attrs_post_init__`, so a default value left out of the file would
        # load back as that starting state instead (e.g. a validator message, or a
        # group hidden until an option shows it)
        _cattrs_omit_if_default=False,
        _cattrs_use_linecache=True,
        _cattrs_use_alias="from_converter",
        _cattrs_include_init_false=False,
        **overrides,
    )
    if not issubclass(cls, ValuesGroupMixin):
        return unstructure

    def unstructure_radio_group(obj: "ValuesGroupMixin[Any]") -> dict[str, Any]:
        data = unstructure(cast("AttrsInstance", obj))
        data["value"] = obj.serialize_value()
        return data

    return unstructure_radio_group


def _apply_state(view: "View", data: dict[str, Any]) -> None:
    """Update a live view tree in place from previously saved state.

    A fresh ``CONVERTER.structure(data, type(view))`` would build new nested
    view instances, losing their bound renderers and connected signals. Setting
    the existing attributes instead lets the normal ``notify_renderer``
    on_setattr hook refresh the UI as each value is applied.

    ``ValuesGroupMixin.value`` is handled separately: its declared type is an
    unresolved generic ``TypeVar`` that cattrs can't structure statically, so it is
    restored through `ValuesGroupMixin.deserialize_value` instead, which resolves it
    via the mixin's own `values` label lookup. ``ValuesGroupMixin.values`` is included
    in saved state (for inspection/debugging) but never restored from it on load: it's
    app-defined config, not persisted user data, and has the same unresolved-`TValue`
    structuring problem `value` has, without an equivalent label-based workaround.
    """
    states = deque([(view, data)])
    while len(states) > 0:
        current_view, new_data = states.popleft()
        current_cls = cast("type[AttrsInstance]", type(current_view))
        attrs.resolve_types(current_cls)
        if isinstance(current_view, ValuesGroupMixin) and "value" in new_data:
            current_view.value = current_view.deserialize_value(new_data["value"])
        for f in attrs.fields(current_cls):
            if (
                f.name not in new_data
                or _is_omitted_field(f)
                or f.on_setattr is attrs.setters.frozen
                or (f.name in ("value", "values") and isinstance(current_view, ValuesGroupMixin))
            ):
                continue
            new_value = new_data[f.name]
            current_field = getattr(current_view, f.name, None)
            if isinstance(current_field, View) and isinstance(new_value, dict):
                states.append((current_field, new_value))
            else:
                setattr(current_view, f.name, CONVERTER.structure(new_value, f.type))


def _reset_state(view: "View", initial: "View") -> None:
    """Set a live view tree back to `initial`'s state, in place.

    `initial` is a freshly built instance of the same class: copying from it, rather than
    from attrs defaults, also restores whatever its `__attrs_post_init__` set up (titles,
    `values`, an initial validator message...). Like `_apply_state`, it sets the existing
    attributes, so renderers and connected signals stay bound and only what actually
    changed is pushed to the UI. Fields `_apply_state` never restores are skipped the
    same way (omitted, frozen); `ValuesGroupMixin.values` is reset before `value`, which
    must be one of them.
    """
    states: deque[tuple[View, View]] = deque([(view, initial)])
    while len(states) > 0:
        current_view, initial_view = states.popleft()
        current_cls = cast("type[AttrsInstance]", type(current_view))
        attrs.resolve_types(current_cls)
        for f in attrs.fields(current_cls):
            if (
                _is_omitted_field(f)
                or f.on_setattr is attrs.setters.frozen
                or (f.name in ("value", "values") and isinstance(current_view, ValuesGroupMixin))
            ):
                continue
            current_field = getattr(current_view, f.name)
            initial_field = getattr(initial_view, f.name)
            if isinstance(current_field, View) and isinstance(initial_field, View):
                states.append((current_field, initial_field))
            else:
                setattr(current_view, f.name, initial_field)
        if isinstance(current_view, ValuesGroupMixin) and isinstance(
            initial_view, ValuesGroupMixin
        ):
            current_view.values = initial_view.values
            current_view.value = initial_view.value


def notify_renderer(instance: "View", attribute: Any, value: Any) -> Any:
    attribute_name = str(attribute.name)
    if not attribute_name.startswith("_") and hasattr(instance, attribute_name):
        old_value = getattr(instance, attribute_name)
        if (
            old_value != value
            and isinstance(instance.renderer, (Renderer, RendererContainer))
            and not instance.renderer.is_updating_state()
        ):
            instance.renderer.refresh_attribute(attribute.name, value)
    return value


T = TypeVar("T", bound=type)


@overload
def define_view(cls: T) -> T: ...
@overload
def define_view(cls: None = None, **kwargs: Any) -> Callable[[T], T]: ...
@dataclass_transform(kw_only_default=True, field_specifiers=(attrs.field,))
def define_view(cls: Union[T, None] = None, **kwargs: Any) -> Union[T, Callable[[T], T]]:
    def wrap(cls: T) -> T:
        if "on_setattr" in kwargs:
            if isinstance(kwargs["on_setattr"], Sequence):
                kwargs["on_setattr"] = [*kwargs["on_setattr"], notify_renderer]
            else:
                kwargs["on_setattr"] = [kwargs["on_setattr"], notify_renderer]
        return attrs.define(
            cls,
            on_setattr=[attrs.setters.validate, notify_renderer],
            kw_only=True,
            slots=False,
            **kwargs,
        )

    if cls is None:
        return wrap
    return wrap(cls)


@define_view
class View:
    #: key of this view's renderer in the backend's ``RENDERERS`` mapping
    #: (see `composeui.core.registry`); concrete views set it
    _renderer_key: ClassVar[Optional[str]] = None
    #: its share of a `HorizontalView`'s width when its field sets no `STRETCH`
    default_stretch: ClassVar[int] = 1

    # properties
    is_visible: bool = attrs.field(default=True)
    is_enabled: bool = attrs.field(default=True)
    # renderer
    renderer: Optional[Union[Renderer[Any, Any], RendererContainer[Any]]] = attrs.field(
        default=None
    )

    def __attrs_post_init__(self) -> None:
        for f in attrs.fields(cast("type[AttrsInstance]", type(self))):
            signal = getattr(self, f.name, None)
            if isinstance(signal, Signal):
                signal.set_name(f"{type(self).__name__}.{f.name}")

    @property
    def children_views(self) -> list["View"]:
        """Get all the field rows of the form view."""
        children_views: list[View] = []
        for field_row_attr in attrs.fields(cast("type[AttrsInstance]", type(self))):
            view = getattr(self, field_row_attr.name)
            if isinstance(view, View):
                children_views.append(view)
        return children_views

    def render(self, renderer_type: RendererType) -> None:
        self._render_children(renderer_type)
        if self.renderer is None:
            self._create_renderer(renderer_type)
        if self.renderer is not None:
            self.renderer.render()

    def _create_renderer(self, renderer_type: RendererType) -> None:
        """Create the renderer of the view."""
        if self._renderer_key is None:
            raise NotImplementedError(self._create_renderer)
        self.renderer = create_renderer(renderer_type, self._renderer_key, self)

    def _render_children(self, renderer_type: RendererType) -> None:
        for child_view in self.children_views:
            child_view.render(renderer_type)


@define_view
class StatusBar(View):
    _renderer_key = "status_bar"

    message: str = attrs.field(default="")
    message_changed: Signal[str] = attrs.Factory(Signal[str])
    timeout: float = attrs.field(default=3.0)
    _timer: Optional[threading.Timer] = attrs.field(default=None)

    def show_message(self, message: str) -> None:
        """Show a message.

        The message is dismissed after timeout seconds. A timeout of 0 means
        the message is never automatically dismissed.
        """
        self.message = message
        if self._timer is not None:
            self._timer.cancel()
        if self.timeout > 0:
            self._timer = threading.Timer(self.timeout, self._dispatch_clear_message)
            self._timer.start()

    def _dispatch_clear_message(self) -> None:
        """Run `clear_message` on the renderer's thread, not the timer's own thread.

        `threading.Timer` calls its target on a dedicated background thread; a bound
        renderer (e.g. Qt) may only be touched from its GUI thread, so the actual
        mutation has to be marshaled through `Renderer.call_on_main_thread` instead
        of calling `clear_message` here directly.
        """
        if self.renderer is not None:
            self.renderer.call_on_main_thread(self.clear_message)
        else:
            self.clear_message()

    def clear_message(self) -> None:
        self.message = ""
        self._timer = None


# class FileType(enum.Enum):
#     OpenFile = enum.auto()
#     SaveFile = enum.auto()


@define_view
class FileView(View):
    filepath: Optional[Path] = attrs.field(default=None)
    extensions: dict[str, tuple[str, ...]] = attrs.Factory(dict[str, tuple[str, ...]])
    # file_type: FileType = attrs.field(default=FileType.OpenFile)

    def _create_renderer(self, renderer_type: RendererType) -> None:
        return None


@define_view
class ActionView(View):
    _renderer_key = "action"

    text: str = attrs.field(default="")
    icon: Optional[str] = attrs.field(default=None)
    data: Any = attrs.field(default=None)
    shortcut: Optional[str] = attrs.field(default=None)
    is_checkable: bool = attrs.field(default=False)
    is_checked: bool = attrs.field(default=False)

    triggered: SignalNoArgs = attrs.Factory(SignalNoArgs)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        # first, so the callbacks connected after it see the new check state; on Qt,
        # `QAction` has already toggled itself, and this brings the view in line
        self.triggered.connect(self._toggle_checked)

    def _toggle_checked(self) -> None:
        if self.is_checkable:
            self.is_checked = not self.is_checked


class DialogKind(enum.Enum):
    #: tells the user something: one button, accepting
    MESSAGE = enum.auto()
    #: asks the user to confirm: an accepting and a rejecting button
    CONFIRM = enum.auto()


@define_view
class DialogView(View):
    """A modal message or confirmation, shown from `open` until the user answers.

    Nothing waits for the answer, since a web request can't: it comes through
    `accepted` or `rejected`, once the dialog is closed. A dialog is what the app asks,
    not study data: never saved, loaded or reset.
    """

    _renderer_key = "dialog"

    title: str = attrs.field(default="")
    text: str = attrs.field(default="")
    kind: DialogKind = attrs.field(default=DialogKind.MESSAGE)
    accept_text: str = attrs.field(default="OK")
    #: the rejecting button's text; a message has no such button
    reject_text: str = attrs.field(default="Cancel")

    accepted: SignalNoArgs = attrs.Factory(SignalNoArgs)
    rejected: SignalNoArgs = attrs.Factory(SignalNoArgs)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        # shown only once opened
        self.is_visible = False

    def open(self) -> None:
        """Show the dialog; its answer comes through `accepted` or `rejected`."""
        self.is_visible = True

    def accept(self) -> None:
        """Close the dialog with its accepting answer; ignored unless it's open."""
        if self.is_visible:
            self.is_visible = False
            self.accepted.emit()

    def reject(self) -> None:
        """Close the dialog with its rejecting answer; ignored unless it's open."""
        if self.is_visible:
            self.is_visible = False
            self.rejected.emit()

    def dismiss(self) -> None:
        """Close the dialog without a button (e.g. Escape): a confirmation is rejected.

        A message has only one answer, so dismissing it accepts it.
        """
        if self.kind is DialogKind.CONFIRM:
            self.reject()
        else:
            self.accept()


@define_view
class SeparatorAction(View):
    _renderer_key = "separator"


@define_view
class Menu(View):
    _renderer_key = "menu"

    title: str = attrs.field(default="")

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        # the menu should be visible only when triggered
        self.is_visible = False


@define_view
class NewAction(ActionView):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.shortcut = "Ctrl+n"
        self.text = "New"
        self.is_checkable = False
        self.icon = None
        self.data = None
        self.triggered.connect(self._new_study)

    def _new_study(self, *, main_view: "MainView", model: Optional["Model"] = None) -> None:
        study.new_study(main_view, model)


@define_view
class OpenFileAction(ActionView):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.text = "Open"
        self.shortcut = "Ctrl+o"
        self.is_checkable = False
        self.icon = None
        self.data = None
        self.triggered.connect(self._open_study)

    def _open_study(self) -> None: ...


@define_view
class SaveAction(ActionView):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.text = "Save"
        self.shortcut = "Ctrl+s"
        self.is_checkable = False
        self.icon = None
        self.data = None
        self.triggered.connect(self._save_study)

    def _save_study(self) -> None: ...


@define_view
class SaveAsAction(ActionView):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.text = "Save As"
        self.shortcut = "Ctrl+Shift+s"
        self.is_checkable = False
        self.icon = None
        self.data = None
        self.triggered.connect(self._save_new_study)

    def _save_new_study(self) -> None: ...


@define_view
class ExitAppAction(ActionView):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.text = "Exit"
        self.shortcut = "Ctrl+q"
        self.is_checkable = False
        self.icon = None
        self.data = None
        self.triggered.connect(self._exit_app)

    def _exit_app(self, *, main_view: "MainView") -> None:
        main_view.close()


@define_view
class FileMenu(Menu):
    new: NewAction = attrs.Factory(NewAction)
    open_file: OpenFileAction = attrs.Factory(OpenFileAction)
    save: SaveAction = attrs.Factory(SaveAction)
    save_as: SaveAsAction = attrs.Factory(SaveAsAction)
    separator_exit: SeparatorAction = attrs.Factory(SeparatorAction)
    exit_app: ExitAppAction = attrs.Factory(ExitAppAction)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.title = "File"
        self.save.triggered.connect(self._save_state)
        self.open_file.triggered.connect(self._load_state)

    def _load_state(self, *, main_view: "MainView", model: Optional["Model"] = None) -> None:
        filepath = main_view.ask_open_filepath(
            extensions={main_view.extension: (f"{main_view.extension}",)}
        )
        if filepath is None:
            return
        try:
            study.open_study(main_view, model, filepath)
        except InvalidStateError as error:
            main_view.status_bar.show_message(f"Can't open {filepath.name!r}: {error}.")

    def _save_state(self, *, main_view: "MainView", model: Optional["Model"] = None) -> None:
        filepath = main_view.ask_save_filepath(
            extensions={main_view.extension: (f"{main_view.extension}",)}
        )
        if filepath is not None:
            study.save_study(main_view, model, filepath)


@define_view
class MainView(View):
    _renderer_key = "main"

    title: str = attrs.field(init=False, on_setattr=attrs.setters.frozen)
    extension: str = attrs.field(init=False, on_setattr=attrs.setters.frozen)
    state_filepath: Optional[Path] = None

    minimum_width: int = attrs.field(default=720)
    minimum_height: int = attrs.field(default=480)

    file_menu: FileMenu = attrs.Factory(FileMenu)
    # study_toolbar: StudyToolbar = StudyToolbar(title="study")
    # a file dialog's last answer, not study data: never saved, loaded or reset
    file_view: FileView = attrs.field(factory=FileView, metadata={OMIT: True})
    # message_view: MessageView = MessageView()
    status_bar: StatusBar = attrs.Factory(StatusBar)

    def _init_app_info(self, *, title: str, extension: str) -> None:
        """Set `title`/`extension` once, meant to be called from `__attrs_post_init__`."""
        object.__setattr__(self, "title", title)
        object.__setattr__(self, "extension", extension)

    def load_state(self, filepath: Path) -> None:
        """Load the state saved in a json file; see `load_state_data`."""
        with filepath.open("rb") as f:
            try:
                data = json.load(f)
            except ValueError as error:  # also covers bytes that aren't text
                msg = f"it isn't a valid {self.extension} file"
                raise InvalidStateError(msg) from error
        self.load_state_data(data)
        self.state_filepath = filepath

    def load_state_data(self, data: Any) -> None:
        """Load state, as `save_state` writes it once parsed from json.

        Raises `InvalidStateError`, leaving this view unchanged, when the data doesn't fit
        it (see `check_state_data`).
        """
        self.check_state_data(data)
        _apply_state(self, data)

    def check_state_data(self, data: Any) -> None:
        """Raise `InvalidStateError` if `load_state_data` can't load `data`.

        The data is applied to a newly built main view: applying sets fields one by one,
        so data failing halfway would otherwise leave this view half loaded.
        """
        if not isinstance(data, dict):
            msg = f"it isn't a valid {self.extension} file"
            raise InvalidStateError(msg)
        try:
            _apply_state(type(self)(), data)
        except _BAD_STATE_ERRORS as error:
            msg = "it doesn't match this application"
            raise InvalidStateError(msg) from error

    def state_data(self) -> Any:
        """Get the state `save_state` writes, before it's turned into json."""
        return CONVERTER.unstructure(self)

    def reset_state(self) -> None:
        """Set every view back to the state of a newly built main view (a new study).

        The tree is reset in place, as `load_state` loads into it, so renderers and
        connected signals keep working.
        """
        _reset_state(self, type(self)())

    def save_state(self, filepath: Path) -> None:
        """Save the current state into a json file."""
        with filepath.open("w") as f:
            json.dump(self.state_data(), f)
        self.state_filepath = filepath

    def ask_open_filepath(self, extensions: dict[str, tuple[str, ...]]) -> Optional[Path]:
        self.file_view.extensions = extensions
        if isinstance(self.renderer, MainRenderer):
            self.file_view.filepath = self.renderer.open_file()
        return self.file_view.filepath

    def ask_save_filepath(self, extensions: dict[str, tuple[str, ...]]) -> Optional[Path]:
        self.file_view.extensions = extensions
        if isinstance(self.renderer, MainRenderer):
            self.file_view.filepath = self.renderer.save_file()
        return self.file_view.filepath

    def close(self) -> None:
        if isinstance(self.renderer, MainRenderer):
            self.renderer.close()


@define_view
class _InputView:
    # properties
    placeholder: str = attrs.field(default="")
    # signals
    editing_finished: SignalNoArgs = attrs.field(factory=SignalNoArgs)
    text_changed: Signal[str] = attrs.field(factory=Signal[str])
    text_edited: Signal[str] = attrs.field(factory=Signal[str])


@define_view
class InputMixin(_InputView):
    # properties
    text: str = attrs.field(default="")


@define_view
class InputView(InputMixin, View):
    _renderer_key = "input"


@define_view
class FloatInputMixin(_InputView):
    # properties
    value: Optional[float] = attrs.field(default=None)
    minimum: Optional[float] = attrs.field(default=None)
    maximum: Optional[float] = attrs.field(default=None)
    decimals: Optional[int] = attrs.field(default=None)


@define_view
class FloatInputView(FloatInputMixin, View):
    _renderer_key = "float_input"


class LogType(enum.Enum):
    ERROR = enum.auto()
    WARNING = enum.auto()
    INFO = enum.auto()


#: A zero-argument check: reads whatever state it needs itself (e.g. `self.text`
#: via a bound method) and returns an error message, or None if it passes.
Validator = Callable[[], Optional[str]]


@define_view
class LogMixin:
    log_message: str = attrs.field(default="")
    log_type: LogType = attrs.field(default=LogType.ERROR)
    validator: Optional[Validator] = attrs.field(default=None, repr=False, metadata={OMIT: True})

    def set_validator(
        self, validator: Validator, *signals: Signal[Unpack[tuple[Any, ...]]]
    ) -> None:
        """Wire `validator` to run against this row whenever any of `signals` fires.

        A failing (non-None) result is pushed into this row's own `log_message`/
        `log_type`; a passing (None) one clears them. Doesn't run `validator`
        immediately - call `run_validator()` afterward for an initial check (e.g. an
        empty required field should already show its error before the first edit).
        """
        self.validator = validator
        for signal in signals:
            signal.connect(self.run_validator)

    def run_validator(self, *_args: Any) -> None:
        """Re-run `validator`, if set, and push its result into the row's own log.

        Takes (and ignores) any positional args so it can be connected directly to
        signals of any arity - a per-keystroke `text_edited: Signal[str]` or a
        no-argument `editing_finished: SignalNoArgs` alike.
        """
        if self.validator is None:
            return
        message = self.validator()
        self.log_message = message or ""
        self.log_type = LogType.ERROR if message else LogType.INFO


@define_view
class LogView(LogMixin, View):
    _renderer_key = "log"


@define_view
class LabelMixin:
    text: str = attrs.field(default="")


@define_view
class LabelView(LabelMixin, View):
    _renderer_key = "label"


@define_view
class CheckBoxMixin:
    #: shown next to the box
    text: str = attrs.field(default="")
    is_checked: bool = attrs.field(default=False)
    #: the user checked or unchecked the box; not emitted when `is_checked` is set in code
    toggled: Signal[bool] = attrs.Factory(Signal[bool])


@define_view
class CheckBoxView(CheckBoxMixin, View):
    _renderer_key = "checkbox"


class ButtonVariant(enum.Enum):
    """How much a button stands out, for the user to tell actions apart."""

    #: the page's main action, e.g. submitting its form
    PRIMARY = enum.auto()
    #: an action beside the main one
    SECONDARY = enum.auto()
    #: an action destroying something, e.g. removing rows
    DANGER = enum.auto()


@define_view
class ButtonView(View):
    """A button the user clicks to act on what the page shows, e.g. to submit a form."""

    _renderer_key = "button"
    # as wide as its text in a row: a button spanning a whole row is rarely wanted
    default_stretch = 0

    text: str = attrs.field(default="")
    variant: ButtonVariant = attrs.field(default=ButtonVariant.PRIMARY)
    #: the user clicked the button
    clicked: SignalNoArgs = attrs.Factory(SignalNoArgs)


class SelectionMode(enum.Enum):
    """How many of a table's rows the user can select."""

    #: one row at most: selecting another row replaces it
    SINGLE = enum.auto()
    #: any number of rows: selecting a row adds it, and selecting it again removes it
    MULTIPLE = enum.auto()


class EditRefusedError(Exception):
    """Raised by a `cell_edited` callback to refuse the edit: the cell keeps its old text."""


def replace_cell(rows: list[list[str]], row: int, column: int, text: str) -> list[list[str]]:
    """Return `rows` with `text` in a cell, as new lists: a row short of it is filled with ""."""
    cells = [*rows[row], *[""] * (column + 1 - len(rows[row]))]
    cells[column] = text
    return [*rows[:row], cells, *rows[row + 1 :]]


@define_view
class TableMixin:
    """A table of text: the app formats each cell itself.

    Each row has one cell per header. Assign new lists to update the table: changing a
    list in place doesn't reach the renderer. The user selects rows as `selection_mode`
    allows: `selected_rows` holds their indexes, and `selection_changed` emits them when
    the user changes them. New `rows` keep each selected row selected when they hold it
    exactly once, wherever it moved, and drop it otherwise.

    The user edits the cells of the columns in `editable_columns` (none by default):
    `cell_edited` emits the row, the column and the new text while `rows` still holds the
    old one, then the edit replaces its row in `rows`, keeping the selection. To refuse or
    reformat it, or to show what the edit changed elsewhere, assign `rows` from the
    callback instead: the table shows them, and the edit isn't applied on top. The edited
    row stays selected when they hold it as edited (e.g. renamed, then sorted), or else
    as it was (the edit refused). Raising `EditRefusedError` refuses it too, the rows staying
    as they are, e.g. when the model refused the new text and changed nothing.
    """

    def _check_selected_rows(self, _attribute: "attrs.Attribute[Any]", rows: list[int]) -> None:
        name = type(self).__name__
        if any(not 0 <= row < len(self.rows) for row in rows):
            msg = f"Cannot set {name}.selected_rows to {rows}: the table has {len(self.rows)} rows."
            raise ValueError(msg)
        if len(set(rows)) != len(rows):
            msg = f"Cannot set {name}.selected_rows to {rows}: a row is selected twice."
            raise ValueError(msg)
        if self.selection_mode is SelectionMode.SINGLE and len(rows) > 1:
            msg = f"Cannot set {name}.selected_rows to {rows}: the table selects a single row."
            raise ValueError(msg)

    def _reconcile_mode(
        self, attribute: "attrs.Attribute[Any]", mode: SelectionMode
    ) -> SelectionMode:
        """Keep only the first selected row when the table comes to select a single one."""
        if mode is SelectionMode.SINGLE and len(self.selected_rows) > 1:
            self.selected_rows = self.selected_rows[:1]
        return cast("SelectionMode", notify_renderer(cast("View", self), attribute, mode))

    def _reconcile_rows(
        self, attribute: "attrs.Attribute[Any]", rows: list[list[str]]
    ) -> list[list[str]]:
        """Move `selected_rows` to their rows in `rows` (or drop them), and notify the renderer."""
        renderer = cast("View", self).renderer
        if isinstance(renderer, (Renderer, RendererContainer)) and renderer.is_updating_state():
            # the user edited a cell: every row stays where it was, and so does the selection
            return rows
        edited = self._edited_rows if self._edited_rows is not None else self.rows
        # each selected row as edited, then as it was
        selected = [(edited[row], self.rows[row]) for row in self.selected_rows]
        # cleared first: refreshing the rows clears a widget's selection, even at the same index
        self.selected_rows = []
        rows = notify_renderer(cast("View", self), attribute, rows)
        found: set[int] = set()
        for candidates in selected:
            held = [rows.index(cells) for cells in candidates if rows.count(cells) == 1]
            found.update(held[:1])
        kept = sorted(found)
        if len(kept) > 0:
            fields = attrs.fields_dict(cast("type[AttrsInstance]", type(self)))
            notify_renderer(cast("View", self), fields["selected_rows"], kept)
            # unvalidated: the validator would check `kept` against the rows being replaced
            object.__setattr__(self, "selected_rows", kept)
        return rows

    headers: list[str] = attrs.Factory(list[str])
    # before `selected_rows`, which it limits
    selection_mode: SelectionMode = attrs.field(
        default=SelectionMode.SINGLE, on_setattr=_reconcile_mode
    )
    rows: list[list[str]] = attrs.field(factory=list[list[str]], on_setattr=_reconcile_rows)
    # after `rows`: loading saved state checks it against the rows already loaded
    selected_rows: list[int] = attrs.field(factory=list[int], validator=[_check_selected_rows])
    selection_changed: Signal[list[int]] = attrs.Factory(Signal[list[int]])
    editable_columns: list[int] = attrs.Factory(list[int])
    cell_edited: Signal[int, int, str] = attrs.Factory(Signal[int, int, str])
    #: `rows` as the edit being emitted leaves them, while its callbacks run
    _edited_rows: Optional[list[list[str]]] = attrs.field(
        default=None, init=False, repr=False, metadata={OMIT: True}
    )

    def emit_cell_edited(self, row: int, column: int, text: str) -> None:
        """Emit `cell_edited` for the user's edit, `rows` still holding the old text.

        Rows its callbacks assign keep the edited row selected as `TableMixin` says.
        Renderers call it; applying the edit afterwards is theirs.
        """
        self._edited_rows = replace_cell(self.rows, row, column, text)
        try:
            self.cell_edited.emit(row, column, text)
        except EditRefusedError:
            # the rows answering the edit, as when a callback puts them back itself
            self.rows = [list(cells) for cells in self.rows]
        finally:
            self._edited_rows = None


@define_view
class TableView(TableMixin, View):
    _renderer_key = "table"


TValue = TypeVar("TValue")


@define_view
class ValuesGroupMixin(Generic[TValue]):
    def _check_value(self, _attribute: "attrs.Attribute[Any]", value: Optional[TValue]) -> None:
        """Reject a `value` that isn't `None` or one of the current `values`."""
        if value is not None and value not in self.values.values():
            if len(self.values) == 0:
                msg = (
                    f"Cannot set {type(self).__name__}.value to {value!r}: `values` is "
                    "empty. Set `values` before setting `value`."
                )
            else:
                msg = (
                    f"Cannot set {type(self).__name__}.value to {value!r}: not one of "
                    f"the available values {list(self.values)}."
                )
            raise ValueError(msg)

    def _reconcile_values(
        self, attribute: "attrs.Attribute[Any]", values: dict[str, TValue]
    ) -> dict[str, TValue]:
        """Clear `value` if it won't be a member of the new `values`, then notify the renderer."""
        if self.value is not None and self.value not in values.values():
            LOGGER.warning(
                "%s.values no longer contains %r (the current value); clearing it.",
                type(self).__name__,
                self.value,
            )
            self.value = None
        return notify_renderer(cast("View", self), attribute, values)

    value: Optional[TValue] = attrs.field(default=None, validator=[_check_value])
    values: dict[str, TValue] = attrs.field(
        factory=dict[str, TValue],
        on_setattr=_reconcile_values,
    )
    value_changed: Signal[Optional[TValue]] = attrs.Factory(Signal[Optional[TValue]])

    def serialize_value(self) -> Optional[str]:
        """Serialize `value` as its label, the key it has in `values`."""
        if self.value is None:
            return None
        for label, candidate in self.values.items():
            if candidate == self.value:
                return label
        return None

    def deserialize_value(self, label: Optional[str]) -> Optional[TValue]:
        """Look up a label previously produced by `serialize_value` back into a TValue."""
        if label is None:
            return None
        if label not in self.values:
            LOGGER.warning(
                "Cannot restore %s.value from saved state: label %r is not among "
                "the current options %r.",
                type(self).__name__,
                label,
                list(self.values),
            )
            return None
        return self.values[label]


@define_view
class RadioGroupView(ValuesGroupMixin[TValue], View):
    _renderer_key = "radio_group"


@define_view
class ComboboxView(ValuesGroupMixin[TValue], View):
    _renderer_key = "combobox"


@define_view
class FormRowView(LogMixin, View):
    #: registry key of the row's field renderer; concrete rows set it
    _field_renderer_key: ClassVar[Optional[str]] = None

    #: set by `FormView.validate` while a cross-field check naming this row fails
    has_form_error: bool = attrs.field(default=False)

    @property
    def is_invalid(self) -> bool:
        """Whether the row's field shows as invalid: its own check or its form's fails."""
        return self.is_invalid_once("has_form_error", self.has_form_error)

    def is_invalid_once(self, name: str, value: Any) -> bool:
        """Get `is_invalid` once the attribute `name` is set to `value`.

        For renderers: they are notified of a change before it lands in the view (see
        `notify_renderer`), so `is_invalid` itself still answers for the old value.
        """
        state = {
            "has_form_error": self.has_form_error,
            "log_type": self.log_type,
            "log_message": self.log_message,
            name: value,
        }
        own_error = state["log_type"] is LogType.ERROR and state["log_message"] != ""
        return bool(state["has_form_error"]) or own_error

    def _create_renderer(self, renderer_type: RendererType) -> None:
        renderers = self._create_row_renderers(renderer_type)
        if renderers is not None:
            self.renderer = RendererContainer(self, renderers)

    def _create_row_renderers(
        self, renderer_type: RendererType
    ) -> Optional[dict[str, Renderer[Any, Any]]]:
        """Create the row's renderers, or None if the backend doesn't support the field."""
        if self._field_renderer_key is None:
            raise NotImplementedError(self._create_renderer)
        field_renderer = create_renderer(renderer_type, self._field_renderer_key, self)
        log_renderer = create_renderer(renderer_type, "log", self)
        if field_renderer is None or log_renderer is None:
            return None
        return {"field": field_renderer, "log": log_renderer}


@define_view
class FormLabelRowView(FormRowView):
    label: str = attrs.field(default="")

    def _create_row_renderers(
        self, renderer_type: RendererType
    ) -> Optional[dict[str, Renderer[Any, Any]]]:
        renderers = super()._create_row_renderers(renderer_type)
        label_renderer = create_renderer(renderer_type, "form_label", self)
        if renderers is None or label_renderer is None:
            return None
        return {"label": label_renderer, **renderers}


@define_view
class RowInputView(FormRowView, InputMixin):
    _field_renderer_key = "input"


@define_view
class LabelRowInputView(FormLabelRowView, InputMixin):
    _field_renderer_key = "input"


@define_view
class RowFloatInputView(FormRowView, FloatInputMixin):
    _field_renderer_key = "float_input"


@define_view
class LabelRowFloatInputView(FormLabelRowView, FloatInputMixin):
    _field_renderer_key = "float_input"


@define_view
class RowCheckBoxView(FormRowView, CheckBoxMixin):
    _field_renderer_key = "checkbox"


@define_view
class LabelRowCheckBoxView(FormLabelRowView, CheckBoxMixin):
    _field_renderer_key = "checkbox"


@define_view
class RowRadioGroupView(FormRowView, ValuesGroupMixin[TValue]):
    _field_renderer_key = "radio_group"


@define_view
class LabelRowRadioGroupView(FormLabelRowView, ValuesGroupMixin[TValue]):
    _field_renderer_key = "radio_group"


@define_view
class RowComboboxView(FormRowView, ValuesGroupMixin[TValue]):
    _field_renderer_key = "combobox"


@define_view
class LabelRowComboboxView(FormLabelRowView, ValuesGroupMixin[TValue]):
    _field_renderer_key = "combobox"


@define_view
class FormView(View):
    _renderer_key = "form"

    log_view: LogView = attrs.field(factory=LogView)
    #: each cross-field check with the rows it is about
    _validators: list[tuple[Validator, tuple[FormRowView, ...]]] = attrs.field(
        factory=list, init=False, repr=False, metadata={OMIT: True}
    )

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.log_view.is_visible = False

    @property
    def field_rows(self) -> list[Union[FormRowView, "FormView"]]:
        """Get all the field rows of the form view."""
        return [
            getattr(self, field_row_attr.name)
            for field_row_attr in attrs.fields(cast("type[AttrsInstance]", type(self)))
            if isinstance(getattr(self, field_row_attr.name), (FormRowView, FormView))
        ]

    def add_validator(
        self,
        validator: Validator,
        *signals: Signal[Unpack[tuple[Any, ...]]],
        rows: Sequence[FormRowView] = (),
    ) -> None:
        """Register a cross-field `validator`, re-run whenever any of `signals` fires.

        Unlike `LogMixin.set_validator` (one validator per row, using that row's own
        log), a form can have several independent cross-field checks - each failing
        (non-None) result is combined into this form's shared `log_view` instead of
        the last one winning (see `PipeFormView` in `examples/pipeform.py`, which has
        two independent checks spanning `main_pipe`/`incident_pipe`). Doesn't run
        immediately - call `validate()` afterward for an initial check.

        `rows` are the rows the check is about: while it fails, each shows its field as
        invalid (`FormRowView.has_form_error`), so the user sees which values to fix
        even though the message is in the form's log. A row is flagged by the form that
        last validated it, so name a row in one form's checks only.
        """
        self._validators.append((validator, tuple(rows)))
        for signal in signals:
            signal.connect(self.validate)

    def validate(self, *_args: Any) -> None:
        """Re-run every registered validator and push the combined result to `log_view`.

        Takes (and ignores) any positional args so it can be connected directly to
        signals of any arity, same as `LogMixin.run_validator`.
        """
        messages: list[str] = []
        failing: list[FormRowView] = []
        for validator, rows in self._validators:
            message = validator()
            if message:
                messages.append(message)
                failing.extend(rows)
        for _, rows in self._validators:
            for row in rows:
                row.has_form_error = any(row is failing_row for failing_row in failing)
        if len(messages) > 0:
            self.log_view.log_message = "- " + "\n- ".join(messages)
            self.log_view.log_type = LogType.ERROR
            self.log_view.is_visible = True
        else:
            self.log_view.is_visible = False
            self.log_view.log_message = ""
            self.log_view.log_type = LogType.INFO


@define_view
class GroupFormView(FormView):
    _renderer_key = "group_form"

    title: str = attrs.field(default="")


class Align(enum.Enum):
    """Where a row packs its views when they leave some of its width free."""

    START = enum.auto()
    END = enum.auto()


@define_view
class HorizontalView(View):
    """Its view fields laid out side by side, in a row.

    Each field takes a share of the row's width, set by its `STRETCH` metadata:
    ``rooms: TableView = attrs.field(factory=TableView, metadata={STRETCH: 3})``, or its
    `default_stretch` when unset (1). A view with a share of 0 keeps its content's width,
    as a button does by default; when they all do, `align` packs them at the row's start
    or end: a subclass sets ``align = Align.END``.
    """

    _renderer_key = "horizontal"

    #: where the views go when none of them takes a share of the row's free width
    align: ClassVar[Align] = Align.START

    @property
    def stretched_views(self) -> list[tuple[View, int]]:
        """Get the views in the row, in order, each with its share of the row's width."""
        return [
            (view, f.metadata.get(STRETCH, view.default_stretch))
            for f in attrs.fields(cast("type[AttrsInstance]", type(self)))
            if isinstance(view := getattr(self, f.name), View)
        ]


@define_view
class VerticalView(View):
    """Its view fields laid out one above the other, in a column, as tall as their content.

    A page is already a column: this one is for a column inside a `HorizontalView`, e.g.
    a table above its buttons, next to another table.
    """

    _renderer_key = "vertical"


#: what a page's route can be: it also names the page in a web address (`/<route>`)
_ROUTE_PATTERN = re.compile(r"[A-Za-z0-9_-]+")


class PageWidth(enum.Enum):
    """How wide a page may grow, where the window doesn't set it (the web backend)."""

    #: a column of fields, easy to read
    NARROW = enum.auto()
    #: room for side by side views, e.g. tables
    WIDE = enum.auto()
    #: the whole window
    FULL = enum.auto()


@define_view
class PageView(View):
    """A page of the app, shown while its `Router` is on the page's `route`.

    Its view fields are its content, laid out in a column. `action` is its entry in the
    router's toolbar, showing the page's `title` and `icon`; it isn't content, and is
    navigation, not study data: never saved, loaded or reset.
    """

    _renderer_key = "page"
    #: how wide the page may grow; a subclass sets it: ``width = PageWidth.WIDE``
    width: ClassVar[PageWidth] = PageWidth.NARROW

    #: names the page in its router; set once, from `__attrs_post_init__`, with
    #: `_init_route`
    route: str = attrs.field(default="", on_setattr=attrs.setters.frozen)
    action: ActionView = attrs.field(factory=ActionView, metadata={OMIT: True})

    def _init_route(self, route: str) -> None:
        """Set `route` once, meant to be called from `__attrs_post_init__`."""
        object.__setattr__(self, "route", route)

    @property
    def title(self) -> str:
        """The page's name in the toolbar."""
        return self.action.text

    @title.setter
    def title(self, title: str) -> None:
        self.action.text = title

    @property
    def icon(self) -> Optional[str]:
        """The page's icon in the toolbar, if the backend shows icons."""
        return self.action.icon

    @icon.setter
    def icon(self, icon: Optional[str]) -> None:
        self.action.icon = icon

    @property
    def content_views(self) -> list[View]:
        """Get the views shown on the page, in order."""
        return [view for view in self.children_views if view is not self.action]


@define_view
class Router(View):
    """Pages shown one at a time, picked from a toolbar with an entry per page.

    Its page fields are the pages, in toolbar order. It starts on the first page;
    triggering a page's `action` navigates to the page, and only the shown page's action
    is checked. Pages can't be added or removed once built.
    """

    _renderer_key = "router"

    #: the shown page's route; change it with `navigate`. Navigation, not study data:
    #: never saved, loaded or reset
    current_route: str = attrs.field(default="", metadata={OMIT: True})
    #: a different page is shown, by its route
    route_changed: Signal[str] = attrs.Factory(Signal[str])

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        routes: set[str] = set()
        for page in self.pages:
            if _ROUTE_PATTERN.fullmatch(page.route) is None:
                msg = (
                    f"{type(page).__name__}.route is {page.route!r}: a route is made of "
                    "letters, digits, '_' and '-' only. Set it with `_init_route`."
                )
                raise ValueError(msg)
            if page.route in routes:
                msg = f"Two pages of {type(self).__name__} have the route {page.route!r}."
                raise ValueError(msg)
            routes.add(page.route)
            page.action.is_checkable = True
            page.action.triggered.connect(functools.partial(self.navigate, page.route))
        if len(self.pages) > 0:
            self._show(self.pages[0].route)

    @property
    def pages(self) -> list[PageView]:
        """Get the pages, in toolbar order."""
        return [view for view in self.children_views if isinstance(view, PageView)]

    @property
    def current_page(self) -> Optional[PageView]:
        """Get the shown page, or None without pages."""
        return self.page(self.current_route)

    def page(self, route: str) -> Optional[PageView]:
        """Get the page on `route`, or None if no page has it."""
        return next((page for page in self.pages if page.route == route), None)

    def navigate(self, route: str) -> None:
        """Show the page on `route`; raise `ValueError` if no page has it."""
        if self.page(route) is None:
            routes = [page.route for page in self.pages]
            msg = f"{type(self).__name__} has no page on {route!r}, only on {routes}."
            raise ValueError(msg)
        is_changed = route != self.current_route
        self._show(route)
        if is_changed:
            self.route_changed.emit(route)

    def _show(self, route: str) -> None:
        # set even when it's already the route: triggering a checked action unchecks it
        for page in self.pages:
            page.action.is_checked = page.route == route
        self.current_route = route

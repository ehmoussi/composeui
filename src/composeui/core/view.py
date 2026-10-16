# from __future__ import annotations

import contextlib
import contextvars
import copy
import enum
import functools
import json
import logging
import math
import re
import sys
import threading
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Generic,
    NamedTuple,
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
from typing_extensions import ParamSpec, Unpack, dataclass_transform

from composeui.core import study
from composeui.core.jobs import Jobs
from composeui.core.model import InvalidStateError, RefusedError
from composeui.core.registry import RendererType, create_renderer
from composeui.core.renderer import MainRenderer, Renderer, RendererContainer
from composeui.core.signal import Signal, SignalNoArgs
from composeui.core.translation import (
    CATALOGS_DIR,
    LANGUAGE_NAMES,
    T,
    Translate,
    TranslatedText,
    language_name,
    no_translation,
    translate_again,
    translator,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

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
#: Field metadata key for a view field of a `GridView`: its cell, a `GridPosition` (or a
#: tuple of its values)
GRID_POSITION = "grid_position"
#: Field metadata key for text the user reads rather than enters (labels, titles...): it
#: belongs to the app's code and language, not to a study, so it's never saved or loaded
UI_TEXT = "ui_text"
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
    # a dialog is what the app asks the user, and the language how it shows: not study data
    return isinstance(cls, type) and issubclass(cls, (*_OMITTED_TYPES, DialogView, LanguageMenu))


def _is_omitted_field(f: "attrs.Attribute[Any]") -> bool:
    """Check whether `f` should skip (de)serialization: by type, or by `OMIT` tag."""
    return _is_omitted_type(f.type) or bool(f.metadata.get(OMIT, False))


def _is_state_field(f: "attrs.Attribute[Any]") -> bool:
    """Check whether `f` is study data, which state files save and load."""
    return not _is_omitted_field(f) and not f.metadata.get(UI_TEXT, False)


@CONVERTER.register_unstructure_hook_factory(attrs.has)
def _omit_renderer_and_signals(
    cls: "type[AttrsInstance]",
) -> Callable[[Any], dict[str, Any]]:
    # a generic view's class, e.g. a field's `RecordTableView[Room]`
    view_cls = get_origin(cls) or cls
    attrs.resolve_types(view_cls)
    overrides: dict[str, AttributeOverride] = {
        str(f.name): override(omit=True) for f in attrs.fields(view_cls) if not _is_state_field(f)
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
    if issubclass(view_cls, RecordTableView):

        def unstructure_record_table(obj: "RecordTableView[Any]") -> dict[str, Any]:
            data = unstructure(cast("AttrsInstance", obj))
            # the records by their own type, which the field's `RecordT` doesn't name;
            # the rows only show them, and the columns, the app's, set what's editable
            data["records"] = CONVERTER.unstructure(obj.records)
            del data["rows"], data["editable_columns"]
            return data

        return unstructure_record_table
    if not issubclass(view_cls, ValuesGroupMixin):
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
    ``RecordTableView.records`` is restored first, by `RecordTableView.record_type`: its
    rows, before the selection checked against them.
    """
    states = deque([(view, data)])
    while len(states) > 0:
        current_view, new_data = states.popleft()
        current_cls = cast("type[AttrsInstance]", type(current_view))
        attrs.resolve_types(current_cls)
        if isinstance(current_view, ValuesGroupMixin) and "value" in new_data:
            current_view.value = current_view.deserialize_value(new_data["value"])
        if isinstance(current_view, RecordTableView) and "records" in new_data:
            current_view.records = current_view.structure_records(new_data["records"])
        for f in attrs.fields(current_cls):
            if (
                f.name not in new_data
                or not _is_state_field(f)
                or f.on_setattr is attrs.setters.frozen
                or (f.name in ("value", "values") and isinstance(current_view, ValuesGroupMixin))
                or (
                    f.name in ("rows", "records", "editable_columns")
                    and isinstance(current_view, RecordTableView)
                )
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
    must be one of them, and `RecordTableView.records` before the selection.
    """
    states: deque[tuple[View, View]] = deque([(view, initial)])
    while len(states) > 0:
        current_view, initial_view = states.popleft()
        current_cls = cast("type[AttrsInstance]", type(current_view))
        attrs.resolve_types(current_cls)
        if isinstance(current_view, RecordTableView) and isinstance(initial_view, RecordTableView):
            current_view.records = initial_view.records
        for f in attrs.fields(current_cls):
            if (
                _is_omitted_field(f)
                or f.on_setattr is attrs.setters.frozen
                or (f.name in ("value", "values") and isinstance(current_view, ValuesGroupMixin))
                or (f.name in ("rows", "records") and isinstance(current_view, RecordTableView))
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


def _retranslate(view: "View", translate: Translate) -> None:
    """Show the text of `view` and its children translated with `translate`.

    The text `tr` translated, wherever a field keeps it; text set without `tr` is left as
    it is.
    """
    for child in view.children_views:
        _retranslate(child, translate)
    view._tr = translate  # noqa: SLF001
    for f in attrs.fields(cast("type[AttrsInstance]", type(view))):
        value = getattr(view, f.name)
        translated = translate_again(value, translate)
        if translated is value:
            continue
        if f.on_setattr is attrs.setters.frozen:
            # set once by the app, e.g. the main view's title: only a language changes it
            notify_renderer(view, f, translated)
            object.__setattr__(view, f.name, translated)
        else:
            setattr(view, f.name, translated)
    view.retranslate()
    # a message on show is in the previous language
    if isinstance(view, LogMixin) and view.log_message != "":
        view.run_validator()
    if isinstance(view, FormView) and view.log_view.log_message != "":
        view.validate()


_ClassT = TypeVar("_ClassT", bound=type)


@overload
def define_view(cls: _ClassT) -> _ClassT: ...
@overload
def define_view(cls: None = None, **kwargs: Any) -> Callable[[_ClassT], _ClassT]: ...
@dataclass_transform(kw_only_default=True, field_specifiers=(attrs.field,))
def define_view(
    cls: Union[_ClassT, None] = None, **kwargs: Any
) -> Union[_ClassT, Callable[[_ClassT], _ClassT]]:
    def wrap(cls: _ClassT) -> _ClassT:
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


_P = ParamSpec("_P")
_ViewT = TypeVar("_ViewT", bound="View")


def child(cls: Callable[_P, _ViewT], /, *args: _P.args, **kwargs: _P.kwargs) -> _ViewT:
    """Get a view field's default: a `cls` view built with these arguments, one per view.

    E.g. ``add: ButtonView = child(ButtonView, text=T("Add"))``. The arguments are copied
    for each view built, so a list among them is never shared.
    """

    def build() -> _ViewT:
        return cls(*copy.deepcopy(args), **copy.deepcopy(kwargs))

    return cast("_ViewT", attrs.Factory(build))


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
    #: translates the view's text into its main view's language (see `MainView.set_language`)
    _tr: Translate = attrs.field(
        default=no_translation, init=False, repr=False, eq=False, metadata={OMIT: True}
    )
    #: the main view holding this view, set by the application; weak, as a view's parent
    _main_view: Optional[Callable[[], Optional["MainView"]]] = attrs.field(
        default=None, init=False, repr=False, eq=False, metadata={OMIT: True}
    )

    def __attrs_post_init__(self) -> None:
        for f in attrs.fields(cast("type[AttrsInstance]", type(self))):
            signal = getattr(self, f.name, None)
            if isinstance(signal, Signal):
                signal.set_name(f"{type(self).__name__}.{f.name}")
        self.retranslate()

    def tr(self, text: str) -> TranslatedText:
        """Translate `text`, as written in the code, into the main view's language.

        A view keeping the translation, in a field or in a list or dict of one, shows it in
        the next language `MainView.set_language` sets; formatted too.
        """
        return TranslatedText(self._tr(text), text)

    @contextlib.contextmanager
    def refusing(self, message: str) -> "Iterator[None]":
        """Show the model's refusal of the block's change in the main view's status bar.

        `message` shows the `RefusedError`'s message, translated (unless `tr` gave it), as
        ``{error}``, e.g. ``self.tr("Can't add a room: {error}")``. In a `cell_edited`
        callback, the edit is refused too: the cell keeps its old text.
        """
        try:
            yield
        except RefusedError as error:
            main_view = None if self._main_view is None else self._main_view()
            if main_view is None:  # not shown by an application: nowhere to show it
                raise
            reason = error.args[0] if error.args else ""
            if not isinstance(reason, TranslatedText):
                reason = self.tr(str(reason))
            main_view.status_bar.show_message(message.format(error=reason))
            if _editing_cell.get():
                raise EditRefusedError from error

    def retranslate(self) -> None:
        """Update text that `tr` alone doesn't follow, e.g. built from other text.

        Called once while the view is built, before the rest of `__attrs_post_init__`,
        then by `MainView.set_language` on every view, children before their parent, once
        their text is translated.
        """

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

    text: str = attrs.field(default="", metadata={UI_TEXT: True})
    #: an image file's path; set by the app, not study data: never saved, loaded or
    #: reset (the web backend serves the file, so a study must not name one)
    icon: Optional[str] = attrs.field(default=None, metadata={OMIT: True})
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

    title: str = attrs.field(default="", metadata={UI_TEXT: True})
    text: str = attrs.field(default="", metadata={UI_TEXT: True})
    kind: DialogKind = attrs.field(default=DialogKind.MESSAGE)
    accept_text: str = attrs.field(default=T("OK"), metadata={UI_TEXT: True})
    #: the rejecting button's text; a message has no such button
    reject_text: str = attrs.field(default=T("Cancel"), metadata={UI_TEXT: True})

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

    title: str = attrs.field(default="", metadata={UI_TEXT: True})

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        # the menu should be visible only when triggered
        self.is_visible = False


@define_view
class ToolBar(View):
    """A row of actions at the top of the window, for the ones the user runs most.

    Its `ActionView` and `SeparatorAction` fields are its entries, in order; a field of
    the main view, docked by the window. `title` names it, e.g. for a screen reader.
    """

    _renderer_key = "toolbar"

    title: str = attrs.field(default="", metadata={UI_TEXT: True})


@define_view
class NewAction(ActionView):
    text: str = attrs.field(default=T("New"), metadata={UI_TEXT: True})

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.shortcut = "Ctrl+n"
        self.is_checkable = False
        self.icon = None
        self.data = None
        self.triggered.connect(self._new_study)

    def _new_study(self, *, main_view: "MainView", model: Optional["Model"] = None) -> None:
        study.new_study(main_view, model)


@define_view
class OpenFileAction(ActionView):
    text: str = attrs.field(default=T("Open"), metadata={UI_TEXT: True})

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.shortcut = "Ctrl+o"
        self.is_checkable = False
        self.icon = None
        self.data = None
        self.triggered.connect(self._open_study)

    def _open_study(self) -> None: ...


@define_view
class SaveAction(ActionView):
    text: str = attrs.field(default=T("Save"), metadata={UI_TEXT: True})

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.shortcut = "Ctrl+s"
        self.is_checkable = False
        self.icon = None
        self.data = None
        self.triggered.connect(self._save_study)

    def _save_study(self) -> None: ...


@define_view
class SaveAsAction(ActionView):
    text: str = attrs.field(default=T("Save As"), metadata={UI_TEXT: True})

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.shortcut = "Ctrl+Shift+s"
        self.is_checkable = False
        self.icon = None
        self.data = None
        self.triggered.connect(self._save_new_study)

    def _save_new_study(self) -> None: ...


@define_view
class ExitAppAction(ActionView):
    text: str = attrs.field(default=T("Exit"), metadata={UI_TEXT: True})

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
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

    title: str = attrs.field(default=T("File"), metadata={UI_TEXT: True})

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
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
            message = main_view.tr("Can't open {name}: {error}.")
            main_view.status_bar.show_message(message.format(name=repr(filepath.name), error=error))

    def _save_state(self, *, main_view: "MainView", model: Optional["Model"] = None) -> None:
        filepath = main_view.ask_save_filepath(
            extensions={main_view.extension: (f"{main_view.extension}",)}
        )
        if filepath is not None:
            study.save_study(main_view, model, filepath)


@define_view
class LanguageMenu(Menu):
    """A menu of the app's languages, the one shown checked; triggering one shows it.

    Make it a field of the main view, which gives it the languages it has catalogs for
    (`MainView.languages`), each named in itself whatever the language shown, and keeps
    the shown one checked. The language isn't study data: never saved, loaded or reset.
    """

    title: str = attrs.field(default=T("Language"), metadata={UI_TEXT: True})
    #: each language's action, its code as `data`; set with `set_languages`
    actions: list[ActionView] = attrs.field(factory=list[ActionView], metadata={OMIT: True})
    #: the languages' names, by code; a subclass extends it for a language it lacks:
    #: ``names = {**LanguageMenu.names, "eo": "Esperanto"}``
    names: ClassVar[Mapping[str, str]] = LANGUAGE_NAMES

    @property
    def children_views(self) -> list[View]:
        return [*super().children_views, *self.actions]

    def set_languages(self, languages: Sequence[str]) -> None:
        """Offer `languages`, by code, before the menu is rendered.

        A language whose first letter no other one shares gets a Ctrl+Shift shortcut.
        """
        initials = [language[:1].lower() for language in languages]
        self.actions = [
            ActionView(
                text=language_name(language, self.names),
                data=language,
                is_checkable=True,
                shortcut=f"Ctrl+Shift+{initial}" if initials.count(initial) == 1 else None,
            )
            for language, initial in zip(languages, initials)
        ]

    def action(self, language: str) -> ActionView:
        """Get the action of `language`, e.g. "fr"."""
        for action in self.actions:
            if action.data == language:
                return action
        msg = f"{type(self).__name__} doesn't offer {language!r}."
        raise KeyError(msg)

    def check(self, language: str) -> None:
        """Check `language`'s action, else its base language's: "fr-CA" checks French."""
        offered = [action.data for action in self.actions]
        base = language.replace("_", "-").split("-")[0]
        checked = language if language in offered else base
        for action in self.actions:
            action.is_checked = action.data == checked


@define_view
class MainView(View):
    _renderer_key = "main"

    #: the app's name, in the window's title; a subclass sets it: ``app_title = T("Pipes")``
    app_title: ClassVar[str] = ""
    #: the extension of the app's study files; a subclass sets it: ``extension = ".pipe"``
    extension: ClassVar[str] = ""
    #: `app_title`, in the main view's language
    title: str = attrs.field(
        default=attrs.Factory(lambda self: self.app_title, takes_self=True),
        init=False,
        on_setattr=attrs.setters.frozen,
    )
    state_filepath: Optional[Path] = None

    minimum_width: int = attrs.field(default=720)
    minimum_height: int = attrs.field(default=480)

    file_menu: FileMenu = attrs.Factory(FileMenu)
    # study_toolbar: StudyToolbar = StudyToolbar(title="study")
    # a file dialog's last answer, not study data: never saved, loaded or reset
    file_view: FileView = attrs.field(factory=FileView, metadata={OMIT: True})
    # message_view: MessageView = MessageView()
    status_bar: StatusBar = attrs.Factory(StatusBar)
    #: functions run in threads, their results given back on the main thread
    jobs: Jobs = attrs.field(
        default=attrs.Factory(Jobs, takes_self=True),
        init=False,
        repr=False,
        eq=False,
        metadata={OMIT: True},
    )

    #: the directory of the app's catalogs, `<language>.json` files (see
    #: `composeui.core.translation`); a subclass sets it, e.g. to
    #: ``Path(__file__).parent / "locales"``
    translations_dir: ClassVar[Optional[Path]] = None
    #: the language the app's text is written in, shown until `set_language`
    source_language: ClassVar[str] = "en"
    #: set by `set_language`; empty while the text shows as written in the code
    _language: str = attrs.field(default="", init=False, repr=False, metadata={OMIT: True})

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        for menu in self._language_menus():
            menu.set_languages(self.languages)
            for action in menu.actions:
                action.triggered.connect(functools.partial(self.set_language, action.data))
            menu.check(self.language)

    @property
    def language(self) -> str:
        """Get the language the text shows in: set with `set_language`, or the source's."""
        return self._language or self.source_language

    @property
    def languages(self) -> list[str]:
        """Get the languages the app shows: `source_language`, then the catalogs'."""
        found = (
            []
            if self.translations_dir is None
            else sorted(path.stem for path in self.translations_dir.glob("*.json"))
        )
        return list(dict.fromkeys([self.source_language, *found]))

    def set_language(self, language: str) -> None:
        """Show the text of every view in `language`, e.g. "fr" or "fr-CA".

        From the app's catalogs (`translations_dir`), then ComposeUI's; text neither
        translates shows as written in the code.
        """
        directories = [d for d in (self.translations_dir, CATALOGS_DIR) if d is not None]
        # first: `retranslate` can show it
        self._language = language
        _retranslate(self, translator(language, directories))
        for menu in self._language_menus():
            menu.check(language)

    def _language_menus(self) -> list[LanguageMenu]:
        return [view for view in self.children_views if isinstance(view, LanguageMenu)]

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
        self.jobs.drop()  # working for the study replaced
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
        self.jobs.drop()  # working for the study replaced
        _reset_state(self, type(self)())
        # the new view's text is as written in the code
        _retranslate(self, self._tr)

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
        self.jobs.drop()
        if isinstance(self.renderer, MainRenderer):
            self.renderer.close()


@define_view
class _InputView:
    # properties
    placeholder: str = attrs.field(default="", metadata={UI_TEXT: True})
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
    text: str = attrs.field(default="", metadata={UI_TEXT: True})


@define_view
class LabelView(LabelMixin, View):
    _renderer_key = "label"


@define_view
class CheckBoxMixin:
    #: shown next to the box
    text: str = attrs.field(default="", metadata={UI_TEXT: True})
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

    text: str = attrs.field(default="", metadata={UI_TEXT: True})
    variant: ButtonVariant = attrs.field(default=ButtonVariant.PRIMARY)
    #: the user clicked the button
    clicked: SignalNoArgs = attrs.Factory(SignalNoArgs)


@define_view
class ProgressBarView(View):
    """How far a long task has gone, e.g. a computation working through its cases."""

    _renderer_key = "progress_bar"

    def _check_maximum(self, _attribute: "attrs.Attribute[Any]", maximum: Optional[int]) -> None:
        if maximum is not None and maximum <= 0:
            msg = f"Cannot set {type(self).__name__}.maximum to {maximum}: it must be positive."
            raise ValueError(msg)

    #: steps done, from 0 to `maximum`; shown clamped to that range (see `clamp`)
    value: int = attrs.field(default=0)
    #: steps the task takes; None while unknown, the bar then only showing that it runs
    maximum: Optional[int] = attrs.field(default=100, validator=[_check_maximum])

    @staticmethod
    def clamp(value: int, maximum: Optional[int]) -> int:
        """`value` within a bar's range of `maximum` steps, as it shows: a count may overshoot.

        Takes both, as a renderer refreshes one before the view holds the new value.
        """
        value = max(0, value)
        return value if maximum is None else min(value, maximum)


def _to_floats(values: "Iterable[float]") -> list[float]:
    """Get `values` as a new list of floats, e.g. from a tuple or a numpy array."""
    return [float(value) for value in values]


class ChartKind(enum.Enum):
    """How a chart draws its series' points."""

    #: joined by a line, e.g. a result against time
    LINE = enum.auto()
    #: as dots, e.g. measurements over a model's curve
    SCATTER = enum.auto()
    #: as bars, a group of one bar per series in each of the chart's `categories`; the
    #: chart's own kind only
    BAR = enum.auto()


#: the share of a category's width a bar chart's group of bars takes
BAR_GROUP_WIDTH = 0.8


_COLOR_PATTERN = re.compile(r"#[0-9a-fA-F]{6}")


@attrs.frozen
class Series:
    """A curve of a `ChartView`: its points, x against y, under `name` in the legend.

    A point whose x or y is NaN is not drawn: the curve has a gap there.
    """

    def _check_y(self, _attribute: "attrs.Attribute[Any]", y: list[float]) -> None:
        if len(y) != len(self.x):
            msg = f"Cannot make the series {self.name!r}: {len(self.x)} x for {len(y)} y."
            raise ValueError(msg)

    def _check_color(self, _attribute: "attrs.Attribute[Any]", color: Optional[str]) -> None:
        if color is not None and _COLOR_PATTERN.fullmatch(color) is None:
            msg = f"Cannot color the series {self.name!r} {color!r}: give it as #rrggbb."
            raise ValueError(msg)

    def _check_kind(self, _attribute: "attrs.Attribute[Any]", kind: Optional[ChartKind]) -> None:
        if kind is ChartKind.BAR:
            msg = f"Cannot draw the series {self.name!r} as bars: a BAR chart draws its series so."
            raise ValueError(msg)

    #: the legend's entry
    name: str
    x: list[float] = attrs.field(converter=_to_floats)
    y: list[float] = attrs.field(converter=_to_floats, validator=[_check_y])
    #: how it is drawn, as a line or dots; None: as its chart's `kind`
    kind: Optional[ChartKind] = attrs.field(default=None, validator=[_check_kind])
    #: its color, as #rrggbb, the same in every theme, e.g. a logo's or a code's; None:
    #: the backend's theme picks it
    color: Optional[str] = attrs.field(default=None, validator=[_check_color])
    #: whether the area between its line and 0 is filled with its color, e.g. a shape
    fill: bool = False


@define_view
class ChartView(View):
    """A chart of results, e.g. a quantity against time or a swept dimension.

    Data and labels: each backend draws it in its own theme's colors and fonts, unless a
    series has a color of its own (`Series.color`).
    Assign a new `series` list to redraw it, e.g. a job adding points; the user's zoom
    stays where the backend has one.

    A `BAR` chart draws a group of bars for each of its `categories`, a bar per series: a
    series' x is the index of a category, and its y the bar's height.

    A log axis (`x_log`, `y_log`) leaves out the values it can't show, those <= 0: a
    point at such an x isn't drawn, and such a y leaves a gap (see `drawn_points`), rather
    than a job's points making the chart fail. A bar chart's x, its categories, is never
    a log axis.
    """

    _renderer_key = "chart"

    #: how its series are drawn, unless one says otherwise (`Series.kind`)
    kind: ChartKind = attrs.field(default=ChartKind.LINE)
    title: str = attrs.field(default="", metadata={UI_TEXT: True})
    x_title: str = attrs.field(default="", metadata={UI_TEXT: True})
    y_title: str = attrs.field(default="", metadata={UI_TEXT: True})
    #: the x axis' unit, shown as "Time (s)", and with the values the user hovers
    x_unit: str = attrs.field(default="")
    y_unit: str = attrs.field(default="")
    series: list[Series] = attrs.field(factory=list[Series])
    #: a `BAR` chart's categories, by the index each series' x names
    categories: list[str] = attrs.field(factory=list[str])
    x_log: bool = attrs.field(default=False)
    y_log: bool = attrs.field(default=False)
    #: the action saving the chart as a report's image (see `composeui.core.chartimage`),
    #: where the backend has one: with the `report` extra installed
    save_image_text: str = attrs.field(default=T("Save Image"), metadata={UI_TEXT: True})
    #: the user clicked the chart at a point, as the axes' values (x, then y), e.g. to
    #: pick a curve's point; where the backend has a pointer: Qt and the web, not Textual
    clicked: Signal[float, float] = attrs.Factory(Signal[float, float])

    @staticmethod
    def kind_of(series: Series, kind: ChartKind) -> ChartKind:
        """Get how `series` is drawn on a chart of `kind`: a bar chart draws only bars.

        Takes the chart's kind, as a renderer refreshes it before the view holds it.
        """
        if kind is ChartKind.BAR or series.kind is None:
            return kind
        return series.kind

    @staticmethod
    def drawn_points(
        series: Series, *, x_log: bool, y_log: bool
    ) -> tuple[list[float], list[float]]:
        """Get the points of `series` its axes can show: a log axis can't show 0 or less.

        A point whose x a log x axis can't show is left out; a y a log y axis can't show
        is NaN, a gap. As they are without a log axis.
        """
        if not x_log and not y_log:
            return series.x, series.y
        xs: list[float] = []
        ys: list[float] = []
        for x, y in zip(series.x, series.y):
            if x_log and not x > 0:
                continue
            xs.append(x)
            ys.append(math.nan if y_log and not y > 0 else y)
        return xs, ys

    @staticmethod
    def bar_heights(series: Series, category_count: int, *, y_log: bool = False) -> list[float]:
        """Get the height of a series' bar in each category, NaN where it has none.

        A point whose x isn't a category's index has no bar; the last of a category wins.
        On a log y axis, a height of 0 or less is no bar either.
        """
        heights = [math.nan] * category_count
        for x, y in zip(series.x, series.y):
            if x.is_integer() and 0 <= x < category_count:
                heights[int(x)] = math.nan if y_log and not y > 0 else y
        return heights

    @staticmethod
    def bar_slot(index: int, series_count: int) -> tuple[float, float]:
        """Get the offset of a series' bar from its category's index, and its width.

        In categories: the bar's middle is at the offset, its group centered on the index.
        """
        width = BAR_GROUP_WIDTH / series_count
        return (index - (series_count - 1) / 2) * width, width

    @staticmethod
    def axis_label(title: str, unit: str) -> str:
        """Get an axis' label: its title with its unit, as "Time (s)"."""
        if unit == "":
            return title
        return f"({unit})" if title == "" else f"{title} ({unit})"


class SelectionMode(enum.Enum):
    """How many of a table's rows the user can select."""

    #: one row at most: selecting another row replaces it
    SINGLE = enum.auto()
    #: any number of rows: selecting a row adds it, and selecting it again removes it
    MULTIPLE = enum.auto()


class EditRefusedError(Exception):
    """Raised by a `cell_edited` callback to refuse the edit: the cell keeps its old text."""


#: whether a `cell_edited` callback is running, for `View.refusing` to refuse its edit
_editing_cell: contextvars.ContextVar[bool] = contextvars.ContextVar("_editing_cell", default=False)


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
    as they are, e.g. when the model refused the new text and changed nothing; so does a
    `RefusedError` caught by `View.refusing` in the callback.
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

    headers: list[str] = attrs.field(factory=list[str], metadata={UI_TEXT: True})
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
        token = _editing_cell.set(True)
        try:
            self._emit_edit(row, column, text)
        except EditRefusedError:
            # the rows answering the edit, as when a callback puts them back itself
            self.rows = [list(cells) for cells in self.rows]
        finally:
            _editing_cell.reset(token)
            self._edited_rows = None

    def _emit_edit(self, row: int, column: int, text: str) -> None:
        """Emit the edit's signals, `_edited_rows` holding the rows as it leaves them."""
        self.cell_edited.emit(row, column, text)


@define_view
class TableView(TableMixin, View):
    _renderer_key = "table"


RecordT = TypeVar("RecordT", bound="AttrsInstance")


@attrs.frozen
class Column:
    """A column of a `RecordTableView`: a field of its records, under `header`."""

    #: the name of the records' field the column shows
    field: str
    header: str
    #: whether the user edits the column's cells
    editable: bool = False


def _cell_text(value: Any) -> str:
    """Show a record's field in its cell: as saved, None as an empty cell."""
    return "" if value is None else str(CONVERTER.unstructure(value))


def _parse_bool(text: Any, _type: type) -> bool:
    if isinstance(text, str) and text.lower() in ("true", "false"):
        return text.lower() == "true"
    msg = f"{text!r} isn't a boolean"
    raise ValueError(msg)


#: parses a cell's text into a record's field; strict about booleans, which
#: `bool("False")` would make true
_CELL_CONVERTER = CONVERTER.copy()
_CELL_CONVERTER.register_structure_hook(bool, _parse_bool)


@define_view
class RecordTableView(TableView, Generic[RecordT]):
    """A table of records, `attrs` instances, each a row with a cell per column.

    Build it with its records' type, so a study can save and load them:
    ``child(RecordTableView[Room], columns=[Column("name", T("Room"), editable=True)])``.
    `columns` set the headers and the editable columns, and the table formats each field
    in its cell (`str`, None as an empty cell): assign new `records`, not `rows`.

    The user's edit is parsed into the field's type with `CONVERTER`: a cell that doesn't
    parse refuses the edit, saying why in the status bar. Else `record_edited` emits the
    old and the new record while `records` still holds the old one, then the new one
    replaces it, unless the callbacks assigned `records` themselves; refusing the edit
    works as with `cell_edited` (`View.refusing`).
    """

    def _reconcile_columns(
        self, _attribute: "attrs.Attribute[Any]", columns: list[Column]
    ) -> list[Column]:
        self.headers = [translate_again(column.header, self._tr) for column in columns]
        self.editable_columns = [index for index, column in enumerate(columns) if column.editable]
        self.rows = [self._cells(record, columns) for record in self.records]
        return columns

    def _reconcile_records(
        self, _attribute: "attrs.Attribute[Any]", records: list[RecordT]
    ) -> list[RecordT]:
        self.rows = [self._cells(record, self.columns) for record in records]
        return records

    # the table's setup, by the app: not study data
    columns: list[Column] = attrs.field(
        factory=list[Column], on_setattr=_reconcile_columns, metadata={OMIT: True}
    )
    records: list[RecordT] = attrs.field(factory=list, on_setattr=_reconcile_records)
    #: the user edited a record: the old one, then the new one
    record_edited: Signal[RecordT, RecordT] = attrs.Factory(Signal[RecordT, RecordT])

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.columns = self.columns
        self.records = self.records

    @property
    def record_type(self) -> type:
        """Get the records' type, from ``RecordTableView[Room]`` or a subclass's base."""
        bases = [getattr(self, "__orig_class__", None)]
        bases += [base for cls in type(self).__mro__ for base in getattr(cls, "__orig_bases__", ())]
        for base in bases:
            origin = get_origin(base)
            if isinstance(origin, type) and issubclass(origin, RecordTableView):
                (record_type,) = get_args(base)
                if isinstance(record_type, type):
                    return record_type
        msg = (
            f"{type(self).__name__} doesn't know its records' type: build it as "
            "RecordTableView[Room](...)."
        )
        raise TypeError(msg)

    @property
    def selected_record(self) -> Optional[RecordT]:
        """Get the first selected record, or None if no row is selected."""
        return self.records[self.selected_rows[0]] if len(self.selected_rows) > 0 else None

    @property
    def selected_records(self) -> list[RecordT]:
        """Get the selected records, as `selected_rows` lists them."""
        return [self.records[row] for row in self.selected_rows]

    def structure_records(self, data: Any) -> list[RecordT]:
        """Build records of `record_type` from their saved data."""
        return cast("list[RecordT]", CONVERTER.structure(data, cast("Any", list)[self.record_type]))

    @staticmethod
    def _cells(record: Any, columns: Sequence[Column]) -> list[str]:
        return [_cell_text(getattr(record, column.field)) for column in columns]

    def _emit_edit(self, row: int, column: int, text: str) -> None:
        old = self.records[row]
        name = self.columns[column].field
        field_type: Any = attrs.fields_dict(attrs.resolve_types(type(old)))[name].type
        try:
            if text == "" and type(None) in get_args(field_type):
                value = None
            else:
                value = _CELL_CONVERTER.structure(text, field_type)
        except _BAD_STATE_ERRORS as error:
            main_view = None if self._main_view is None else self._main_view()
            if main_view is not None:
                message = self.tr('{header}: "{text}" isn\'t a valid value')
                main_view.status_bar.show_message(
                    message.format(header=self.headers[column], text=text)
                )
            raise EditRefusedError from error
        # `old` as `Any`: mypy's attrs plugin doesn't take a bound type variable
        new: RecordT = attrs.evolve(cast("Any", old), **{name: value})
        if self._edited_rows is not None:
            # as the table will show it, to keep it selected once the records come back
            self._edited_rows[row] = self._cells(new, self.columns)
        records, rows = self.records, self.rows
        super()._emit_edit(row, column, text)
        self.record_edited.emit(old, new)
        if self.records is records and self.rows is rows:
            self.records = [*records[:row], new, *records[row + 1 :]]


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

    @staticmethod
    def _value_key(index: int, value: TValue) -> str:
        """Get the key `value`, at `index` in `values`, is saved and sent by.

        Not its label, which changes with the app's language: an enum member's name, a
        string itself, else its position.
        """
        if isinstance(value, enum.Enum):
            return value.name
        if isinstance(value, str):
            return value
        return str(index)

    @property
    def options(self) -> list[tuple[str, str]]:
        """Get each of `values` as its key (see `serialize_value`) and its label, in order."""
        return [
            (self._value_key(index, value), label)
            for index, (label, value) in enumerate(self.values.items())
        ]

    def serialize_value(self) -> Optional[str]:
        """Serialize `value` as its key: its label could be in another language on load."""
        if self.value is None:
            return None
        for index, candidate in enumerate(self.values.values()):
            if candidate == self.value:
                return self._value_key(index, candidate)
        return None

    def deserialize_value(self, key: Optional[str]) -> Optional[TValue]:
        """Look up a key previously produced by `serialize_value` back into a TValue.

        A label is accepted too, as older state files saved it.
        """
        if key is None:
            return None
        for index, candidate in enumerate(self.values.values()):
            if self._value_key(index, candidate) == key:
                return candidate
        if key in self.values:
            return self.values[key]
        LOGGER.warning(
            "Cannot restore %s.value from saved state: %r is not among the current options %r.",
            type(self).__name__,
            key,
            list(self.values),
        )
        return None


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
    label: str = attrs.field(default="", metadata={UI_TEXT: True})

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

    title: str = attrs.field(default="", metadata={UI_TEXT: True})


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
    or end: a subclass sets ``align = Align.END``. On the web, a row narrower than 42rem
    stacks its views, unless none takes a share.
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


class GridPosition(NamedTuple):
    """A view's cell in a `GridView`, counted from 0, spanning more cells to its right or below."""

    row: int
    column: int
    row_span: int = 1
    column_span: int = 1

    @property
    def cells(self) -> "list[tuple[int, int]]":
        """Get the (row, column) cells the view covers."""
        return [
            (row, column)
            for row in range(self.row, self.row + self.row_span)
            for column in range(self.column, self.column + self.column_span)
        ]


class GridPositionError(ValueError):
    """A `GridView`'s view field has no cell, or one outside the grid or another view's."""


@define_view
class GridView(View):
    """Its view fields laid out in a grid: equally wide columns, rows as tall as their views.

    Each field sets its cell with its `GRID_POSITION` metadata:
    ``chart: ChartView = attrs.field(factory=ChartView, metadata={GRID_POSITION: (1, 0)})``,
    or ``GridPosition(1, 0, column_span=2)`` to span two columns. Cells no view takes are
    left empty, as are those of a hidden view. A view shorter than its row stays at its
    top; one with no share of a row (`default_stretch` 0, e.g. a button) keeps its
    content's width, at its cell's start. On the web, a grid narrower than 42rem stacks
    its views in one column, row by row.
    """

    _renderer_key = "grid"

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        taken: dict[tuple[int, int], str] = {}
        for name, (_, position) in self._named_positions().items():
            if position.row < 0 or position.column < 0:
                msg = f"{type(self).__name__}.{name}: no cell before row or column 0"
                raise GridPositionError(msg)
            if position.row_span < 1 or position.column_span < 1:
                msg = f"{type(self).__name__}.{name}: a span is at least 1"
                raise GridPositionError(msg)
            for cell in position.cells:
                if cell in taken:
                    msg = f"{type(self).__name__}.{name}: cell {cell} is {taken[cell]}'s"
                    raise GridPositionError(msg)
                taken[cell] = name

    @property
    def positioned_views(self) -> list[tuple[View, GridPosition]]:
        """Get the views in the grid with their cells, row by row."""
        return sorted(self._named_positions().values(), key=lambda vp: (vp[1].row, vp[1].column))

    @property
    def row_count(self) -> int:
        """Get the number of rows: down to the lowest view's last."""
        return max((p.row + p.row_span for _, p in self.positioned_views), default=0)

    @property
    def column_count(self) -> int:
        """Get the number of columns: up to the rightmost view's last."""
        return max((p.column + p.column_span for _, p in self.positioned_views), default=0)

    def _named_positions(self) -> dict[str, tuple[View, GridPosition]]:
        """Get each view field's view and cell, by field name."""
        positions: dict[str, tuple[View, GridPosition]] = {}
        for f in attrs.fields(cast("type[AttrsInstance]", type(self))):
            if isinstance(view := getattr(self, f.name), View):
                position = f.metadata.get(GRID_POSITION)
                if position is None:
                    msg = f"{type(self).__name__}.{f.name}: no GRID_POSITION in its metadata"
                    raise GridPositionError(msg)
                positions[f.name] = (view, GridPosition(*position))
        return positions


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
    #: names the page in its router; a subclass sets it: ``route = "results"``
    route: ClassVar[str] = ""
    #: the `title` the page starts with: ``page_title = T("Results")``
    page_title: ClassVar[str] = ""

    action: ActionView = attrs.field(factory=ActionView, metadata={OMIT: True})

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.title = self.page_title

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
                    "letters, digits, '_' and '-' only. Set it in the page's class: "
                    'route = "results".'
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

# from __future__ import annotations

import contextlib
import contextvars
import copy
import datetime
import decimal
import enum
import functools
import json
import logging
import math
import operator
import re
import sys
import threading
import weakref
from collections import deque
from collections.abc import Callable, Hashable, Mapping, Sequence
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
from composeui.core.model import InvalidStateError, Model, RefusedError
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
    import argparse
    from collections.abc import Iterable, Iterator

    from attrs import AttrsInstance


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
            for name in ("rows", "editable_columns", "sortable_columns", "filterable_columns"):
                del data[name]
            return data

        return unstructure_record_table
    if not issubclass(view_cls, ValuesGroupMixin):
        return unstructure

    def unstructure_radio_group(obj: "ValuesGroupMixin[Any]") -> dict[str, Any]:
        data = unstructure(cast("AttrsInstance", obj))
        data["value"] = obj.serialize_value()
        return data

    return unstructure_radio_group


#: what a `RecordTableView`'s records and columns set, which loading leaves to them
_RECORD_TABLE_SETUP = (
    "rows",
    "records",
    "editable_columns",
    "sortable_columns",
    "filterable_columns",
)


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
                or (f.name in _RECORD_TABLE_SETUP and isinstance(current_view, RecordTableView))
            ):
                continue
            new_value = new_data[f.name]
            current_field = getattr(current_view, f.name, None)
            if isinstance(current_field, View) and isinstance(new_value, dict):
                states.append((current_field, new_value))
                continue
            value = CONVERTER.structure(new_value, f.type)
            if isinstance(current_view, TableMixin):
                # a sort or a filter on a column the table no longer sorts or filters
                value = current_view.loadable(f.name, value)
            setattr(current_view, f.name, value)


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


def set_references(root: "View", main_view: "MainView", model: "Optional[Model]") -> None:
    """Give `root` and its children their main view, and their signals the main view and model.

    What the signals pass to a callback asking for ``main_view`` or ``model`` by name.
    A list of views keeps both, for the views it builds later.
    """
    views: deque[View] = deque([root])
    main_view_reference = weakref.ref(main_view)
    while len(views) > 0:
        current_view = views.popleft()
        current_view._main_view = main_view_reference  # noqa: SLF001
        if isinstance(current_view, ListView):
            current_view._model = None if model is None else weakref.ref(model)  # noqa: SLF001
        # its children, not only its view fields: e.g. a language menu's actions
        views.extend(current_view.children_views)
        for f in attrs.fields(cast("type[AttrsInstance]", type(current_view))):
            signal = getattr(current_view, f.name)
            if isinstance(signal, Signal):
                signal.set_main_view(main_view)
                if model is not None:
                    signal.set_model(model)


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
class PickFileAction(ActionView):
    """An action picking a file to open; `file_picked` emits its path.

    On Qt and Textual, triggering it shows the file picker. On the web, the browser's
    picker uploads the file: the path is then a copy, gone once `file_picked`'s
    callbacks have run. Unlike `OpenFileAction`, the file is the app's to read, not a
    study.
    """

    #: the file types the picker offers, by name: ``{"Markdown": (".md", ".markdown")}``;
    #: on the web, a file of another type is refused
    extensions: dict[str, tuple[str, ...]] = attrs.field(
        factory=dict[str, tuple[str, ...]], metadata={OMIT: True}
    )
    file_picked: Signal[Path] = attrs.Factory(Signal[Path])

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.triggered.connect(self._pick_file)

    def _pick_file(self, *, main_view: "MainView") -> None:
        path = main_view.ask_open_filepath(extensions=self.extensions)
        if path is not None:
            self.file_picked.emit(path)


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
        self.save_as.triggered.connect(self._save_state)
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
    #: whether the window has `file_menu`, the studies' New, Open, Save, Save As and Exit;
    #: an app without studies, e.g. a viewer, sets it to False and leaves it out
    has_file_menu: ClassVar[bool] = True
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
    def children_views(self) -> list[View]:
        views = super().children_views
        if self.has_file_menu:
            return views
        # never rendered: no backend shows it, or binds its shortcuts
        return [view for view in views if view is not self.file_menu]

    @classmethod
    def add_arguments(cls, parser: "argparse.ArgumentParser") -> None:
        """Add the app's own command-line options to `parser`, e.g. a file to show.

        After the backend's (`-f`, `--language`, `--port`...); `apply_arguments` gets
        their values. None by default.
        """

    def apply_arguments(self, args: "argparse.Namespace") -> None:
        """Apply the app's own command-line options (`add_arguments`), parsed in `args`.

        Once the main view is wired and `-f`'s study is open: once on Qt and Textual, for
        every session on the web.
        """

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


@define_view
class IntInputMixin(_InputView):
    # properties
    value: Optional[int] = attrs.field(default=None)
    minimum: Optional[int] = attrs.field(default=None)
    maximum: Optional[int] = attrs.field(default=None)


@define_view
class IntInputView(IntInputMixin, View):
    """A whole number, e.g. an hour of the day; a spin box where the toolkit has one."""

    _renderer_key = "int_input"


@define_view
class SliderMixin:
    def _check_step(self, _attribute: "attrs.Attribute[Any]", step: int) -> None:
        if step <= 0:
            msg = f"Cannot set {type(self).__name__}.step to {step}: it must be positive."
            raise ValueError(msg)

    #: from `minimum` to `maximum` by `step`; shown at its nearest step (see `position`)
    value: int = attrs.field(default=0)
    minimum: int = attrs.field(default=0)
    #: the last step, if `maximum - minimum` is not a whole number of steps, falls short of it
    maximum: int = attrs.field(default=100)
    step: int = attrs.field(default=1, validator=[_check_step])
    #: the user moved the handle; not emitted when `value` is set in code
    value_changed: Signal[int] = attrs.Factory(Signal[int])

    @staticmethod
    def last_position(minimum: int, maximum: int, step: int) -> int:
        """Get the steps from `minimum` to the last one at most `maximum`; 0 if none."""
        return max(0, (maximum - minimum) // step)

    @staticmethod
    def position(value: int, minimum: int, maximum: int, step: int) -> int:
        """Get the handle's position, in steps from `minimum`: `value`'s nearest, in range.

        Takes them all, as a renderer refreshes one before the view holds the new value.
        """
        last = SliderMixin.last_position(minimum, maximum, step)
        # a value halfway between two steps goes up, whatever the step (`round` goes even)
        return min(max(0, (value - minimum + step // 2) // step), last)


@define_view
class SliderView(SliderMixin, View):
    """A whole number picked by dragging a handle, e.g. a number of workers.

    Its value is shown beside the track, so that its row is no taller than a field's.
    """

    _renderer_key = "slider"


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
class MarkdownMixin:
    #: read-only Markdown, e.g. a help page; its links open in the browser
    text: str = attrs.field(default="", metadata={UI_TEXT: True})


@define_view
class MarkdownView(MarkdownMixin, View):
    _renderer_key = "markdown"


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


@define_view
class MetricView(View):
    """A figure read at a glance, e.g. the jobs running, and how much it changed.

    A row of them in a `HorizontalView` makes a dashboard's summary.
    """

    _renderer_key = "metric"

    #: what the figure counts, e.g. "Running"
    label: str = attrs.field(default="", metadata={UI_TEXT: True})
    #: the figure as shown, formatted by the app, e.g. "3" or "12.5 GB"
    value: str = attrs.field(default="")
    #: how much the figure changed; None shows no badge, else its sign colors the badge
    delta: Optional[float] = attrs.field(default=None)
    #: after the change in its badge, e.g. "since yesterday"
    delta_text: str = attrs.field(default="", metadata={UI_TEXT: True})

    @staticmethod
    def badge(delta: float, delta_text: str) -> str:
        """Get the badge's text, e.g. "↑ 2 since yesterday", a fall "↓ 2", no change "→ 0".

        Takes both, as a renderer refreshes one before the view holds the new value.
        """
        arrow = "↑" if delta > 0 else "↓" if delta < 0 else "→"
        # 15 digits: 2.0 shows "2" and 0.1 + 0.2 shows "0.3", never an exponent before 1e15
        text = f"{arrow} {abs(delta):.15g}"
        return f"{text} {delta_text}" if delta_text != "" else text


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

    def _check_height(self, _attribute: "attrs.Attribute[Any]", height: Optional[int]) -> None:
        if height is not None and height <= 0:
            msg = f"Cannot set {type(self).__name__}.height to {height}: it must be positive."
            raise ValueError(msg)

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
    #: its height on screen, in pixels (a terminal's rows of about 16), e.g. to keep a
    #: shape's proportions; None: the backend's own. The app's layout, not a study's
    height: Optional[int] = attrs.field(
        default=None, validator=[_check_height], metadata={OMIT: True}
    )
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


def _parse_bool(text: Any, _type: type) -> bool:
    if isinstance(text, str) and text.lower() in ("true", "false"):
        return text.lower() == "true"
    msg = f"{text!r} isn't a boolean"
    raise ValueError(msg)


#: parses a cell's text into a record's field; strict about booleans, which
#: `bool("False")` would make true
_CELL_CONVERTER = CONVERTER.copy()
_CELL_CONVERTER.register_structure_hook(bool, _parse_bool)


class FilterProblem(enum.Enum):
    """Why a filter's text doesn't parse (see `parse_filter`)."""

    #: nothing typed
    EMPTY = enum.auto()
    #: not a number, for a number column
    NOT_A_NUMBER = enum.auto()
    #: not a date, for a date column
    NOT_A_DATE = enum.auto()
    #: neither true nor false, for a boolean column
    NOT_A_BOOLEAN = enum.auto()
    #: a range whose start is after its end
    REVERSED_RANGE = enum.auto()
    #: not a valid regular expression, for a text column's ``/pattern/``
    NOT_A_PATTERN = enum.auto()


class FilterError(ValueError):
    """A filter's text that doesn't parse: `problem` says why (see `TableMixin.filter_error`)."""

    def __init__(self, problem: FilterProblem, text: str) -> None:
        super().__init__(f"{text!r}: {problem.name.lower().replace('_', ' ')}")
        self.problem = problem
        self.text = text


class FilterOperator(enum.Enum):
    """How a filter compares a cell with its value."""

    CONTAINS = "contains"
    NOT_CONTAINS = "!"
    TEXT_EQUAL = "=text"
    TEXT_NOT_EQUAL = "!=text"
    STARTS_WITH = "start*"
    ENDS_WITH = "*end"
    MATCHES = "/regex/"
    EMPTY = "empty"
    EQUAL = "="
    NOT_EQUAL = "!="
    LESS = "<"
    LESS_OR_EQUAL = "<="
    GREATER = ">"
    GREATER_OR_EQUAL = ">="
    RANGE = ".."


#: the comparisons a filter's text starts with, the longer before their prefixes
_COMPARISONS = (
    FilterOperator.GREATER_OR_EQUAL,
    FilterOperator.LESS_OR_EQUAL,
    FilterOperator.NOT_EQUAL,
    FilterOperator.GREATER,
    FilterOperator.LESS,
    FilterOperator.EQUAL,
)


#: each comparison, as a function of a cell's value and the filter's
_COMPARE: Mapping[FilterOperator, Callable[[Any, Any], Any]] = {
    FilterOperator.EQUAL: operator.eq,
    FilterOperator.NOT_EQUAL: operator.ne,
    FilterOperator.LESS: operator.lt,
    FilterOperator.LESS_OR_EQUAL: operator.le,
    FilterOperator.GREATER: operator.gt,
    FilterOperator.GREATER_OR_EQUAL: operator.ge,
}


#: each text comparison, as a function of the filter's value and a cell's text
_TEXT_MATCHES: Mapping[FilterOperator, Callable[[Any, str], Any]] = {
    FilterOperator.CONTAINS: lambda value, text: value in text.casefold(),
    FilterOperator.NOT_CONTAINS: lambda value, text: value not in text.casefold(),
    FilterOperator.TEXT_EQUAL: lambda value, text: text.casefold() == value,
    FilterOperator.TEXT_NOT_EQUAL: lambda value, text: text.casefold() != value,
    FilterOperator.STARTS_WITH: lambda value, text: text.casefold().startswith(value),
    FilterOperator.ENDS_WITH: lambda value, text: text.casefold().endswith(value),
    FilterOperator.MATCHES: lambda value, text: value.search(text) is not None,
}


@attrs.frozen
class Filter:
    """A column's filter, parsed from the text the user typed (see `parse_filter`)."""

    operator: FilterOperator
    #: the text a cell is compared with (casefolded), a compiled regular expression, or
    #: the value a cell's is compared with
    value: Any = None
    #: a range's end
    upper: Any = None

    def matches(self, value: Any, text: str) -> bool:
        """Tell whether a cell passes: its value (its text in a text column) and its text."""
        if self.operator is FilterOperator.EMPTY:
            return value is None or text == ""
        if self.operator in _TEXT_MATCHES:
            return bool(_TEXT_MATCHES[self.operator](self.value, text))
        if value is None:
            return False
        try:
            return self._compares(value)
        except TypeError:  # a value of another type, e.g. the column's since changed
            return False

    def _compares(self, value: Any) -> bool:
        if self.operator is FilterOperator.RANGE:
            return bool(self.value <= value <= self.upper)
        return bool(_COMPARE[self.operator](value, self.value))


class ColumnKind(enum.Enum):
    """What a column's cells hold, which sets how they sort and filter."""

    TEXT = enum.auto()
    NUMBER = enum.auto()
    DATE = enum.auto()
    BOOLEAN = enum.auto()


def column_kind(field_type: Any) -> ColumnKind:
    """Get the kind of a column showing a field of `field_type` (`Optional` or not)."""
    types = [arg for arg in get_args(field_type) if arg is not type(None)]
    if get_origin(field_type) is Union and len(types) == 1:
        field_type = types[0]
    if field_type is bool:
        return ColumnKind.BOOLEAN
    if field_type in (int, float, decimal.Decimal):
        return ColumnKind.NUMBER
    if field_type in (datetime.date, datetime.datetime):
        return ColumnKind.DATE
    return ColumnKind.TEXT


def _parse_value(text: str, field_type: Any, kind: ColumnKind) -> Any:
    """Parse a filter's value as the column's field, the way an edit is parsed."""
    types = [arg for arg in get_args(field_type) if arg is not type(None)]
    base = types[0] if get_origin(field_type) is Union and len(types) == 1 else field_type
    problems = {
        ColumnKind.NUMBER: FilterProblem.NOT_A_NUMBER,
        ColumnKind.DATE: FilterProblem.NOT_A_DATE,
        ColumnKind.BOOLEAN: FilterProblem.NOT_A_BOOLEAN,
    }
    try:
        # as `_cell_text` writes a date: ISO, which the converter doesn't read
        if base is datetime.datetime:
            return datetime.datetime.fromisoformat(text)
        if base is datetime.date:
            return datetime.date.fromisoformat(text)
        if base is decimal.Decimal:
            return decimal.Decimal(text)
        return _CELL_CONVERTER.structure(text, base)
    except (*_BAD_STATE_ERRORS, decimal.InvalidOperation) as error:
        raise FilterError(problems[kind], text) from error


def as_pattern(text: str) -> str:
    """Write a regular expression as a text column's filter: between slashes."""
    return f"/{text}/"


def split_pattern(text: str) -> tuple[str, bool]:
    """Get a filter's text without its slashes, and whether it's a regular expression.

    The user writes a pattern without them, a toggle saying it is one (see `as_pattern`).
    """
    is_pattern = len(text) >= 2 and text.startswith("/") and text.endswith("/")  # noqa: PLR2004
    return (text[1:-1], True) if is_pattern else (text, False)


def _parse_text(text: str) -> Filter:
    """Parse a text column's filter, its text stripped and neither empty nor ``=``.

    A regular expression (`as_pattern`) searches the cells (ignoring case), ``=kitchen``
    keeps the cells equal to the text and ``!=kitchen`` the others, ``!kit`` the cells not
    containing it, ``kit*`` those starting with it and ``*en`` those ending with it. Else
    the cells containing it.
    """
    pattern, is_pattern = split_pattern(text)
    if is_pattern:
        try:
            return Filter(FilterOperator.MATCHES, re.compile(pattern, re.IGNORECASE))
        except re.error as error:
            raise FilterError(FilterProblem.NOT_A_PATTERN, pattern) from error
    for prefix, comparison in (
        ("!=", FilterOperator.TEXT_NOT_EQUAL),
        ("=", FilterOperator.TEXT_EQUAL),
        ("!", FilterOperator.NOT_CONTAINS),
    ):
        if text.startswith(prefix) and len(text) > len(prefix):
            return Filter(comparison, text[len(prefix) :].strip().casefold())
    if len(text) > 1 and text.endswith("*") and not text.startswith("*"):
        return Filter(FilterOperator.STARTS_WITH, text[:-1].casefold())
    if len(text) > 1 and text.startswith("*") and not text.endswith("*"):
        return Filter(FilterOperator.ENDS_WITH, text[1:].casefold())
    return Filter(FilterOperator.CONTAINS, text.strip("*").casefold())


def parse_filter(text: str, field_type: Any = str) -> Filter:
    """Parse a filter's text for a column showing a field of `field_type`.

    In a text column, ignoring case: the cells containing the text, or as `_parse_text`
    says (``=exact``, ``!=exact``, ``!not``, ``start*``, ``*end``, ``/regex/``). In a number
    or a date column, a comparison (``>20``, ``>=20``, ``<20``, ``<=20``, ``!=20``), a range
    (``18..24``, both ends included) or a bare value, meaning ``=``. In a boolean column,
    ``true`` or ``false``. In any column, ``=`` alone: the empty cells. Raise
    `FilterError` when the text doesn't parse.
    """
    text = text.strip()
    if text == "":
        raise FilterError(FilterProblem.EMPTY, text)
    if text == "=":
        return Filter(FilterOperator.EMPTY)
    kind = column_kind(field_type)
    if kind is ColumnKind.TEXT:
        return _parse_text(text)
    if kind is ColumnKind.BOOLEAN:
        return Filter(FilterOperator.EQUAL, _parse_value(text, field_type, kind))
    for comparison in _COMPARISONS:
        if text.startswith(comparison.value):
            value = text[len(comparison.value) :].strip()
            return Filter(comparison, _parse_value(value, field_type, kind))
    if ".." in text:
        lower, _, upper = (part.strip() for part in text.partition(".."))
        range_filter = Filter(
            FilterOperator.RANGE,
            _parse_value(lower, field_type, kind),
            _parse_value(upper, field_type, kind),
        )
        if range_filter.value > range_filter.upper:
            raise FilterError(FilterProblem.REVERSED_RANGE, text)
        return range_filter
    return Filter(FilterOperator.EQUAL, _parse_value(text, field_type, kind))


#: the text of a table's filter bar, which the renderers show
FILTER_TEXTS: Mapping[str, str] = {
    "search": T("Search"),
    "add_filter": T("+ Filter"),
    "column": T("Column"),
    "value": T("Value"),
    "add": T("Add"),
    "clear": T("Clear"),
    "count": T("{shown} of {total}"),
    "no_match": T("No rows match the filters"),
    "remove": T("Remove the filter on {header}"),
    "edit": T("Edit the filter on {header}"),
    "chip": T("{header}: {filter}"),
    "chip_pattern": T("{header} matches {filter}"),
    "pattern": T("Regular expression"),
}


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

    The user sorts the rows by a column of `sortable_columns` (`sort_column`, ascending
    unless `sort_descending`), searches the text of `filterable_columns` (`search`) and
    filters each of them (`filters`, the text typed, see `parse_filter`). The table shows
    `shown_rows`, which these compute; the indexes the table emits or takes stay those of
    `rows` whatever the order, and a search or a filter hiding a selected row deselects
    it, `selection_changed` emitting. New `rows` keep the order, the search and the
    filters.
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

    def _check_sort_column(self, _attribute: "attrs.Attribute[Any]", column: Optional[int]) -> None:
        if column is not None and not self._is_column(column, self.sortable_columns):
            name = type(self).__name__
            msg = f"Cannot sort {name} by column {column}: it isn't one of its sortable columns."
            raise ValueError(msg)

    def _check_filters(self, _attribute: "attrs.Attribute[Any]", filters: dict[int, str]) -> None:
        name = type(self).__name__
        for column, text in filters.items():
            if not self._is_column(column, self.filterable_columns):
                msg = (
                    f"Cannot filter {name} by column {column}: it isn't one of its filterable"
                    " columns."
                )
                raise ValueError(msg)
            parse_filter(text, self._column_type(column))

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
            # the user edited a cell: the selection stays on its rows, which may still move
            # or hide, as their cells sort or filter
            object.__setattr__(self, "rows", rows)
            self._show_rows(self.selected_rows, force=False)
            return rows
        edited = self._edited_rows if self._edited_rows is not None else self.rows
        # each selected row as edited, then as it was
        selected = [(edited[row], self.rows[row]) for row in self.selected_rows]
        # unshown until the rows are: the renderer shows the selection with them
        object.__setattr__(self, "selected_rows", [])
        rows = notify_renderer(cast("View", self), attribute, rows)
        object.__setattr__(self, "rows", rows)
        found: set[int] = set()
        for candidates in selected:
            held = [rows.index(cells) for cells in candidates if rows.count(cells) == 1]
            found.update(held[:1])
        self._show_rows(sorted(found), force=True)
        return rows

    def _reconcile_sortable(
        self, attribute: "attrs.Attribute[Any]", columns: list[int]
    ) -> list[int]:
        """Stop sorting by a column no longer sortable, and notify the renderer."""
        self._store(attribute, columns)
        if self.sort_column is not None and self.sort_column not in columns:
            self.sort_column = None
        return columns

    def _reconcile_filterable(
        self, attribute: "attrs.Attribute[Any]", columns: list[int]
    ) -> list[int]:
        """Drop the filters of columns no longer filterable, and notify the renderer."""
        self._store(attribute, columns)
        if any(column not in columns for column in self.filters):
            self.filters = {
                column: text for column, text in self.filters.items() if column in columns
            }
        if len(columns) == 0 and self.search != "":
            self.search = ""  # nothing left to search
        return columns

    def _store(self, attribute: "attrs.Attribute[Any]", value: Any) -> None:
        """Set an attribute, then notify the renderer: it shows the view as it now is."""
        old = getattr(self, attribute.name)
        object.__setattr__(self, attribute.name, value)
        renderer = cast("View", self).renderer
        if (
            old != value
            and isinstance(renderer, (Renderer, RendererContainer))
            and not renderer.is_updating_state()
        ):
            renderer.refresh_attribute(attribute.name, value)

    def _reshow(self, attribute: "attrs.Attribute[Any]", value: Any) -> Any:
        """Show the rows as `value` sorts or filters them, and notify the renderer."""
        if getattr(self, attribute.name) == value:
            return value
        self._store(attribute, value)
        selected = self.selected_rows
        shown = self._show_rows(selected, force=True)
        if shown != selected:
            self.selection_changed.emit(shown)
        return value

    headers: list[str] = attrs.field(factory=list[str], metadata={UI_TEXT: True})
    #: the filter bar's text, by what it's for (see `FILTER_TEXTS`)
    filter_texts: dict[str, str] = attrs.field(
        factory=lambda: dict(FILTER_TEXTS), metadata={UI_TEXT: True}
    )
    # before `selected_rows`, which it limits
    selection_mode: SelectionMode = attrs.field(
        default=SelectionMode.SINGLE, on_setattr=_reconcile_mode
    )
    rows: list[list[str]] = attrs.field(factory=list[list[str]], on_setattr=_reconcile_rows)
    # the sort and the filters, after `rows` and before `selected_rows`: loading saved state
    # shows the rows as they were before selecting them again
    sortable_columns: list[int] = attrs.field(factory=list[int], on_setattr=_reconcile_sortable)
    filterable_columns: list[int] = attrs.field(factory=list[int], on_setattr=_reconcile_filterable)
    sort_column: Optional[int] = attrs.field(
        default=None,
        validator=[_check_sort_column],
        on_setattr=[attrs.setters.validate, _reshow],
    )
    sort_descending: bool = attrs.field(default=False, on_setattr=_reshow)
    #: text the shown rows contain in a filterable column, ignoring case
    search: str = attrs.field(default="", on_setattr=_reshow)
    #: the filters by column, as typed (see `parse_filter`)
    filters: dict[int, str] = attrs.field(
        factory=dict[int, str],
        validator=[_check_filters],
        on_setattr=[attrs.setters.validate, _reshow],
    )
    # after `rows`: loading saved state checks it against the rows already loaded
    selected_rows: list[int] = attrs.field(factory=list[int], validator=[_check_selected_rows])
    #: the indexes in `rows` of the rows shown, in their order: computed, never set
    shown_rows: list[int] = attrs.field(
        factory=list[int], init=False, on_setattr=attrs.setters.frozen, metadata={OMIT: True}
    )
    selection_changed: Signal[list[int]] = attrs.Factory(Signal[list[int]])
    editable_columns: list[int] = attrs.Factory(list[int])
    cell_edited: Signal[int, int, str] = attrs.Factory(Signal[int, int, str])
    #: `rows` as the edit being emitted leaves them, while its callbacks run
    _edited_rows: Optional[list[list[str]]] = attrs.field(
        default=None, init=False, repr=False, metadata={OMIT: True}
    )

    def sort_by(self, column: int) -> None:
        """Sort as a click on the column's header does: ascending, descending, then not."""
        if self.sort_column != column:
            self.sort_descending = False
            self.sort_column = column
        elif not self.sort_descending:
            self.sort_descending = True
        else:
            self.sort_column = None
            self.sort_descending = False

    def filter_error(self, column: int, text: str) -> Optional[str]:
        """Say why `text` can't filter `column`, translated; None if it can."""
        try:
            parse_filter(text, self._column_type(column))
        except FilterError as error:
            tr = cast("View", self).tr
            messages = {
                FilterProblem.EMPTY: tr("Type a value to filter by"),
                FilterProblem.NOT_A_NUMBER: tr('"{text}" isn\'t a number'),
                FilterProblem.NOT_A_DATE: tr('"{text}" isn\'t a date, as 2024-01-31'),
                FilterProblem.NOT_A_BOOLEAN: tr('"{text}" isn\'t true or false'),
                FilterProblem.REVERSED_RANGE: tr("The range's start is after its end"),
                FilterProblem.NOT_A_PATTERN: tr('"{text}" isn\'t a valid regular expression'),
            }
            return messages[error.problem].format(text=error.text)
        return None

    def filter_takes_pattern(self, column: int) -> bool:
        """Tell whether a regular expression filters `column`: a text column."""
        return column_kind(self._column_type(column)) is ColumnKind.TEXT

    def filter_placeholder(self, column: int, *, is_pattern: bool = False) -> str:
        """Hint at what filters `column`, translated: a regular expression, or else text."""
        kind = column_kind(self._column_type(column))
        tr = cast("View", self).tr
        if is_pattern and kind is ColumnKind.TEXT:
            return tr("a regular expression, as Room [1-3]")
        if kind is ColumnKind.NUMBER:
            return tr(">=20, 18..24")
        if kind is ColumnKind.DATE:
            return tr(">=2024-01-31")
        if kind is ColumnKind.BOOLEAN:
            return tr("true or false")
        return tr("contains, =exact, start*, !not")

    def filter_chip(self, column: int) -> str:
        """Show a filter as its chip does: its column's header, then the text typed.

        Apart, as a label and its value: the header isn't part of what's typed. A regular
        expression without its slashes: "Room matches Room [1-3]".
        """
        header = self.headers[column] if column < len(self.headers) else ""
        text, is_pattern = split_pattern(self.filters[column])
        if is_pattern and self.filter_takes_pattern(column):
            chip = self.filter_texts.get("chip_pattern", "{header} {filter}")
        else:
            chip, text = self.filter_texts.get("chip", "{header}: {filter}"), self.filters[column]
        return chip.format(header=header, filter=text)

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

    def loadable(self, name: str, value: Any) -> Any:
        """Get the part of a saved sort or filters (`name`) the table's columns still take."""
        if name == "sort_column":
            return value if value is None or self._is_column(value, self.sortable_columns) else None
        if name == "filters":
            return {
                column: text
                for column, text in value.items()
                if self._is_column(column, self.filterable_columns)
                and self.filter_error(column, text) is None
            }
        return value

    def _is_column(self, column: int, columns: list[int]) -> bool:
        return column in columns and 0 <= column < len(self.headers)

    def _column_type(self, _column: int) -> Any:
        """Get the type of the field a column shows: text, in a table of text."""
        return str

    def _cell_value(self, row: int, column: int) -> Any:
        """Get the value a cell sorts and filters by: its text, in a table of text."""
        return self._cell_text(row, column)

    def _cell_text(self, row: int, column: int) -> str:
        cells = self.rows[row]
        return cells[column] if column < len(cells) else ""

    def _shown(self) -> list[int]:
        """Get the indexes in `rows` of the rows the search and the filters pass, sorted."""
        filters: dict[int, Filter] = {}
        for column, text in self.filters.items():
            # a filter the columns no longer take, e.g. changed since, filters nothing
            with contextlib.suppress(FilterError):
                filters[column] = parse_filter(text, self._column_type(column))
        needle = self.search.strip().casefold()
        searched = [column for column in self.filterable_columns if column < len(self.headers)]
        shown = [
            row
            for row in range(len(self.rows))
            if (
                needle == ""
                or any(needle in self._cell_text(row, column).casefold() for column in searched)
            )
            and all(
                row_filter.matches(self._cell_value(row, column), self._cell_text(row, column))
                for column, row_filter in filters.items()
            )
        ]
        if self.sort_column is None or self.sort_column >= len(self.headers):
            return shown
        return self._sorted(shown, self.sort_column)

    def _sorted(self, rows: list[int], column: int) -> list[int]:
        """Sort `rows` by `column`, stably: by value, text by `str.casefold`, empty cells last."""
        is_text = column_kind(self._column_type(column)) is ColumnKind.TEXT

        def key(row: int) -> Any:
            value = self._cell_value(row, column)
            if value is None or value == "":
                return None
            return value.casefold() if is_text else value

        keys = {row: key(row) for row in rows}
        present = [row for row in rows if keys[row] is not None]
        try:
            present.sort(key=keys.__getitem__, reverse=self.sort_descending)
        except TypeError:  # values that don't compare, e.g. the column's type since changed
            present.sort(
                key=lambda row: self._cell_text(row, column).casefold(),
                reverse=self.sort_descending,
            )
        return present + [row for row in rows if keys[row] is None]

    def _show_rows(self, selected: list[int], *, force: bool) -> list[int]:
        """Compute `shown_rows`, keep the shown rows of `selected` selected, and show both.

        The renderer gets `shown_rows` when they changed, or always with `force` (it shows
        the rows with them); once the view holds them both, so it can show them together.
        Return the rows still selected.
        """
        shown = self._shown()
        is_shown = set(shown)
        kept = [row for row in selected if row in is_shown]
        changed = shown != self.shown_rows
        object.__setattr__(self, "shown_rows", shown)
        object.__setattr__(self, "selected_rows", kept)
        renderer = cast("View", self).renderer
        if isinstance(renderer, (Renderer, RendererContainer)) and (force or changed):
            # even while the renderer updates the view: its widget doesn't order the rows
            renderer.refresh_attribute("shown_rows", shown)
        return kept


@define_view
class TableView(TableMixin, View):
    _renderer_key = "table"

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        object.__setattr__(self, "shown_rows", self._shown())


RecordT = TypeVar("RecordT", bound="AttrsInstance")


@attrs.frozen
class Column:
    """A column of a `RecordTableView`: a field of its records, under `header`."""

    #: the name of the records' field the column shows
    field: str
    header: str
    #: whether the user edits the column's cells
    editable: bool = False
    #: whether the user sorts the rows by the column
    sortable: bool = False
    #: whether the user searches and filters the column
    filterable: bool = False


def _cell_text(value: Any) -> str:
    """Show a record's field in its cell: as saved, None as an empty cell."""
    return "" if value is None else str(CONVERTER.unstructure(value))


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
        # first: the rows sort and filter by the columns' fields
        object.__setattr__(self, "columns", columns)
        self.headers = [translate_again(column.header, self._tr) for column in columns]
        self.editable_columns = [index for index, column in enumerate(columns) if column.editable]
        self.sortable_columns = [index for index, column in enumerate(columns) if column.sortable]
        self.filterable_columns = [
            index for index, column in enumerate(columns) if column.filterable
        ]
        self.rows = [self._cells(record, columns) for record in self.records]
        return columns

    def _reconcile_records(
        self, _attribute: "attrs.Attribute[Any]", records: list[RecordT]
    ) -> list[RecordT]:
        # first: the rows sort and filter by the records' values
        object.__setattr__(self, "records", records)
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

    def _column_type(self, column: int) -> Any:
        """Get the type of the column's field, by which its cells sort and filter."""
        if column >= len(self.columns):
            return str
        try:
            fields = attrs.fields_dict(attrs.resolve_types(self.record_type))
        except TypeError:  # a table not knowing its records' type: its cells are text
            return str
        field = fields.get(self.columns[column].field)
        return str if field is None else field.type

    def _cell_value(self, row: int, column: int) -> Any:
        if row >= len(self.records) or column >= len(self.columns):
            return self._cell_text(row, column)
        value = getattr(self.records[row], self.columns[column].field)
        # an enum sorts and filters by its text, as shown
        return _cell_text(value) if isinstance(value, enum.Enum) else value

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
    #: what to enter in the field, shown by a "?" button beside the label (a hint on Textual)
    help: str = attrs.field(default="", metadata={UI_TEXT: True})
    #: the "?" button's name for screen readers
    help_button_text: str = attrs.field(default=T("Help"), metadata={UI_TEXT: True})

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
class RowIntInputView(FormRowView, IntInputMixin):
    _field_renderer_key = "int_input"


@define_view
class LabelRowIntInputView(FormLabelRowView, IntInputMixin):
    _field_renderer_key = "int_input"


@define_view
class RowSliderView(FormRowView, SliderMixin):
    _field_renderer_key = "slider"


@define_view
class LabelRowSliderView(FormLabelRowView, SliderMixin):
    _field_renderer_key = "slider"


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


@define_view
class ExpanderView(View):
    """A collapsible section: its title always shown, its view fields only while expanded.

    Its view fields are laid out one above the other, as in a `VerticalView`, e.g. a
    record's details above its Edit and Delete buttons.
    """

    _renderer_key = "expander"

    #: shown in the header the user clicks to expand or collapse the section
    title: str = attrs.field(default="", metadata={UI_TEXT: True})
    is_expanded: bool = attrs.field(default=False)
    #: the user expanded or collapsed the section; not emitted when `is_expanded` is set in code
    toggled: Signal[bool] = attrs.Factory(Signal[bool])


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


@define_view
class SidebarView(View):
    """A column of views beside the pages, shown whatever the page, e.g. a form creating a record.

    A field of the main view, not of its router, rather than a view repeated on each page.
    Its view fields are its content, laid out in a column on the window's left: Qt docks
    it, Textual shows it left of the scrolling content, and the web a column left of the
    pages, a drawer opened from a button in the header on a phone. The user retracts it
    to a narrow strip, and back, with a button (`is_expanded`).
    """

    _renderer_key = "sidebar"

    #: a heading above the content; none while empty
    title: str = attrs.field(default="", metadata={UI_TEXT: True})
    #: the button retracting and expanding the sidebar (opening the drawer on a phone),
    #: for screen readers and as its tooltip
    toggle_text: str = attrs.field(default=T("Sidebar"), metadata={UI_TEXT: True})
    #: whether the content shows, else a narrow strip with the button bringing it back.
    #: Layout, not study data: never saved, loaded or reset
    is_expanded: bool = attrs.field(default=True, metadata={OMIT: True})
    #: the user retracted or expanded the sidebar; not emitted when `is_expanded` is set in code
    toggled: Signal[bool] = attrs.Factory(Signal[bool])


ItemT = TypeVar("ItemT")


@define_view
class ListView(View, Generic[ItemT]):
    """A view per record, laid out in a column, e.g. an expander per record.

    A subclass builds a record's view (`build_item`). Setting `items` to the records,
    e.g. the model's, shows them: a new record gets a view of its own, a record gone
    takes its view along, and a record still there keeps its view, told by its key
    (`item_key`). A record changed keeps its view if `update_item` shows the change in
    it, so the view keeps what the user did to it (an expander stays expanded); else it
    gets a new view. The records and their views are the model's, not study data: never
    saved, loaded or reset.
    """

    _renderer_key = "list"

    #: the records' views, in the records' order; made by setting `items`
    item_views: list[View] = attrs.field(factory=list, init=False, metadata={OMIT: True})
    _items: list[ItemT] = attrs.field(factory=list, init=False, repr=False, metadata={OMIT: True})
    #: the model the signals of the views built pass on (see `set_references`)
    _model: Optional[Callable[[], Optional["Model"]]] = attrs.field(
        default=None, init=False, repr=False, eq=False, metadata={OMIT: True}
    )

    @property
    def children_views(self) -> list[View]:
        return [*super().children_views, *self.item_views]

    @property
    def items(self) -> list[ItemT]:
        """Get the records shown, in order."""
        return list(self._items)

    @items.setter
    def items(self, items: "Iterable[ItemT]") -> None:
        new_items = list(items)
        old = {
            self.item_key(item): (item, view) for item, view in zip(self._items, self.item_views)
        }
        views: list[View] = []
        keys: set[Hashable] = set()
        for item in new_items:
            key = self.item_key(item)
            if key in keys:
                msg = f"Two records of {type(self).__name__} have the key {key!r}."
                raise ValueError(msg)
            keys.add(key)
            old_item, view = old.get(key, (None, None))
            if view is None or (old_item != item and not self.update_item(view, item)):
                view = self._new_item_view(item)
            views.append(view)
        self._items = new_items
        self.item_views = views

    def build_item(self, item: ItemT) -> View:
        """Get a new view showing `item`; a subclass builds it."""
        raise NotImplementedError(self.build_item)

    def item_key(self, item: ItemT) -> Hashable:
        """Get what tells `item` apart from the other records: the record itself by default.

        A record changed, with the same key, keeps its view; e.g. a key of its name or id.
        """
        return item

    def update_item(self, view: View, item: ItemT) -> bool:
        """Show `item`, changed, in `view`, its view; return False to get a new view instead.

        The default, so a subclass only shows a change in place where it's worth it.
        """
        return False

    def _new_item_view(self, item: ItemT) -> View:
        """Build `item`'s view, set up as the views built with the main view were.

        Its signals pass the main view and the model on, and it shows the main view's
        language; the list's renderer renders it, if the list is rendered.
        """
        view = self.build_item(item)
        main_view = None if self._main_view is None else self._main_view()
        if main_view is not None:
            set_references(view, main_view, None if self._model is None else self._model())
        _retranslate(view, self._tr)
        return view

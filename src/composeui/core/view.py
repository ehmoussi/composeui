"""The views: typed `attrs` classes that describe the UI, without a backend.

A renderer shows each view on a backend (see `composeui.core.registry`). Setting a field
of a view pushes the change to its renderer. The widget catalog lists the views.
"""

from __future__ import annotations

import array
import contextlib
import contextvars
import copy
import csv
import datetime
import decimal
import enum
import functools
import io
import json
import logging
import math
import operator
import re
import sys
import threading
import weakref
from collections import OrderedDict, deque
from collections.abc import Callable, Hashable, Mapping, Sequence
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Generic,
    NamedTuple,
    Optional,
    Protocol,
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

    from composeui.core.jobs import Job

__all__ = [
    "CHECKED_TEXTS",
    "CONVERTER",
    "GRID_POSITION",
    "OMIT",
    "SEARCH_DELAY_MS",
    "SOURCE_TABLE_JOB_ROWS",
    "STRETCH",
    "UI_TEXT",
    "ActionView",
    "Align",
    "ButtonVariant",
    "ButtonView",
    "CellKind",
    "CellStyle",
    "CellWidget",
    "ChartKind",
    "ChartView",
    "CheckBoxMixin",
    "CheckBoxView",
    "Column",
    "ComboBoxView",
    "ConsoleView",
    "ContentDialogView",
    "DateInputMixin",
    "DateInputView",
    "DialogKind",
    "DialogView",
    "EditRefusedError",
    "ExpanderView",
    "FileMenu",
    "FilePathInputMixin",
    "FilePathInputView",
    "FileView",
    "Filter",
    "FilterError",
    "FilterOperator",
    "FilterProblem",
    "FloatInputMixin",
    "FloatInputView",
    "FolderPathInputMixin",
    "FolderPathInputView",
    "FormDialogView",
    "FormLabelRowView",
    "FormRowView",
    "FormView",
    "GridPosition",
    "GridPositionError",
    "GridView",
    "GroupFormView",
    "HeaderGroup",
    "HorizontalView",
    "InputMixin",
    "InputView",
    "IntInputMixin",
    "IntInputView",
    "LabelMixin",
    "LabelRowCheckBoxView",
    "LabelRowComboBoxView",
    "LabelRowDateInputView",
    "LabelRowFilePathInputView",
    "LabelRowFloatInputView",
    "LabelRowFolderPathInputView",
    "LabelRowInputView",
    "LabelRowIntInputView",
    "LabelRowRadioGroupView",
    "LabelRowSavePathInputView",
    "LabelRowSliderView",
    "LabelView",
    "LanguageMenu",
    "LineStyle",
    "ListSource",
    "ListView",
    "LogMixin",
    "LogType",
    "LogView",
    "MainView",
    "MapPoint",
    "MapView",
    "MarkdownMixin",
    "MarkdownView",
    "Menu",
    "MetricView",
    "NodeMark",
    "Orientation",
    "PageView",
    "PageWidth",
    "PickFileAction",
    "ProgressBarView",
    "RadioGroupView",
    "RecordTableView",
    "ReferenceLine",
    "Router",
    "RowCheckBoxView",
    "RowComboBoxView",
    "RowDateInputView",
    "RowFilePathInputView",
    "RowFloatInputView",
    "RowFolderPathInputView",
    "RowInputView",
    "RowIntInputView",
    "RowRadioGroupView",
    "RowSavePathInputView",
    "RowSliderView",
    "SavePathInputMixin",
    "SavePathInputView",
    "SelectionMode",
    "SeparatorAction",
    "Series",
    "SidebarView",
    "SliderMixin",
    "SliderView",
    "Sort",
    "SourceColumn",
    "SourceTableView",
    "SplitterView",
    "StatusBar",
    "T",
    "TabPage",
    "TabView",
    "TableMixin",
    "TableSource",
    "TableView",
    "ToolBar",
    "TreeNode",
    "TreePath",
    "TreeView",
    "TypedFormDialogView",
    "Validator",
    "ValuesGroupMixin",
    "VerticalView",
    "View",
    "as_pattern",
    "child",
    "define_view",
    "find_in_lines",
    "format_date",
    "notify_renderer",
    "parse_date",
    "replace_cell",
]


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
#: the version of how a study file holds the views' state, written in it as
#: ``{"composeui": {"format": ...}, "app": {"version": ...}, "views": ...}``. A file
#: without them is from before, and holds the views' state alone.
STATE_FORMAT = 1
#: what applying structurally wrong state can raise (from cattrs or a field's own
#: conversion, e.g. ``float("abc")``)
_BAD_STATE_ERRORS = (
    ValueError,
    TypeError,
    KeyError,
    AttributeError,
    cattrs.BaseValidationError,
    cattrs.StructureHandlerNotFoundError,
)


def _is_version(value: Any) -> bool:
    """Tell whether a study file's version is one: a positive integer, not a bool."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _is_omitted_type(tp: Any) -> bool:
    """Check whether a (possibly generic/Optional/Union) type is or wraps an omitted type."""
    origin = get_origin(tp)
    if origin is Union:
        return any(_is_omitted_type(arg) for arg in get_args(tp))
    cls = origin if origin is not None else tp
    # a dialog is what the app asks the user, and the language how it shows: not study data
    return isinstance(cls, type) and issubclass(cls, (*_OMITTED_TYPES, DialogView, LanguageMenu))


def _is_omitted_field(f: attrs.Attribute[Any]) -> bool:
    """Check whether `f` should skip (de)serialization: by type, or by `OMIT` tag."""
    return _is_omitted_type(f.type) or bool(f.metadata.get(OMIT, False))


def _is_state_field(f: attrs.Attribute[Any]) -> bool:
    """Check whether `f` is study data, which state files save and load."""
    return not _is_omitted_field(f) and not f.metadata.get(UI_TEXT, False)


@CONVERTER.register_unstructure_hook_factory(attrs.has)
def _omit_renderer_and_signals(
    cls: type[AttrsInstance],
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

        def unstructure_record_table(obj: RecordTableView[Any]) -> dict[str, Any]:
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

    def unstructure_radio_group(obj: ValuesGroupMixin[Any]) -> dict[str, Any]:
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


def _apply_state(view: View, data: dict[str, Any]) -> None:
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


def _show_checked(view: View) -> None:
    """Show the views of each check box under `view` as the box is: a study's done loading.

    Their own visibility, a state too, may have been loaded after their box's.
    """
    views = deque([view])
    while len(views) > 0:
        current = views.popleft()
        if isinstance(current, CheckBoxMixin):
            for shown in current.shown_views:
                shown.is_visible = current.is_checked
        views.extend(current.children_views)


def _reset_state(view: View, initial: View) -> None:
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


def notify_renderer(instance: View, attribute: Any, value: Any) -> Any:
    """Push the new `value` of a view's field to its renderer, if the value changed.

    The ``on_setattr`` hook of every view field (see `define_view`). Return `value`.
    """
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


def set_references(root: View, main_view: MainView, model: Optional[Model]) -> None:
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


def _retranslate(view: View, translate: Translate) -> None:
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
    """Define a view class: an `attrs` class whose field changes reach its renderer.

    Use it as ``@define_view``, or as ``@define_view(...)`` with keyword arguments for
    `attrs.define`. The fields are keyword-only. Hooks of its own (``on_setattr``) run
    after the validators, before the renderer hears the change.
    """

    def wrap(cls: _ClassT) -> _ClassT:
        options = {"kw_only": True, "slots": False, **kwargs}
        own = options.pop("on_setattr", [])
        hooks = list(own) if isinstance(own, Sequence) else [own]
        return attrs.define(
            cls, on_setattr=[attrs.setters.validate, *hooks, notify_renderer], **options
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
    """The base of every view: a part of the UI that a renderer shows on a backend.

    Setting a field of a view pushes the change to its renderer. `is_visible` shows or hides
    the view, and `is_enabled` enables or disables it.
    """

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
    _main_view: Optional[Callable[[], Optional[MainView]]] = attrs.field(
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

        A view that keeps the translation, in a field or in a list or dict of one, shows it in
        the next language that `MainView.set_language` sets. Formatted text follows too.
        """
        return TranslatedText(self._tr(text), text)

    @contextlib.contextmanager
    def refusing(self, message: str) -> Iterator[None]:
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

        Called once while the view is built, before the rest of `__attrs_post_init__`. Then
        `MainView.set_language` calls it on every view once their text is translated,
        children before their parent.
        """

    @property
    def children_views(self) -> list[View]:
        """Get the views in the fields of this view, in order."""
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

    @classmethod
    def _renderer_keys(cls) -> tuple[str, ...]:
        """Get the keys of the renderers that show the view: a backend needs each of them."""
        return () if cls._renderer_key is None else (cls._renderer_key,)

    def _render_children(self, renderer_type: RendererType) -> None:
        for child_view in self.children_views:
            child_view.render(renderer_type)


@define_view
class StatusBar(View):
    """A line at the bottom of the window that shows a short message to the user.

    `show_message` shows a message for `timeout` seconds.
    """

    _renderer_key = "status_bar"

    message: str = attrs.field(default="")
    message_changed: Signal[str] = attrs.Factory(Signal[str])
    timeout: float = attrs.field(default=3.0)
    _timer: Optional[threading.Timer] = attrs.field(default=None)

    def show_message(self, message: str) -> None:
        """Show `message` for `timeout` seconds.

        With a `timeout` of 0, the message is not dismissed automatically.
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
        """Remove the message from the status bar."""
        self.message = ""
        self._timer = None


# class FileType(enum.Enum):
#     OpenFile = enum.auto()
#     SaveFile = enum.auto()


@define_view
class FileView(View):
    """The file path that the last file dialog of the main view gave."""

    filepath: Optional[Path] = attrs.field(default=None)
    extensions: dict[str, tuple[str, ...]] = attrs.Factory(dict[str, tuple[str, ...]])
    # file_type: FileType = attrs.field(default=FileType.OpenFile)

    def _create_renderer(self, renderer_type: RendererType) -> None:
        return None


@define_view
class ActionView(View):
    """An entry of a menu or a toolbar that the user triggers, for example Save.

    `triggered` emits when the user triggers it. A checkable action (`is_checkable`) changes
    `is_checked` first, so the callbacks see the new state.
    """

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
    """The kind of a `DialogView`: a message or a confirmation."""

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
    """A line between two groups of entries in a menu or a toolbar."""

    _renderer_key = "separator"


@define_view
class Menu(View):
    """A menu of the window, with an entry for each of its action fields.

    Its `ActionView` and `SeparatorAction` fields are its entries, in order. `title` names it.
    """

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
    """The New action of the File menu, which starts a new study."""

    text: str = attrs.field(default=T("New"), metadata={UI_TEXT: True})

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.shortcut = "Ctrl+n"
        self.is_checkable = False
        self.icon = None
        self.data = None
        self.triggered.connect(self._new_study)

    def _new_study(self, *, main_view: MainView, model: Optional[Model] = None) -> None:
        study.new_study(main_view, model)


@define_view
class OpenFileAction(ActionView):
    """The Open action of the File menu, which opens a study from a file."""

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

    def _pick_file(self, *, main_view: MainView) -> None:
        path = main_view.ask_open_filepath(extensions=self.extensions)
        if path is not None:
            self.file_picked.emit(path)


@define_view
class SaveAction(ActionView):
    """The Save action of the File menu, which saves the study to a file."""

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
    """The Save As action of the File menu, which saves the study to a file."""

    text: str = attrs.field(default=T("Save As"), metadata={UI_TEXT: True})

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.shortcut = "Ctrl+Shift+s"
        self.is_checkable = False
        self.icon = None
        self.data = None


@define_view
class ExitAppAction(ActionView):
    """The Exit action of the File menu, which closes the app."""

    text: str = attrs.field(default=T("Exit"), metadata={UI_TEXT: True})

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.shortcut = "Ctrl+q"
        self.is_checkable = False
        self.icon = None
        self.data = None
        self.triggered.connect(self._exit_app)

    def _exit_app(self, *, main_view: MainView) -> None:
        main_view.close()


@define_view
class FileMenu(Menu):
    """The File menu of the main view, with New, Open, Save, Save As and Exit.

    An app without studies sets `MainView.has_file_menu` to False to leave it out.
    """

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

    def _load_state(self, *, main_view: MainView, model: Optional[Model] = None) -> None:
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

    def _save_state(self, *, main_view: MainView, model: Optional[Model] = None) -> None:
        filepath = main_view.ask_save_filepath(
            extensions={main_view.extension: (f"{main_view.extension}",)}
        )
        if filepath is not None:
            study.save_study(main_view, model, filepath)


@define_view
class LanguageMenu(Menu):
    """A menu of the app's languages, the one shown checked; triggering one shows it.

    Make it a field of the main view. The main view gives it the languages it has catalogs
    for (`MainView.languages`), and keeps the shown one checked. The menu names each
    language in itself, whatever the language shown. The language isn't study data:
    never saved, loaded or reset.
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


class PageWidth(enum.Enum):
    """How wide the content of a main view or page may grow on the web."""

    #: a column of fields, easy to read
    NARROW = enum.auto()
    #: room for side by side views, e.g. tables
    WIDE = enum.auto()
    #: the whole window
    FULL = enum.auto()


@define_view
class MainView(View):
    """The root view of an app: its window, with the menus, the status bar and the content.

    A subclass sets `app_title`, `extension` and `translations_dir`, and adds its views as
    fields. The main view saves and loads the state of its views (`save_state`,
    `load_state`), and runs work in threads with `jobs`.
    """

    _renderer_key = "main"

    #: the web content's default width; a subclass sets it: ``width = PageWidth.WIDE``
    width: ClassVar[PageWidth] = PageWidth.NARROW

    #: the app's name, in the window's title; a subclass sets it: ``app_title = T("Pipes")``
    app_title: ClassVar[str] = ""
    #: the extension of the app's study files; a subclass sets it: ``extension = ".pipe"``
    extension: ClassVar[str] = ""
    #: the app's icon, an image file: the window's on Qt, the browser tab's and the header's
    #: on the web. ComposeUI's by default; a subclass sets its own, or None for none
    app_icon: ClassVar[Optional[Path]] = Path(__file__).parent.parent / "images" / "composeui.svg"
    #: whether the window has `file_menu`, the studies' New, Open, Save, Save As and Exit;
    #: an app without studies, e.g. a viewer, sets it to False and leaves it out
    has_file_menu: ClassVar[bool] = True
    #: the version of the app's state, saved with it: a subclass raises it when a change of
    #: its views would lose an older study's state, and upgrades the state in `migrate_state`
    state_version: ClassVar[int] = 1
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
    #: emitted once the views and the model's data are in place: as the app starts, with the
    #: study of ``-f`` or a new one, and after New and Open (after `Model.loaded`). The app
    #: gives again then what a study doesn't hold, such as the source of a large table
    loaded: SignalNoArgs = attrs.Factory(SignalNoArgs)
    #: functions run in threads, their results given back on the main thread
    jobs: Jobs = attrs.field(
        default=attrs.Factory(Jobs, takes_self=True),
        init=False,
        repr=False,
        eq=False,
        metadata={OMIT: True},
    )

    #: the directory of the app's catalogs, ``<language>.json`` files (see
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
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        """Add the app's own command-line options to `parser`, e.g. a file to show.

        After the backend's (``-f``, ``--language``, ``--port``...); `apply_arguments` gets
        their values. None by default.
        """

    def apply_arguments(self, args: argparse.Namespace) -> None:
        """Apply the app's own command-line options (`add_arguments`), parsed in `args`.

        Once the main view is wired and ``-f``'s study is open: once on Qt and Textual, for
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
        self.load_state_data(self.state_data_from_file(data))
        self.state_filepath = filepath

    def file_data(self) -> dict[str, Any]:
        """Get what a study file holds: the views' state (`state_data`) and its versions."""
        return {
            "composeui": {"format": STATE_FORMAT},
            "app": {"version": self.state_version},
            "views": self.state_data(),
        }

    def state_data_from_file(self, data: Any) -> Any:
        """Get the views' state from what a study file holds (`file_data`), upgraded.

        A state of an older `state_version` goes through `migrate_state`. Raises
        `InvalidStateError` for a file of a newer ComposeUI or app, or not one at all.
        """
        invalid = f"it isn't a valid {self.extension} file"
        if not isinstance(data, dict):
            raise InvalidStateError(invalid)
        if "composeui" not in data:
            # saved before the versions were: the first of each
            state_format, version, views = 1, 1, data
        else:
            try:
                state_format = data["composeui"]["format"]
                version = data["app"]["version"]
                views = data["views"]
            except (KeyError, TypeError) as error:
                raise InvalidStateError(invalid) from error
        if not _is_version(state_format) or not _is_version(version):
            raise InvalidStateError(invalid)
        if state_format > STATE_FORMAT:
            msg = "it was saved by a newer version of ComposeUI"
            raise InvalidStateError(msg)
        if version > self.state_version:
            msg = "it was saved by a newer version of this application"
            raise InvalidStateError(msg)
        if version == self.state_version:
            return views
        try:
            return self.migrate_state(views, version)
        except _BAD_STATE_ERRORS as error:
            msg = "it doesn't match this application"
            raise InvalidStateError(msg) from error

    def migrate_state(self, data: Any, version: int) -> Any:
        """Upgrade a state saved by an older `state_version` of the app, `version`.

        Return the state as `state_data` gets it now. The app overrides it when it raises
        `state_version`, e.g. to move a renamed field's value to its new name. Without an
        override, the state loads as it is: the fields it no longer has are skipped.
        """
        del version
        return data

    def load_state_data(self, data: Any) -> None:
        """Load state, as `state_data` gets it: a study file's from `state_data_from_file`.

        Raises `InvalidStateError`, leaving this view unchanged, when the data doesn't fit
        it (see `check_state_data`).
        """
        self.check_state_data(data)
        self.jobs.drop()  # working for the study replaced
        _apply_state(self, data)
        _show_checked(self)

    def check_state_data(self, data: Any) -> None:
        """Raise `InvalidStateError` if `load_state_data` can't load `data`.

        The data is applied to a newly built main view. Applying sets the fields one by one,
        so data that fails halfway would otherwise leave this view half loaded.
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
        _show_checked(self)
        # the new view's text is as written in the code
        _retranslate(self, self._tr)

    def save_state(self, filepath: Path) -> None:
        """Save the current state into a json file, with its versions (`file_data`)."""
        with filepath.open("w") as f:
            json.dump(self.file_data(), f)
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

    def render(self, renderer_type: RendererType) -> None:
        super().render(renderer_type)
        if self.renderer is not None:
            # the jobs started before, e.g. by `setup_model`, show their results now
            self.jobs.hand_over_to(self.renderer)

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
    """The fields of a field for one line of text: its `text` and its signals."""

    # properties
    text: str = attrs.field(default="")


@define_view
class InputView(InputMixin, View):
    """A field where the user types one line of text, for example a name."""

    _renderer_key = "input"


@define_view
class FloatInputMixin(_InputView):
    """The fields of a field for a decimal number: its `value`, range and decimals."""

    # properties
    value: Optional[float] = attrs.field(default=None)
    minimum: Optional[float] = attrs.field(default=None)
    maximum: Optional[float] = attrs.field(default=None)
    #: the most decimals the field shows (and, on Qt, takes); None: as many as `str` writes
    decimals: Optional[int] = attrs.field(default=None)

    @staticmethod
    def shown_text(value: Optional[float], decimals: Optional[int]) -> str:
        """Show `value` with at most `decimals` decimals, "" for no value.

        The value is rounded, and trailing zeros are left out: with 0 decimals, 36.0 is
        "36", and with 2, 3.14159 is "3.14" and 2.5 is "2.5". Without `decimals`, the
        value shows as `str` writes it, e.g. "36.0". Takes `decimals`, as a renderer
        refreshes it before the view holds it.
        """
        if value is None:
            return ""
        if decimals is None or not math.isfinite(value):
            return str(value)
        text = f"{value:.{decimals}f}"
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        # a negative value rounded to 0 isn't "-0"
        return "0" if text == "-0" else text


@define_view
class FloatInputView(FloatInputMixin, View):
    """A field where the user types a decimal number, for example a length.

    `value` is None while the field is empty.
    """

    _renderer_key = "float_input"


@define_view
class IntInputMixin(_InputView):
    """The fields of a field for a whole number: its `value` and its range."""

    # properties
    value: Optional[int] = attrs.field(default=None)
    minimum: Optional[int] = attrs.field(default=None)
    maximum: Optional[int] = attrs.field(default=None)


@define_view
class IntInputView(IntInputMixin, View):
    """A whole number, e.g. an hour of the day; a spin box where the toolkit has one."""

    _renderer_key = "int_input"


#: how a date is typed and shown when nothing gives it a format: ISO 8601's
ISO_DATE_FORMAT = "yyyy-MM-dd"
#: a date format's parts: its day, month and year (see `DateInputMixin.date_format`)
_DATE_PARTS = {"dd": "day", "MM": "month", "yyyy": "year"}
_DATE_PART_PATTERN = re.compile("|".join(_DATE_PARTS))
#: splits a date format into its parts and the separators between them
_DATE_PART_SPLIT = re.compile(f"({_DATE_PART_PATTERN.pattern})")


def _unstructure_date(value: datetime.date) -> str:
    return value.isoformat()


def _structure_date(value: Any, _type: type) -> datetime.date:
    return datetime.date.fromisoformat(str(value))


def _structure_datetime(value: Any, _type: type) -> datetime.datetime:
    return (
        value
        if isinstance(value, datetime.datetime)
        else datetime.datetime.fromisoformat(str(value))
    )


# registered with their type: cattrs can't read a postponed annotation on 3.9
CONVERTER.register_unstructure_hook(datetime.date, _unstructure_date)
CONVERTER.register_structure_hook(datetime.date, _structure_date)
CONVERTER.register_structure_hook(datetime.datetime, _structure_datetime)


def is_date_format(date_format: str) -> bool:
    """Tell whether `date_format` has a day, a month and a year, each once."""
    parts = _DATE_PART_PATTERN.findall(date_format)
    return sorted(parts) == sorted(_DATE_PARTS)


def format_date(value: datetime.date, date_format: str) -> str:
    """Show `value` as `date_format` says, e.g. "18/10/2026" for "dd/MM/yyyy".

    A format lacking a part, e.g. a catalog's mistake, shows the date as ISO 8601 does.
    """
    if not is_date_format(date_format):
        date_format = ISO_DATE_FORMAT
    texts = {"dd": f"{value.day:02d}", "MM": f"{value.month:02d}", "yyyy": f"{value.year:04d}"}
    return _DATE_PART_PATTERN.sub(lambda part: texts[part.group()], date_format)


def date_hint(placeholder: str, date_format: str) -> str:
    """Get what an empty date field shows: `placeholder`, else the format, as "mm/dd/yyyy"."""
    return placeholder or date_format.lower()


def parse_date(text: str, date_format: str) -> datetime.date:
    """Read a date typed as `date_format` says, or as ISO 8601 (2026-10-18) whatever it is.

    The day and the month may have a single digit ("1/2/2026"), and a separator ending
    the format may be left out ("18.10.2026" for "dd.MM.yyyy."). Raises `ValueError`
    for anything else, or a day the month doesn't have.
    """
    text = text.strip()
    for candidate in dict.fromkeys([date_format, ISO_DATE_FORMAT]):
        if not is_date_format(candidate):
            continue
        pieces = [piece for piece in _DATE_PART_SPLIT.split(candidate) if piece != ""]
        pattern = ""
        for index, piece in enumerate(pieces):
            if piece in _DATE_PARTS:
                digits = r"\d{4}" if piece == "yyyy" else r"\d{1,2}"
                pattern += f"(?P<{_DATE_PARTS[piece]}>{digits})"
            elif index == len(pieces) - 1:
                # a separator ending the format, e.g. Hungarian's dot, may be left out
                pattern += rf"(?:\s*{re.escape(piece.strip())})?"
            else:
                pattern += rf"\s*{re.escape(piece.strip())}\s*"
        matched = re.fullmatch(pattern, text)
        if matched is None:
            continue
        with contextlib.suppress(ValueError):  # a day the month doesn't have
            return datetime.date(*(int(matched[part]) for part in ("year", "month", "day")))
    # the same message for a day the month doesn't have, whatever Python's own says
    msg = f"{text!r} isn't a date as {date_format}"
    raise ValueError(msg)


@define_view
class DateInputMixin(_InputView):
    """A date, typed as `date_format` says or picked from a calendar.

    Not every backend refuses a date typed out of `minimum`/`maximum`: Textual and the web
    mark it or keep it. So validate the date. The calendar offers only the dates in range.
    """

    value: Optional[datetime.date] = attrs.field(default=None)
    minimum: Optional[datetime.date] = attrs.field(default=None)
    maximum: Optional[datetime.date] = attrs.field(default=None)
    #: how the date is typed and shown: its day ``dd``, month ``MM`` and year ``yyyy`` between
    #: separators; a text the catalogs translate, so the main view's language's
    date_format: str = attrs.field(default=T("MM/dd/yyyy"), metadata={UI_TEXT: True})
    #: the calendar's month names, January first, and its days' short names, Monday first
    month_names: list[str] = attrs.field(
        factory=lambda: [
            T("January"),
            T("February"),
            T("March"),
            T("April"),
            T("May"),
            T("June"),
            T("July"),
            T("August"),
            T("September"),
            T("October"),
            T("November"),
            T("December"),
        ],
        metadata={UI_TEXT: True},
    )
    day_names: list[str] = attrs.field(
        factory=lambda: [T("Mo"), T("Tu"), T("We"), T("Th"), T("Fr"), T("Sa"), T("Su")],
        metadata={UI_TEXT: True},
    )
    #: the names of the button opening the calendar, and of its month buttons, as a
    #: screen reader reads them out
    pick_text: str = attrs.field(default=T("Pick a date"), metadata={UI_TEXT: True})
    previous_month_text: str = attrs.field(default=T("Previous month"), metadata={UI_TEXT: True})
    next_month_text: str = attrs.field(default=T("Next month"), metadata={UI_TEXT: True})
    #: the user typed or picked a new date (None once the field is emptied); not
    #: emitted when `value` is set in code
    value_changed: Signal[Optional[datetime.date]] = attrs.Factory(Signal[Optional[datetime.date]])

    def shown_text(self, value: Optional[datetime.date]) -> str:
        """Show `value` as `date_format` says, "" for no date."""
        return "" if value is None else format_date(value, self.date_format)


@define_view
class DateInputView(DateInputMixin, View):
    """A date, e.g. a booking's first day: typed in the main view's language's format."""

    _renderer_key = "date_input"


def is_within_roots(path: Path, roots: Iterable[Path]) -> bool:
    """Whether `path` is one of `roots`, or inside one, once resolved (``~``, ``..``, links)."""
    try:
        try:
            # strict: a loop of links, or a NUL character, raises on every Python and OS
            resolved = path.expanduser().resolve(strict=True)
        except FileNotFoundError:  # a file still to come: the links above it followed
            resolved = path.expanduser().resolve()
        resolved_roots = [root.expanduser().resolve() for root in roots]
    # a loop of links raises RuntimeError before 3.13, a NUL character ValueError
    except (OSError, RuntimeError, ValueError):
        return False
    return any(resolved == root or root in resolved.parents for root in resolved_roots)


@define_view
class PathInputMixin(InputMixin):
    """A path typed in the field or picked with the "…" button beside it.

    What `FilePathInputMixin` and `FolderPathInputMixin` share: `text` holds the path as
    typed, and `path` reads it as a path. With `server_roots`, the web's button lists the
    server's folders in them, and the field holds the path picked there.
    """

    #: the folders of the server that the web's "…" lists, and nothing outside them. On
    #: Qt and Textual, the dialog opens in the first one while the field is empty, and the
    #: user can leave it.
    server_roots: tuple[Path, ...] = attrs.field(default=(), metadata={OMIT: True})
    #: the texts of the web's list of the server's files in `server_roots`
    parent_folder_text: str = attrs.field(default=T("Parent folder"), metadata={UI_TEXT: True})
    cancel_text: str = attrs.field(default=T("Cancel"), metadata={UI_TEXT: True})
    unreadable_folder_text: str = attrs.field(
        default=T("This folder can't be read."), metadata={UI_TEXT: True}
    )
    #: the user picked a path with the "…" button, now in the field; a typed path is
    #: reported as any text is (`text_edited`, `editing_finished`)
    path_picked: Signal[Path] = attrs.Factory(Signal[Path])
    #: whether `path` keeps to `server_roots`: set by the web, which lists only their files
    _keeps_to_roots: bool = attrs.field(
        default=False, init=False, repr=False, eq=False, metadata={OMIT: True}
    )

    @property
    def path(self) -> Optional[Path]:
        """Get the path the field holds, None while it's empty.

        On the web, with `server_roots`, None too for a path typed outside them, symbolic
        links followed: the user can type any path of the server.
        """
        text = self.text.strip()
        if text == "":
            return None
        path = Path(text)
        if (
            self._keeps_to_roots
            and self.server_roots
            and not is_within_roots(path, self.server_roots)
        ):
            return None
        return path


@define_view
class FilePathInputMixin(PathInputMixin):
    """A file's path, typed in the field or picked with the "…" button beside it.

    `text` holds the path as typed, and `path` reads it as a path. On Qt and Textual, the
    button opens the toolkit's file dialog. On the web, the browser's picker uploads the
    file. The field then holds the path of the session's copy, kept until the session
    ends. With `server_roots`, the web's button instead lists the files on the server in
    those folders, and the field holds the path of the file picked there, not a copy.
    With `has_reload`, a reload button beside them emits `reload_clicked`, e.g. to read
    the file again once it changed.
    """

    #: the file types the dialog offers, by name: ``{"CSV": (".csv",)}``; on the web, a
    #: file of another type is refused
    extensions: dict[str, tuple[str, ...]] = attrs.field(
        factory=dict[str, tuple[str, ...]], metadata={OMIT: True}
    )
    has_reload: bool = attrs.field(default=False)
    #: the names of the "…" and reload buttons, as a tooltip and a screen reader show them
    browse_text: str = attrs.field(default=T("Choose a file"), metadata={UI_TEXT: True})
    reload_text: str = attrs.field(default=T("Reload"), metadata={UI_TEXT: True})
    partial_folder_text: str = attrs.field(
        default=T("This folder holds too many items to list them all: type the file's path."),
        metadata={UI_TEXT: True},
    )
    reload_clicked: SignalNoArgs = attrs.Factory(SignalNoArgs)


@define_view
class FolderPathInputMixin(PathInputMixin):
    """A folder's path, typed in the field or picked with the "…" button beside it.

    `text` holds the path as typed, and `path` reads it as a path. On Qt and Textual, the
    button opens the toolkit's folder dialog. The browser can't give the page a folder's
    path: on the web, the user types it, and the field has no button. With
    `server_roots`, the web's button lists the server's folders in them: a folder's item
    shows its folders, and "Choose this folder" puts the folder shown in the field.
    """

    #: the name of the "…" button, as a tooltip and a screen reader show it
    browse_text: str = attrs.field(default=T("Choose a folder"), metadata={UI_TEXT: True})
    #: the button of the web's list that picks the folder it shows
    choose_folder_text: str = attrs.field(default=T("Choose this folder"), metadata={UI_TEXT: True})
    partial_folder_text: str = attrs.field(
        default=T("This folder holds too many items to list them all: type the folder's path."),
        metadata={UI_TEXT: True},
    )


def with_extension(path: Path, extensions: Mapping[str, tuple[str, ...]]) -> Path:
    """Get `path` with the first of `extensions` added, unless it has one of them (any case)."""
    suffixes = [suffix for group in extensions.values() for suffix in group]
    if not suffixes or path.name.lower().endswith(tuple(s.lower() for s in suffixes)):
        return path
    return path.with_name(path.name + suffixes[0])


@define_view
class SavePathInputMixin(PathInputMixin):
    """A path to save a file to, typed in the field or picked with the "…" button beside it.

    `text` holds the path as typed, and `path` reads it as a path, with the first of
    `extensions` added if the name has none of them. On Qt and Textual, the button opens
    the toolkit's save dialog. The browser can't give the page a path: on the web, the
    user types it, and the field has no button. With `server_roots`, the web's button
    lists the server's folders in them and their files of `extensions`: a file's item
    takes its name, and "Save" picks the folder shown with the name typed. With
    `confirms_overwrite`, a file that exists is picked only once the user agrees to
    replace it.
    """

    #: the file types the dialog offers, by name: ``{"PDF": (".pdf",)}``; the first one is
    #: added to a name that has none of them
    extensions: dict[str, tuple[str, ...]] = attrs.field(
        factory=dict[str, tuple[str, ...]], metadata={OMIT: True}
    )
    #: whether the user agrees to replace a file that exists, before it's picked
    confirms_overwrite: bool = attrs.field(default=True, metadata={OMIT: True})
    #: the name of the "…" button, as a tooltip and a screen reader show it
    browse_text: str = attrs.field(default=T("Save as"), metadata={UI_TEXT: True})
    partial_folder_text: str = attrs.field(
        default=T("This folder holds too many items to list them all: type the file's path."),
        metadata={UI_TEXT: True},
    )
    #: the texts of the web's list: the box of the file's name, and the button saving it
    file_name_text: str = attrs.field(default=T("File name"), metadata={UI_TEXT: True})
    save_text: str = attrs.field(default=T("Save"), metadata={UI_TEXT: True})
    #: the question before replacing a file, its ``{name}`` the file's, and its answer
    replace_question_text: str = attrs.field(
        default=T("{name} already exists. Replace it?"), metadata={UI_TEXT: True}
    )
    replace_text: str = attrs.field(default=T("Replace"), metadata={UI_TEXT: True})

    @property
    def path(self) -> Optional[Path]:
        """Get the path the field holds, the first extension added; None while it's empty.

        On the web, with `server_roots`, None too for a path typed outside them.
        """
        path = super().path
        return None if path is None else with_extension(path, self.extensions)


@define_view
class SavePathInputView(SavePathInputMixin, View):
    """A path to save a file to, e.g. a report: typed, or picked from a save dialog."""

    _renderer_key = "save_path_input"


@define_view
class FolderPathInputView(FolderPathInputMixin, View):
    """A folder's path, e.g. where to write results: typed, or picked from a folder dialog."""

    _renderer_key = "folder_path_input"


@define_view
class FilePathInputView(FilePathInputMixin, View):
    """A file's path, e.g. a data file to read: typed, or picked from a file dialog."""

    _renderer_key = "file_path_input"


@define_view
class SliderMixin:
    """The fields of a slider: its `value`, its range and its `step`."""

    def _check_step(self, _attribute: attrs.Attribute[Any], step: int) -> None:
        if step <= 0:
            msg = f"Cannot set {type(self).__name__}.step to {step}: it must be positive."
            raise ValueError(msg)

    #: from `minimum` to `maximum` by `step`; shown at its nearest step (see `position`)
    value: int = attrs.field(default=0)
    minimum: int = attrs.field(default=0)
    #: the last step, if ``maximum - minimum`` is not a whole number of steps, falls short of it
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
    """How a log message reads: an error, a warning or information."""

    ERROR = enum.auto()
    WARNING = enum.auto()
    INFO = enum.auto()


#: A zero-argument check: reads whatever state it needs itself (e.g. `self.text`
#: via a bound method) and returns an error message, or None if it passes.
Validator = Callable[[], Optional[str]]


@define_view
class LogMixin:
    """The fields of a message that a check (`validator`) writes, e.g. an error."""

    log_message: str = attrs.field(default="")
    log_type: LogType = attrs.field(default=LogType.ERROR)
    validator: Optional[Validator] = attrs.field(default=None, repr=False, metadata={OMIT: True})
    #: the row's check ran (`run_validator`), passing or not, e.g. for a form dialog's OK
    checked: SignalNoArgs = attrs.Factory(SignalNoArgs)

    def set_validator(
        self, validator: Validator, *signals: Signal[Unpack[tuple[Any, ...]]]
    ) -> None:
        """Wire `validator` to run against this row whenever any of `signals` fires.

        A failing (non-None) result is pushed into this row's own `log_message`/`log_type`,
        and a passing (None) result clears them. It doesn't run `validator` immediately: call
        `run_validator` afterward for an initial check. E.g. an empty required field should
        already show its error before the first edit.
        """
        self.validator = validator
        for signal in signals:
            signal.connect(self.run_validator)

    def run_validator(self, *_args: Any) -> None:
        """Re-run `validator`, if set, and push its result into the row's own log.

        Takes (and ignores) any positional arguments, so it can be connected directly to
        signals of any arity. E.g. a per-keystroke ``text_edited: Signal[str]``, or a
        no-argument ``editing_finished: SignalNoArgs``.
        """
        if self.validator is None:
            return
        message = self.validator()
        self.log_message = message or ""
        self.log_type = LogType.ERROR if message else LogType.INFO
        self.checked.emit()


@define_view
class LogView(LogMixin, View):
    """A message to the user, for example an error, styled by its `log_type`.

    A new message replaces the last one. For a stream of output, see `ConsoleView`.
    """

    _renderer_key = "log"


@define_view
class LabelMixin:
    """The fields of a label: its `text`."""

    text: str = attrs.field(default="", metadata={UI_TEXT: True})


@define_view
class LabelView(LabelMixin, View):
    """A line of read-only text, for example a caption."""

    _renderer_key = "label"


@define_view
class MarkdownMixin:
    """The fields of a Markdown view: its `text`."""

    #: read-only Markdown, e.g. a help page; its links open in the browser
    text: str = attrs.field(default="", metadata={UI_TEXT: True})


@define_view
class MarkdownView(MarkdownMixin, View):
    """Read-only Markdown text, for example a help page.

    Its links open in the browser. Raw HTML in the text is never read as markup.
    """

    _renderer_key = "markdown"


#: what ends a line, or starts it again ("\r"), in a console's text
_LINE_BREAKS = re.compile(r"(\r\n|\n|\r)")
#: a console's texts, by what they're for: its controls saving the text to a file, copying
#: it to the clipboard, and searching it, with the count of the matches
CONSOLE_TEXTS: Mapping[str, str] = {
    "save": T("Save output"),
    "copy": T("Copy all"),
    "search": T("Search"),
    "matches": T("{current} of {count}"),
    "no_match": T("No match"),
}


def find_in_lines(lines: Sequence[str], query: str) -> list[tuple[int, int, int]]:
    """Find `query` in a console's `lines`, as its search does: plain text, any case.

    Get each match's line, start and end, in order; none for an empty query.
    """
    if query == "":
        return []
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    return [
        (index, match.start(), match.end())
        for index, line in enumerate(lines)
        for match in pattern.finditer(line)
    ]


def follow_match(
    matches: Sequence[tuple[int, int, int]], first_line: int, current: Optional[tuple[int, int]]
) -> int:
    """Get the index of a search's current match among `matches`, after lines came or went.

    `current` is the match shown before, as its line's number, counted from the first line
    ever shown, and its start; `first_line` is the number of `matches`' first line. The
    match is the same one, or the next if it went, else the last; the first without one.
    """
    if current is None or len(matches) == 0:
        return 0
    for index, (line, start, _end) in enumerate(matches):
        if (first_line + line, start) >= current:
            return index
    return len(matches) - 1


@define_view
class ConsoleView(View):
    r"""Plain text that the app adds to as it comes, for example the output of a process.

    `append` adds text: "\n" ends a line, and "\r" starts the line again, as a terminal
    shows a progress line. The view keeps the last `max_lines` lines and drops the oldest.
    Set `text` to replace the text, or call `clear`. The view shows the text as it is,
    never as markup, and scrolls to its end as text comes, unless the user scrolled up.

    Its text is the app's output, not study data: never saved, loaded or reset. For a
    single message to the user, such as an error, see `LogView`. The user saves the text
    to a file (`export_text`), named `export_filename` at first, or copies it all. The
    user searches the text too: plain text, any case, as `find_in_lines` finds it.
    """

    _renderer_key = "console"

    def _trim(self, _attribute: attrs.Attribute[Any], max_lines: int) -> int:
        self._drop_oldest(max_lines)
        return max_lines

    #: the most lines kept, the line being written not counted; the oldest go first
    max_lines: int = attrs.field(
        default=10_000,
        validator=attrs.validators.ge(1),
        on_setattr=[attrs.setters.validate, _trim, notify_renderer],
        metadata={OMIT: True},
    )
    _lines: deque[str] = attrs.field(
        factory=deque[str], init=False, repr=False, eq=False, metadata={OMIT: True}
    )
    _last_line: str = attrs.field(default="", init=False, repr=False, metadata={OMIT: True})
    #: a "\r" ended the text so far: the next text starts the last line again
    _is_returned: bool = attrs.field(default=False, init=False, repr=False, metadata={OMIT: True})
    _line_count: int = attrs.field(default=0, init=False, repr=False, metadata={OMIT: True})
    #: the texts of its controls, by what they're for (see `CONSOLE_TEXTS`)
    texts: dict[str, str] = attrs.field(
        factory=lambda: dict(CONSOLE_TEXTS), metadata={UI_TEXT: True}
    )
    #: the name offered for the file the text is saved to
    export_filename: str = attrs.field(default="output.txt", metadata={OMIT: True})

    @property
    def text(self) -> str:
        """Get the lines kept, then the line being written."""
        return "\n".join([*self._lines, self._last_line])

    @text.setter
    def text(self, text: str) -> None:
        self._lines.clear()
        self._last_line = ""
        self._is_returned = False
        self._add(text)
        self._refresh("text")

    @property
    def lines(self) -> Sequence[str]:
        """Get the lines kept, each ended, the oldest first."""
        return self._lines

    @property
    def last_line(self) -> str:
        """Get the line being written: the text after the last line's end."""
        return self._last_line

    @property
    def line_count(self) -> int:
        """Get how many lines have ended since the view was built, the dropped ones too."""
        return self._line_count

    def append(self, text: str) -> None:
        """Add `text` at the end, e.g. the output a process has written since the last call."""
        self._add(text)
        self._refresh("line_count")

    def clear(self) -> None:
        """Remove the whole text."""
        self.text = ""

    def export_text(self, path: Path) -> None:
        """Write the text to the file `path`, in UTF-8; the status bar says how it went.

        Outside a main view, a failure raises `OSError` instead.
        """
        main_view = None if self._main_view is None else self._main_view()
        try:
            path.write_text(self.text, encoding="utf-8")
        except OSError as error:
            if main_view is None:
                raise
            failed = self.tr("Can't save to {name}: {error}.")
            main_view.status_bar.show_message(failed.format(name=path.name, error=error))
            return
        if main_view is not None:
            done = self.tr("Saved the output to {name}.")
            main_view.status_bar.show_message(done.format(name=path.name))

    def _add(self, text: str) -> None:
        for part in _LINE_BREAKS.split(text):
            if part in ("\n", "\r\n"):
                self._lines.append(self._last_line)
                self._line_count += 1
                self._last_line = ""
                self._is_returned = False
            elif part == "\r":
                # a "\n" may come next, in the next text: the line then ends as it is
                self._is_returned = True
            elif part != "":
                self._last_line = part if self._is_returned else self._last_line + part
                self._is_returned = False
        self._drop_oldest(self.max_lines)

    def _drop_oldest(self, max_lines: int) -> None:
        while len(self._lines) > max_lines:
            self._lines.popleft()

    def _refresh(self, name: str) -> None:
        """Show the change: not a field's, which the renderer would hear by itself."""
        renderer = self.renderer
        if isinstance(renderer, (Renderer, RendererContainer)):
            renderer.refresh_attribute(name, getattr(self, name))


def lines_after(console: ConsoleView, count: int) -> list[str]:
    """Get the lines kept that ended after the first `count`, e.g. the ones not shown yet."""
    lines = console.lines
    new = min(console.line_count - count, len(lines))
    return [lines[index] for index in range(len(lines) - new, len(lines))]


@define_view
class CheckBoxMixin:
    """The fields of a check box: its `text`, its state and `toggled`."""

    def _show_checked(self, _attribute: attrs.Attribute[Any], is_checked: bool) -> bool:
        for view in self._shown:
            view.is_visible = is_checked
        return is_checked

    #: shown next to the box
    text: str = attrs.field(default="", metadata={UI_TEXT: True})
    # its own hooks: the class's would else run, but not these
    is_checked: bool = attrs.field(default=False, on_setattr=[_show_checked, notify_renderer])
    #: the user checked or unchecked the box; not emitted when `is_checked` is set in code
    toggled: Signal[bool] = attrs.Factory(Signal[bool])
    #: the views shown only while the box is checked (see `shows`)
    _shown: list[View] = attrs.field(
        factory=list[View], init=False, repr=False, eq=False, metadata={OMIT: True}
    )

    @property
    def shown_views(self) -> list[View]:
        """Get the views shown only while the box is checked (see `shows`)."""
        return list(self._shown)

    def shows(self, *views: View) -> None:
        """Show `views` only while the box is checked, from now on, e.g. an optional part.

        They follow the box however it changes: as the user clicks it, as code sets
        `is_checked`, and as a study opens or New starts one.
        """
        self._shown.extend(views)
        for view in views:
            view.is_visible = self.is_checked


@define_view
class CheckBoxView(CheckBoxMixin, View):
    """A check box with a text, for an option that is on or off."""

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

    def _check_maximum(self, _attribute: attrs.Attribute[Any], maximum: Optional[int]) -> None:
        if maximum is not None and maximum <= 0:
            msg = f"Cannot set {type(self).__name__}.maximum to {maximum}: it must be positive."
            raise ValueError(msg)

    #: steps done, from 0 to `maximum`; shown clamped to that range (see `clamp`)
    value: int = attrs.field(default=0)
    #: steps the task takes; None while unknown, the bar then only showing that it runs
    maximum: Optional[int] = attrs.field(default=100, validator=[_check_maximum])

    @staticmethod
    def clamp(value: int, maximum: Optional[int]) -> int:
        """Get `value` within the bar's range of `maximum` steps: a count may overshoot.

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


def _to_floats(values: Iterable[float]) -> list[float]:
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


#: the latitude of a Web Mercator map's edges, north and south, in degrees
MAP_LATITUDE_LIMIT = 85.05112878


@attrs.frozen(kw_only=True)
class MapPoint:
    """A geographic position, given as latitude and longitude in degrees.

    Both arguments are keyword-only. Latitude is limited to the range of a Web Mercator map.
    """

    latitude: float = attrs.field(
        converter=float,
        validator=[
            attrs.validators.ge(-MAP_LATITUDE_LIMIT),
            attrs.validators.le(MAP_LATITUDE_LIMIT),
        ],
    )
    longitude: float = attrs.field(
        converter=float, validator=[attrs.validators.ge(-180), attrs.validators.le(180)]
    )


@define_view
class MapView(View):
    """An interactive street map with geographic points drawn over its tiles.

    Qt uses Qt Location, and the web uses deck.gl. Textual does not render this view.
    With ``center=None`` and ``zoom=None``, the map fits its points and follows new data
    and widget sizes. Each explicit value overrides its automatic value. A user pan or
    zoom sets both values; new points then keep that viewport. Reset both to None to fit
    again. The study saves these settings, but not the points or tile settings.
    """

    _renderer_key = "map"
    MAX_ZOOM: ClassVar[int] = 19

    title: str = attrs.field(default="", metadata={UI_TEXT: True})
    #: None fits the points; otherwise the center to keep
    center: Optional[MapPoint] = attrs.field(default=None)
    #: None fits the points; otherwise an OpenStreetMap zoom level from 0 to 19
    zoom: Optional[float] = attrs.field(
        default=None,
        converter=attrs.converters.optional(float),
        validator=attrs.validators.optional(
            attrs.validators.and_(attrs.validators.ge(0), attrs.validators.le(MAX_ZOOM))
        ),
    )
    points: list[MapPoint] = attrs.field(factory=list[MapPoint], metadata={OMIT: True})
    height: int = attrs.field(default=400, validator=attrs.validators.ge(1), metadata={OMIT: True})
    #: False draws only the points, without any network requests for tiles
    tiles: bool = attrs.field(default=True, metadata={OMIT: True})
    #: identifies the native app to the tile server; the web uses the browser's identity
    user_agent: str = attrs.field(
        default="ComposeUI (+https://github.com/ehmoussi/composeui)", metadata={OMIT: True}
    )
    clicked: Signal[float, float] = attrs.Factory(Signal[float, float])
    #: the user panned or zoomed; center and zoom already hold the new viewport
    viewport_changed: SignalNoArgs = attrs.Factory(SignalNoArgs)

    @staticmethod
    def point_bounds(
        points: list[MapPoint], center: Optional[MapPoint]
    ) -> tuple[MapPoint, float, float]:
        """Get the center and spans as fractions of the Web Mercator world.

        With no center override, use the shortest longitude arc across the date line.
        With an override, use spans symmetric around that center.
        """
        if not points:
            return center or MapPoint(latitude=0, longitude=0), 1.0, 1.0
        xs = sorted((point.longitude + 180) / 360 % 1 for point in points)
        ys = [
            0.5 - math.asinh(math.tan(math.radians(point.latitude))) / (2 * math.pi)
            for point in points
        ]
        if center is None:
            # Remove the largest longitude gap so points across the date line stay together.
            gaps = [right - left for left, right in zip(xs, [*xs[1:], xs[0] + 1])]
            gap_index = max(range(len(gaps)), key=gaps.__getitem__)
            span_x = 1 - gaps[gap_index]
            middle_x = (xs[(gap_index + 1) % len(xs)] + span_x / 2) % 1
            middle_y = (min(ys) + max(ys)) / 2
            center = (
                points[0]
                if span_x == 0 and min(ys) == max(ys)
                else MapPoint(
                    latitude=max(
                        -MAP_LATITUDE_LIMIT,
                        min(
                            MAP_LATITUDE_LIMIT,
                            math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * middle_y)))),
                        ),
                    ),
                    longitude=middle_x * 360 - 180,
                )
            )
            return center, span_x, max(ys) - min(ys)
        center_x = (center.longitude + 180) / 360
        center_y = 0.5 - math.asinh(math.tan(math.radians(center.latitude))) / (2 * math.pi)
        return (
            center,
            2 * max(abs((x - center_x + 0.5) % 1 - 0.5) for x in xs),
            2 * max(abs(y - center_y) for y in ys),
        )

    @staticmethod
    def fitted_zoom(span_x: float, span_y: float, width: int, height: int) -> float:
        """Fit Mercator spans in pixel dimensions with 32 pixels of padding on each side.

        Clamp the zoom to 0 through 19; use 12 for a single location.
        """
        if span_x == 0 and span_y == 0:
            return 12.0
        scales = [
            max(1, size - 64) / (256 * span)
            for span, size in ((span_x, width), (span_y, height))
            if span > 0
        ]
        return max(0.0, min(float(MapView.MAX_ZOOM), math.log2(min(scales))))


@attrs.frozen
class Series:
    """A curve of a `ChartView`: its points, x against y, under `name` in the legend.

    A point whose x or y is NaN is not drawn: the curve has a gap there.
    """

    def _check_y(self, _attribute: attrs.Attribute[Any], y: list[float]) -> None:
        if len(y) != len(self.x):
            msg = f"Cannot make the series {self.name!r}: {len(self.x)} x for {len(y)} y."
            raise ValueError(msg)

    def _check_color(self, _attribute: attrs.Attribute[Any], color: Optional[str]) -> None:
        if color is not None and _COLOR_PATTERN.fullmatch(color) is None:
            msg = f"Cannot color the series {self.name!r} {color!r}: give it as #rrggbb."
            raise ValueError(msg)

    def _check_kind(self, _attribute: attrs.Attribute[Any], kind: Optional[ChartKind]) -> None:
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
    #: whether its line holds each value until the next point, in steps, e.g. the jobs
    #: running over time; with `fill`, a step area. Dots are drawn as they are
    step: bool = False

    @classmethod
    def bars(cls, name: str, values: Iterable[float]) -> Series:
        """Make a `BAR` chart's series: a bar per value, in its chart's `categories` in order."""
        heights = list(values)
        return cls(name, list(range(len(heights))), heights)


class LineStyle(enum.Enum):
    """How a reference line is drawn; a terminal draws each solid."""

    SOLID = enum.auto()
    DASHED = enum.auto()
    DOTTED = enum.auto()
    #: dashes and dots in turn
    DASH_DOT = enum.auto()


@attrs.frozen
class ReferenceLine:
    """A line across a `ChartView` at a value, e.g. a capacity ("Max: 40") or now.

    It is no series: not in the legend, but labeled beside itself. The chart's range
    takes it in, so it shows even away from the data.
    """

    def _check_color(self, _attribute: attrs.Attribute[Any], color: Optional[str]) -> None:
        if color is not None and _COLOR_PATTERN.fullmatch(color) is None:
            msg = f"Cannot color the reference line {self.label!r} {color!r}: give it as #rrggbb."
            raise ValueError(msg)

    #: where it crosses its axis: a y, or an x if `vertical` (a bar chart's category index)
    value: float = attrs.field(converter=float)
    #: shown beside it, e.g. "Max: 40"; empty: none
    label: str = ""
    #: whether it stands at an x, across the y axis, rather than lying at a y
    vertical: bool = False
    #: its color, as #rrggbb, the same in every theme; None: the theme's text color
    color: Optional[str] = attrs.field(default=None, validator=[_check_color])
    #: dashed by default: told apart from the series, which are solid
    style: LineStyle = LineStyle.DASHED


#: past it, a float's digits no longer tell the whole number it is (see `ChartView.is_whole`)
_WHOLE_LIMIT = 1e15


@define_view
class ChartView(View):
    """A chart of results, e.g. a quantity against time or a swept dimension.

    The view holds data and labels. Each backend draws it in its own theme's colors and
    fonts, unless a series has a color of its own (`Series.color`). Assign a new `series`
    list to redraw it, e.g. when a job adds points. The user's zoom stays, where the
    backend has one.

    A `BAR` chart draws a group of bars for each of its `categories`, a bar per series. A
    series' x is the index of a category, and its y is the bar's height.

    A log axis (`x_log`, `y_log`) leaves out the values it can't show, those <= 0. A point
    at such an x isn't drawn, and such a y leaves a gap (see `drawn_points`). A reference
    line at such a value isn't drawn either (see `drawn_lines`). So a job's points never
    make the chart fail. A bar chart's x, its categories, is never a log axis.
    """

    _renderer_key = "chart"

    def _check_height(self, _attribute: attrs.Attribute[Any], height: Optional[int]) -> None:
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
    #: lines at values, e.g. a limit, drawn over the series
    reference_lines: list[ReferenceLine] = attrs.field(factory=list[ReferenceLine])
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
    def step_points(xs: list[float], ys: list[float]) -> tuple[list[float], list[float]]:
        """Get the corners of a step line through the points: each y held until the next x.

        A NaN y stays a gap, up to the next point.
        """
        step_xs: list[float] = []
        step_ys: list[float] = []
        for index, (x, y) in enumerate(zip(xs, ys)):
            step_xs.append(x)
            step_ys.append(y)
            if index + 1 < len(xs):
                step_xs.append(xs[index + 1])
                step_ys.append(y)
        return step_xs, step_ys

    @staticmethod
    def held_value(xs: list[float], ys: list[float], x: float) -> Optional[float]:
        """Get the y a step line holds at `x`: the last point's at or before it, x in order.

        None before the first point; NaN in a gap.
        """
        held: Optional[float] = None
        for point_x, point_y in zip(xs, ys):
            if point_x > x:
                break
            held = point_y
        return held

    @staticmethod
    def drawn_lines(lines: list[ReferenceLine], *, x_log: bool, y_log: bool) -> list[ReferenceLine]:
        """Get the reference lines their axes can show: a log axis can't show 0 or less."""
        return [
            line
            for line in lines
            if math.isfinite(line.value)
            and (line.value > 0 or not (x_log if line.vertical else y_log))
        ]

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
    def is_whole(values: Sequence[float]) -> bool:
        """Tell whether `values` are whole numbers, e.g. counts, their gaps (NaN) aside.

        A series of them shows its hovered values as integers, e.g. "45280" rather than
        "4.528e+04"; another with 4 significant digits.
        """
        return all(
            math.isnan(value) or (value.is_integer() and abs(value) < _WHOLE_LIMIT)
            for value in values
        )

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
#: ``bool("False")`` would make true
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
    #: a text's filter typed in ASCII characters alone, which SQLite folds as Python does
    #: (see `SqliteSource`)
    typed_ascii: bool = True

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
            return _text_filter(comparison, text[len(prefix) :].strip())
    if len(text) > 1 and text.endswith("*") and not text.startswith("*"):
        return _text_filter(FilterOperator.STARTS_WITH, text[:-1])
    if len(text) > 1 and text.startswith("*") and not text.endswith("*"):
        return _text_filter(FilterOperator.ENDS_WITH, text[1:])
    return _text_filter(FilterOperator.CONTAINS, text.strip("*"))


def _text_filter(operator: FilterOperator, text: str) -> Filter:
    """Get the filter comparing the cells with `text`, ignoring any case (casefolded)."""
    return Filter(operator, text.casefold(), typed_ascii=text.isascii())


def parse_filter(text: str, field_type: Any = str) -> Filter:
    """Parse a filter's text for a column showing a field of `field_type`.

    In a text column, ignoring case: the cells that contain the text, or as `_parse_text`
    says (``=exact``, ``!=exact``, ``!not``, ``start*``, ``*end``, ``/regex/``). In a
    number or a date column: a comparison (``>20``, ``>=20``, ``<20``, ``<=20``,
    ``!=20``). Or a range (``18..24``, both ends included), or a bare value, which means
    ``=``. In a boolean column: ``true`` or ``false``. In any column: ``=`` alone, for the
    empty cells. Raise `FilterError` when the text doesn't parse.
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


class CellKind(enum.Enum):
    """What the cells of a column show (see `CellWidget`)."""

    #: a check box, checked when the cell's text is "true", ignoring case
    CHECK_BOX = enum.auto()
    #: a combobox of `CellWidget.options`, showing the cell's text
    COMBOBOX = enum.auto()
    #: the cell's text, then a button
    BUTTON = enum.auto()
    #: the cell's text as a link
    LINK = enum.auto()
    #: a file's path, then a "…" button picking one (see `CellWidget.file_path`)
    FILE_PATH = enum.auto()


#: a check box cell's text, by whether it's checked, as `str` writes a boolean
CHECKED_TEXTS: Mapping[bool, str] = {True: "True", False: "False"}


def _to_texts(texts: Iterable[str]) -> tuple[str, ...]:
    return tuple(texts)


def _to_paths(paths: Iterable[Path]) -> tuple[Path, ...]:
    return tuple(paths)


@attrs.frozen
class CellWidget:
    """A widget in each cell of a table's column, by `TableMixin.cell_widgets`.

    A check box and a combobox edit their cell when the column is in `editable_columns`.
    Then `cell_edited` emits the new text, as for a typed edit; a check box's text comes
    from `CHECKED_TEXTS`. Else they only show the cell's text. A button and a link emit
    `cell_clicked`, and the user never types in their cells.

    A file path cell is typed in, and its "…" button picks a file, as `FilePathInputView`'s
    does: the toolkit's file dialog on Qt and Textual, an upload on the web, whose copy the
    session keeps while a cell holds its path. `cell_edited` then emits the file's path.
    Its button is enabled only in an editable column. With `server_roots`, the web lists
    the server's files in them instead, and refuses a path typed outside them: the cell
    keeps its text, and the status bar says why.
    """

    kind: CellKind
    #: a combobox's choices, the texts its cells take
    options: tuple[str, ...] = attrs.field(default=(), converter=_to_texts)
    #: a button's text; a file path button's name, as a tooltip and a screen reader show it
    text: str = "\u2026"
    #: whether a check box column's header has a box checking or unchecking every shown row
    check_all: bool = False
    #: the file types a file path's dialog offers, by name: ``{"CSV": (".csv",)}``; on the
    #: web, a file of another type is refused
    extensions: dict[str, tuple[str, ...]] = attrs.field(
        factory=dict[str, tuple[str, ...]], hash=False
    )
    #: the folders of the server whose files a file path's "…" lists on the web, rather
    #: than uploading a copy; on Qt and Textual, the dialog opens in the first one while
    #: the cell is empty, and the user can leave it (see `FilePathInputMixin.server_roots`)
    server_roots: tuple[Path, ...] = attrs.field(default=(), converter=_to_paths)

    def translated(self, translate: Translate) -> CellWidget:
        """Get it with a button's text translated again, if it's `TranslatedText`."""
        text = translate_again(self.text, translate)
        return self if text is self.text else attrs.evolve(self, text=text)

    @classmethod
    def check_box(cls, *, check_all: bool = False) -> CellWidget:
        return cls(CellKind.CHECK_BOX, check_all=check_all)

    @classmethod
    def combobox(cls, options: Iterable[str] = ()) -> CellWidget:
        return cls(CellKind.COMBOBOX, _to_texts(options))

    @classmethod
    def button(cls, text: str = "\u2026") -> CellWidget:
        return cls(CellKind.BUTTON, text=text)

    @classmethod
    def link(cls) -> CellWidget:
        return cls(CellKind.LINK)

    @classmethod
    def file_path(
        cls,
        extensions: Optional[dict[str, tuple[str, ...]]] = None,
        text: str = T("Choose a file"),
        server_roots: Iterable[Path] = (),
    ) -> CellWidget:
        return cls(
            CellKind.FILE_PATH,
            text=text,
            extensions=dict(extensions or {}),
            server_roots=_to_paths(server_roots),
        )


#: the brightness above which a background takes black text, else white
_LIGHT_BACKGROUND = 0.5


@attrs.frozen
class CellStyle:
    """How a table's cell looks, by `TableMixin.cell_styles`: plain by default."""

    def _check_background(self, _attribute: attrs.Attribute[Any], color: Optional[str]) -> None:
        if color is not None and _COLOR_PATTERN.fullmatch(color) is None:
            msg = f"Cannot color a cell's background {color!r}: give it as #rrggbb."
            raise ValueError(msg)

    def _check_row_span(self, _attribute: attrs.Attribute[Any], row_span: int) -> None:
        if row_span < 1:
            msg = f"Cannot make a cell span {row_span} rows: it spans 1 at least."
            raise ValueError(msg)

    #: its color, as #rrggbb, the same in every theme, e.g. red for NaN; its text is
    #: black or white, whichever reads on it (`text_color`)
    background: Optional[str] = attrs.field(default=None, validator=[_check_background])
    #: False: grayed, and never edited, even in an editable column: its widget is disabled
    is_enabled: bool = True
    #: a mark before its text, e.g. a warning, named by the table's `mark_text`
    mark: Optional[NodeMark] = None
    #: how many rows it covers, its own and those under it, which show nothing in its
    #: column; only while the table shows them right under it, unsorted and unfiltered
    row_span: int = attrs.field(default=1, validator=[_check_row_span])

    @property
    def text_color(self) -> Optional[str]:
        """Get the color of the text on `background`, black or white; None without one."""
        if self.background is None:
            return None
        red, green, blue = (int(self.background[i : i + 2], 16) / 255 for i in (1, 3, 5))
        brightness = 0.299 * red + 0.587 * green + 0.114 * blue
        return "#000000" if brightness > _LIGHT_BACKGROUND else "#ffffff"


#: a cell without a style of its own
PLAIN_CELL = CellStyle()


@attrs.frozen
class HeaderGroup:
    """A header over several columns, on a row above theirs, by `TableMixin.header_groups`.

    E.g. "Coordinates" over "Standard space" and "Physical space".
    """

    text: str
    #: its first column
    column: int
    #: how many columns it covers, from `column` on
    column_count: int

    def translated(self, translate: Translate) -> HeaderGroup:
        """Get it with its text translated again, if it's `TranslatedText`."""
        text = translate_again(self.text, translate)
        return self if text is self.text else attrs.evolve(self, text=text)

    def covers(self, column: int) -> bool:
        return self.column <= column < self.column + self.column_count


#: the milliseconds a table's filter bar waits after the last key typed in its search
#: before it searches: one search for a word, not one per letter (Enter searches at once)
SEARCH_DELAY_MS = 300

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

#: the texts of the web's list of the server's files, for a table's file path cells
FILE_TEXTS: Mapping[str, str] = {
    "parent_folder": T("Parent folder"),
    "cancel": T("Cancel"),
    "unreadable_folder": T("This folder can't be read."),
    "partial_folder": T("This folder holds too many items to list them all: type the file's path."),
    "outside_roots": T("Can't take {path}: it isn't in the folders this column lists."),
}

_ItemT = TypeVar("_ItemT")


def _sorted_by(
    items: Sequence[_ItemT],
    value: Callable[[_ItemT], Any],
    text: Callable[[_ItemT], str],
    *,
    is_text: bool,
    descending: bool,
) -> list[_ItemT]:
    """Sort `items` stably by `value`: text by `str.casefold`, empty cells last.

    Values that don't compare (e.g. a column's type since changed) sort by their `text`.
    """

    def key(item: _ItemT) -> Any:
        cell = value(item)
        if cell is None or cell == "":
            return None
        return cell.casefold() if is_text else cell

    keyed = [(item, key(item)) for item in items]
    present = [(item, cell) for item, cell in keyed if cell is not None]
    try:
        ordered = sorted(present, key=operator.itemgetter(1), reverse=descending)
    except TypeError:
        ordered = sorted(present, key=lambda pair: text(pair[0]).casefold(), reverse=descending)
    return [item for item, _ in ordered] + [item for item, cell in keyed if cell is None]


def _filter_error(tr: Callable[[str], str], text: str, field_type: Any) -> Optional[str]:
    """Say why `text` can't filter a column of `field_type`, translated by `tr`; None if it can."""
    try:
        parse_filter(text, field_type)
    except FilterError as error:
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


def _filter_placeholder(tr: Callable[[str], str], field_type: Any, *, is_pattern: bool) -> str:
    """Hint at what filters a column of `field_type`: a regular expression, or else text."""
    kind = column_kind(field_type)
    if is_pattern and kind is ColumnKind.TEXT:
        return tr("a regular expression, as Room [1-3]")
    if kind is ColumnKind.NUMBER:
        return tr(">=20, 18..24")
    if kind is ColumnKind.DATE:
        return tr(">=2024-01-31")
    if kind is ColumnKind.BOOLEAN:
        return tr("true or false")
    return tr("contains, =exact, start*, !not")


def _filter_chip(texts: Mapping[str, str], header: str, typed: str, *, takes_pattern: bool) -> str:
    """Show a filter as its chip does: its column's header, then the text typed.

    Apart, as a label and its value: the header isn't part of what's typed. A regular
    expression without its slashes: "Room matches Room [1-3]".
    """
    text, is_pattern = split_pattern(typed)
    if is_pattern and takes_pattern:
        chip = texts.get("chip_pattern", "{header} {filter}")
    else:
        chip, text = texts.get("chip", "{header}: {filter}"), typed
    return chip.format(header=header, filter=text)


def _store(view: View, attribute: attrs.Attribute[Any], value: Any) -> None:
    """Set `view`'s attribute, then notify its renderer: it shows the view as it now is."""
    old = getattr(view, attribute.name)
    object.__setattr__(view, attribute.name, value)
    renderer = view.renderer
    if (
        old != value
        and isinstance(renderer, (Renderer, RendererContainer))
        and not renderer.is_updating_state()
    ):
        renderer.refresh_attribute(attribute.name, value)


def _sort_value(value: Any) -> Any:
    """Get the value a field's cell sorts and filters by: an enum by its text, as shown."""
    return _cell_text(value) if isinstance(value, enum.Enum) else value


@define_view
class TableMixin:
    """A table of text: the app formats each cell itself.

    Each row has one cell per header. Assign new lists to update the table: changing a
    list in place doesn't reach the renderer. The user selects rows as `selection_mode`
    allows. `selected_rows` holds their indexes, and `selection_changed` emits them when
    the user changes them. New `rows` keep each selected row selected when they hold it
    exactly once, wherever it moved, and drop it otherwise. `row_activated` emits a row's
    index when the user opens it: a double click on a cell that doesn't edit or click, or
    Enter, which also selects it on Textual and the web.

    The user edits the cells of the columns in `editable_columns` (none by default).
    `cell_edited` emits the row, the column and the new text while `rows` still holds the
    old text. Then the edit replaces its row in `rows`, and keeps the selection. To refuse
    or reformat the edit, or to show what it changed elsewhere, assign `rows` from the
    callback instead. The table shows these rows, and doesn't apply the edit on top. The
    edited row stays selected when they hold it as edited (e.g. renamed, then sorted), or
    else as it was (the edit refused). Raising `EditRefusedError` refuses the edit too,
    and the rows stay as they are, e.g. when the model refused the new text and changed
    nothing. A `RefusedError` caught by `View.refusing` in the callback does the same.

    A column of `cell_widgets` shows a widget in each cell (see `CellWidget`). A check box,
    a combobox or a file path edits the cell. A button or a link emits `cell_clicked` with
    its row and column. A check box column's header can check or uncheck every shown row
    (`check_all`), and each change is emitted as the user's edit.

    The user sorts the rows by a column of `sortable_columns` (`sort_column`, ascending
    unless `sort_descending`). The user also searches the text of `filterable_columns`
    (`search`), and filters each of them (`filters`, the text typed, see `parse_filter`).
    The table shows `shown_rows`, which these compute. The indexes that the table emits or
    takes stay those of `rows`, whatever the order. A search or a filter that hides a
    selected row deselects it, and `selection_changed` emits. New `rows` keep the order,
    the search and the filters.

    Each cell of `cell_styles` looks as its `CellStyle` says: a background color, grayed
    and never edited, a mark, spanning the rows under it. Assign the styles with the rows
    they describe. They are by index in `rows`, so new rows keep the styles of the rows
    that were at their indexes. `header_groups` put a header over several columns, on a
    row above theirs. `row_headers` put a header before each row, e.g. the keys of a small
    key/value table of results.
    """

    def _check_selected_rows(self, _attribute: attrs.Attribute[Any], rows: list[int]) -> None:
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

    def _check_header_groups(
        self, _attribute: attrs.Attribute[Any], groups: list[HeaderGroup]
    ) -> None:
        name = type(self).__name__
        covered: set[int] = set()
        for group in groups:
            columns = set(range(group.column, group.column + group.column_count))
            if group.column < 0 or group.column_count < 1:
                msg = f"Cannot group {name}'s headers under {group.text!r}: it covers no column."
                raise ValueError(msg)
            if len(columns & covered) > 0:
                msg = (
                    f"Cannot group {name}'s headers under {group.text!r}: a column is in two"
                    " groups."
                )
                raise ValueError(msg)
            covered |= columns

    def _check_sort_column(self, _attribute: attrs.Attribute[Any], column: Optional[int]) -> None:
        if column is not None and not self._is_column(column, self.sortable_columns):
            name = type(self).__name__
            msg = f"Cannot sort {name} by column {column}: it isn't one of its sortable columns."
            raise ValueError(msg)

    def _check_filters(self, _attribute: attrs.Attribute[Any], filters: dict[int, str]) -> None:
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
        self, attribute: attrs.Attribute[Any], mode: SelectionMode
    ) -> SelectionMode:
        """Keep only the first selected row when the table comes to select a single one."""
        if mode is SelectionMode.SINGLE and len(self.selected_rows) > 1:
            self.selected_rows = self.selected_rows[:1]
        return cast("SelectionMode", notify_renderer(cast("View", self), attribute, mode))

    def _reconcile_rows(
        self, attribute: attrs.Attribute[Any], rows: list[list[str]]
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

    def _reconcile_sortable(self, attribute: attrs.Attribute[Any], columns: list[int]) -> list[int]:
        """Stop sorting by a column no longer sortable, and notify the renderer."""
        self._store(attribute, columns)
        if self.sort_column is not None and self.sort_column not in columns:
            self.sort_column = None
        return columns

    def _reconcile_filterable(
        self, attribute: attrs.Attribute[Any], columns: list[int]
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

    def _store(self, attribute: attrs.Attribute[Any], value: Any) -> None:
        """Set an attribute, then notify the renderer: it shows the view as it now is."""
        _store(cast("View", self), attribute, value)

    def _restyle(self, attribute: attrs.Attribute[Any], value: Any) -> Any:
        """Set how the table looks, and notify the renderer, which shows it with the rows."""
        self._store(attribute, value)
        return value

    def _reshow(self, attribute: attrs.Attribute[Any], value: Any) -> Any:
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
    #: the user opened a row (a double click, Enter): its index in `rows`
    row_activated: Signal[int] = attrs.Factory(Signal[int])
    editable_columns: list[int] = attrs.Factory(list[int])
    cell_edited: Signal[int, int, str] = attrs.Factory(Signal[int, int, str])
    #: the widget in each cell of a column, by column: the app's setup, not study data
    cell_widgets: dict[int, CellWidget] = attrs.field(
        factory=dict[int, CellWidget], metadata={OMIT: True}
    )
    #: the texts of the web's list of the server's files, for a file path cell with
    #: `server_roots`, by what they're for (see `FILE_TEXTS`)
    file_texts: dict[str, str] = attrs.field(
        factory=lambda: dict(FILE_TEXTS), metadata={UI_TEXT: True}
    )
    #: the user clicked a button or a link cell: its row and its column
    cell_clicked: Signal[int, int] = attrs.Factory(Signal[int, int])
    #: how each cell looks, by its index in `rows` and its column (see `CellStyle`): the
    #: app's to set with the rows, not study data
    cell_styles: dict[tuple[int, int], CellStyle] = attrs.field(
        factory=dict[tuple[int, int], CellStyle], on_setattr=_restyle, metadata={OMIT: True}
    )
    #: headers over several columns, on a row above `headers`
    header_groups: list[HeaderGroup] = attrs.field(
        factory=list[HeaderGroup],
        validator=[_check_header_groups],
        on_setattr=[attrs.setters.validate, _restyle],
        metadata={UI_TEXT: True},
    )
    #: a header before each row, by its index in `rows`; none shown while empty
    row_headers: list[str] = attrs.field(
        factory=list[str], on_setattr=_restyle, metadata={UI_TEXT: True}
    )
    #: each `NodeMark`'s name, for screen readers (web) and as a tooltip (Qt)
    done_text: str = attrs.field(default=T("Done"), metadata={UI_TEXT: True})
    warning_text: str = attrs.field(default=T("Warning"), metadata={UI_TEXT: True})
    error_text: str = attrs.field(default=T("Error"), metadata={UI_TEXT: True})
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
        return _filter_error(cast("View", self).tr, text, self._column_type(column))

    def filter_takes_pattern(self, column: int) -> bool:
        """Tell whether a regular expression filters `column`: a text column."""
        return column_kind(self._column_type(column)) is ColumnKind.TEXT

    def filter_placeholder(self, column: int, *, is_pattern: bool = False) -> str:
        """Hint at what filters `column`, translated: a regular expression, or else text."""
        tr = cast("View", self).tr
        return _filter_placeholder(tr, self._column_type(column), is_pattern=is_pattern)

    def filter_chip(self, column: int) -> str:
        """Show a filter as its chip does: its column's header, then the text typed.

        Apart, as a label and its value: the header isn't part of what's typed. A regular
        expression without its slashes: "Room matches Room [1-3]".
        """
        header = self.headers[column] if column < len(self.headers) else ""
        return _filter_chip(
            self.filter_texts,
            header,
            self.filters[column],
            takes_pattern=self.filter_takes_pattern(column),
        )

    def mark_text(self, mark: NodeMark) -> str:
        """Get the name of `mark` in the main view's language."""
        if mark is NodeMark.DONE:
            return self.done_text
        return self.warning_text if mark is NodeMark.WARNING else self.error_text

    def cell_style(self, row: int, column: int) -> CellStyle:
        """Get how a cell looks, by its index in `rows`: plain unless `cell_styles` say."""
        return self.cell_styles.get((row, column), PLAIN_CELL)

    def is_cell_editable(self, row: int, column: int) -> bool:
        """Tell whether the user edits a cell: in `editable_columns`, and not disabled."""
        return column in self.editable_columns and self.cell_style(row, column).is_enabled

    def header_group(self, column: int) -> Optional[HeaderGroup]:
        """Get the group of `header_groups` over `column`, if any."""
        return next((group for group in self.header_groups if group.covers(column)), None)

    def shown_cell_styles(self) -> dict[tuple[int, int], CellStyle]:
        """Get how the shown cells look, by position in `shown_rows` and column.

        A cell spans the shown rows right under it that follow it in `rows`, up to its
        `row_span`. Its style here says how many rows it spans as shown.
        """
        positions = {row: position for position, row in enumerate(self.shown_rows)}
        styles: dict[tuple[int, int], CellStyle] = {}
        for (row, column), style in self.cell_styles.items():
            position = positions.get(row)
            if position is None or column >= len(self.headers):
                continue
            span = 1
            while (
                span < style.row_span
                and position + span < len(self.shown_rows)
                and self.shown_rows[position + span] == row + span
            ):
                span += 1
            styles[position, column] = attrs.evolve(style, row_span=span)
        return styles

    def is_checked(self, row: int, column: int) -> bool:
        """Tell whether a check box cell is checked: its text is "true", ignoring case."""
        return self._cell_text(row, column).casefold() == "true"

    def column_checked(self, column: int) -> Optional[bool]:
        """Tell whether a check box column's shown cells are all checked, none, or some (None).

        Its disabled cells don't count: the check-all box doesn't change them.
        """
        checked = {
            self.is_checked(row, column)
            for row in self.shown_rows
            if self.cell_style(row, column).is_enabled
        }
        return None if len(checked) > 1 else checked == {True}

    def check_all(self, column: int, *, is_checked: bool) -> None:
        """Check or uncheck a check box column's shown cells, as its header's box does.

        Each cell changing is the user's edit: `cell_edited` emits it, and the edit applies
        unless its callbacks assigned `rows` or refused it. A disabled cell stays as it is.
        """
        text = CHECKED_TEXTS[is_checked]
        for row in list(self.shown_rows):
            if (
                row >= len(self.rows)
                or self.is_checked(row, column) == is_checked
                or not self.cell_style(row, column).is_enabled
            ):
                continue
            rows = self.rows
            self.emit_cell_edited(row, column, text)
            if self.rows is rows:
                # as edited, for the selection to stay on its row
                self._edited_rows = replace_cell(rows, row, column, text)
                try:
                    self.rows = self._edited_rows
                finally:
                    self._edited_rows = None

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
        return _sorted_by(
            rows,
            lambda row: self._cell_value(row, column),
            lambda row: self._cell_text(row, column),
            is_text=column_kind(self._column_type(column)) is ColumnKind.TEXT,
            descending=self.sort_descending,
        )

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
    """A table of text that the app formats cell by cell (see `TableMixin`)."""

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
    #: the widget in each of its cells (see `CellWidget`); a combobox without options, on
    #: an enum field, offers the enum's members
    widget: Optional[CellWidget] = None


def _cell_text(value: Any) -> str:
    """Show a record's field in its cell: as saved, None as an empty cell."""
    return "" if value is None else str(CONVERTER.unstructure(value))


@define_view
class RecordTableView(TableView, Generic[RecordT]):
    """A table of records, `attrs` instances, each a row with a cell per column.

    Build it with its records' type, so a study can save and load them:
    ``child(RecordTableView[Room], columns=[Column("name", T("Room"), editable=True)])``.
    `columns` set the headers and the editable columns. The table formats each field in
    its cell (`str`, None as an empty cell): assign new `records`, not `rows`.

    The user's edit is parsed into the field's type with `CONVERTER`. A cell that doesn't
    parse refuses the edit, and the status bar says why. Else `record_edited` emits the
    old and the new record while `records` still holds the old one. Then the new record
    replaces the old one, unless the callbacks assigned `records` themselves. Refusing the
    edit works as with `cell_edited` (`View.refusing`).
    """

    def _reconcile_columns(
        self, _attribute: attrs.Attribute[Any], columns: list[Column]
    ) -> list[Column]:
        # first: the rows sort and filter by the columns' fields
        object.__setattr__(self, "columns", columns)
        self.headers = [translate_again(column.header, self._tr) for column in columns]
        self.editable_columns = [index for index, column in enumerate(columns) if column.editable]
        self.sortable_columns = [index for index, column in enumerate(columns) if column.sortable]
        self.filterable_columns = [
            index for index, column in enumerate(columns) if column.filterable
        ]
        self.cell_widgets = self._cell_widgets()
        self.rows = [self._cells(record, columns) for record in self.records]
        return columns

    def _cell_widgets(self) -> dict[int, CellWidget]:
        return {
            index: self._cell_widget(index, column.widget)
            for index, column in enumerate(self.columns)
            if column.widget is not None
        }

    def _cell_widget(self, column: int, widget: CellWidget) -> CellWidget:
        """Get a column's widget, translated.

        A combobox without options, on an enum field, offers the enum's members.
        """
        widget = widget.translated(self._tr)
        field_type = self._column_type(column)
        if (
            widget.kind is not CellKind.COMBOBOX
            or len(widget.options) > 0
            or not isinstance(field_type, type)
            or not issubclass(field_type, enum.Enum)
        ):
            return widget
        return attrs.evolve(widget, options=_to_texts(_cell_text(member) for member in field_type))

    def _reconcile_records(
        self, _attribute: attrs.Attribute[Any], records: list[RecordT]
    ) -> list[RecordT]:
        # first: the rows sort and filter by the records' values
        object.__setattr__(self, "records", records)
        # the records' type may be known only since: ``RecordTableView[Room](...)`` sets it
        # once built
        self.cell_widgets = self._cell_widgets()
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

    def column_index(self, field: str) -> int:
        """Get the index of the column showing `field`, e.g. to style its cells.

        Raise `ValueError` when no column shows it.
        """
        for index, column in enumerate(self.columns):
            if column.field == field:
                return index
        msg = f"{type(self).__name__} has no column showing {field!r}."
        raise ValueError(msg)

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
        assert column < len(self.columns)  # a sort's, a filter's or a header's: one of them
        try:
            fields = attrs.fields_dict(attrs.resolve_types(self.record_type))
        except TypeError:  # a table not knowing its records' type: its cells are text
            return str
        field = fields.get(self.columns[column].field)
        return str if field is None else field.type

    def _cell_value(self, row: int, column: int) -> Any:
        # the rows are the records' cells, under their columns
        assert row < len(self.records)
        assert column < len(self.columns)
        return _sort_value(getattr(self.records[row], self.columns[column].field))

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
        assert self._edited_rows is not None  # set by `emit_cell_edited`, its only caller
        # as the table will show it, to keep it selected once the records come back
        self._edited_rows[row] = self._cells(new, self.columns)
        records, rows = self.records, self.rows
        super()._emit_edit(row, column, text)
        self.record_edited.emit(old, new)
        if self.records is records and self.rows is rows:
            self.records = [*records[:row], new, *records[row + 1 :]]


@attrs.frozen
class SourceColumn:
    """A column of a `TableSource`: the values it holds, under `header`."""

    #: the name the source knows the column by, e.g. a record's field or a query's column
    name: str
    header: str
    #: the type of its values, which sets how they sort and filter (see `column_kind`)
    type: Any = str


@attrs.frozen
class Sort:
    """The order of a table's rows: by the values of the column named `column`."""

    column: str
    descending: bool = False


IdT = TypeVar("IdT")


class TableSource(Protocol[IdT]):
    """The rows of a large table, each known by its id, which the table reads in windows.

    The source sorts, searches and filters its rows itself (e.g. in SQL), so that a table
    never reads them all: it asks once for the ids of the rows it shows, in order, then
    for the cells of the rows on screen. `changed` says the rows changed, so the table
    reads them again. An id is a hashable value that stays its row's own while the rows
    change (e.g. a primary key), so that a table's selection stays on its rows.
    `ListSource` is a source of records in memory.
    """

    @property
    def columns(self) -> Sequence[SourceColumn]:
        """Get the columns, in the order a table shows them."""
        ...

    @property
    def changed(self) -> SignalNoArgs:
        """Get the signal emitted once the rows changed."""
        ...

    def count(self) -> int:
        """Get the number of rows, before any search or filter."""
        ...

    def ordered_ids(
        self, sort: Optional[Sort], search: str, filters: Mapping[str, Filter]
    ) -> Sequence[IdT]:
        """Get the ids of the rows that `search` and `filters` pass, in the order of `sort`.

        `search` keeps the rows where the cell of a text column contains it, ignoring case;
        a blank one keeps every row. `filters` holds a `Filter` by column name (see
        `parse_filter`), which a cell passes as `Filter.matches` says. `sort` orders the
        rows by a column's values, text ignoring case, the empty cells last in both orders
        and equal cells in the source's order. Without it, the rows keep the source's
        order. Raise `ValueError` for a column the source doesn't have.
        """
        ...

    def cells(self, ids: Sequence[IdT], columns: Sequence[str]) -> Mapping[IdT, Sequence[Any]]:
        """Get the values of the rows `ids` in `columns`, by id; an id now gone is left out.

        Raise `ValueError` for a column the source doesn't have.
        """
        ...


class ListSource(Generic[RecordT]):
    """A `TableSource` of `attrs` records in memory: a row per record, a column per header.

    Build it with the records' type and the headers by field:
    ``ListSource(Room, {"name": T("Room"), "temperature": T("Temperature")})``. A row's id
    is its index in `records`, or its `id_field` when it has one: then new records keep a
    table's selection on the same records. Assign new `records` to change the rows, which
    emits `changed`. It sorts, searches and filters as a `RecordTableView` does: an enum
    by its text, as shown.
    """

    def __init__(
        self,
        record_type: type[RecordT],
        headers: Mapping[str, str],
        records: Sequence[RecordT] = (),
        *,
        id_field: Optional[str] = None,
    ) -> None:
        fields = attrs.fields_dict(attrs.resolve_types(record_type))
        for name in [*headers, *([] if id_field is None else [id_field])]:
            if name not in fields:
                msg = f"Cannot build a ListSource of {record_type.__name__}: no field {name!r}."
                raise ValueError(msg)
        self._columns = {
            name: SourceColumn(name, header, fields[name].type) for name, header in headers.items()
        }
        self._id_field = id_field
        self._changed = SignalNoArgs()
        self._records: tuple[RecordT, ...] = ()
        #: the records by id, in their order
        self._rows: dict[Hashable, RecordT] = {}
        self._set_records(records)

    @property
    def columns(self) -> Sequence[SourceColumn]:
        return tuple(self._columns.values())

    @property
    def changed(self) -> SignalNoArgs:
        return self._changed

    @property
    def records(self) -> Sequence[RecordT]:
        return self._records

    @records.setter
    def records(self, records: Sequence[RecordT]) -> None:
        self._set_records(records)
        self._changed.emit()

    def count(self) -> int:
        return len(self._records)

    def _set_records(self, records: Sequence[RecordT]) -> None:
        rows = {
            index if self._id_field is None else getattr(record, self._id_field): record
            for index, record in enumerate(records)
        }
        if len(rows) != len(records):
            msg = f"Cannot set the records of a ListSource: two have the same {self._id_field}."
            raise ValueError(msg)
        self._records = tuple(records)
        self._rows = rows

    def ordered_ids(
        self, sort: Optional[Sort], search: str, filters: Mapping[str, Filter]
    ) -> list[Hashable]:
        for name in [*filters, *([] if sort is None else [sort.column])]:
            self._column(name)
        needle = search.strip().casefold()
        searched = [
            column.name
            for column in self._columns.values()
            if column_kind(column.type) is ColumnKind.TEXT
        ]
        # the records once: in a job, the main thread may assign new ones meanwhile
        rows = self._rows
        ids = [
            row_id
            for row_id, record in rows.items()
            if (
                needle == ""
                or any(needle in self._text(record, name).casefold() for name in searched)
            )
            and all(
                row_filter.matches(self._value(record, name), self._text(record, name))
                for name, row_filter in filters.items()
            )
        ]
        if sort is None:
            return ids
        return _sorted_by(
            ids,
            lambda row_id: self._value(rows[row_id], sort.column),
            lambda row_id: self._text(rows[row_id], sort.column),
            is_text=column_kind(self._column(sort.column).type) is ColumnKind.TEXT,
            descending=sort.descending,
        )

    def cells(self, ids: Sequence[Hashable], columns: Sequence[str]) -> dict[Hashable, list[Any]]:
        names = [self._column(name).name for name in columns]
        rows = self._rows  # once, as `ordered_ids` does
        return {
            row_id: [getattr(rows[row_id], name) for name in names]
            for row_id in ids
            if row_id in rows
        }

    def _column(self, name: str) -> SourceColumn:
        column = self._columns.get(name)
        if column is None:
            msg = f"Cannot read the column {name!r} of a ListSource: it has none of this name."
            raise ValueError(msg)
        return column

    @staticmethod
    def _value(record: Any, name: str) -> Any:
        return _sort_value(getattr(record, name))

    @staticmethod
    def _text(record: Any, name: str) -> str:
        return _cell_text(getattr(record, name))


#: the text of a large table: what the web says without rows, and its export's action
SOURCE_TABLE_TEXTS: Mapping[str, str] = {"empty": T("No rows"), "export": T("Export CSV")}

#: the rows a `SourceTableView` reads from its source at once, from a multiple of it on
SOURCE_TABLE_WINDOW = 200
#: the rows whose values a `SourceTableView` keeps, the ones read last
SOURCE_TABLE_CACHE = 1_000
#: the rows from which a `SourceTableView` orders its source's in a job, on Qt and Textual
SOURCE_TABLE_JOB_ROWS = 100_000


def _write_csv(job: Optional[Job[None]], chunks: Iterator[str], path: Path) -> None:
    """Write a large table's CSV, as `SourceTableView.csv_chunks` gives it, in a job or not.

    A job canceled (New, Open, closing the app) stops. Stopped, or failed (e.g. a cell the
    source can't read, a full disk), it leaves no part of the file: none that looks whole.
    """
    is_written = False
    try:
        with path.open("w", encoding="utf-8", newline="") as file:
            for chunk in chunks:
                if job is not None and job.is_canceled:
                    break
                file.write(chunk)
            else:
                is_written = True
    finally:
        if not is_written:
            path.unlink(missing_ok=True)


class _WeakCallback:
    """A view's method connected to a signal, held weakly, and called no more once dropped.

    So a source outliving its table (e.g. the model's) keeps no table alive, and calls
    none that replaced it.
    """

    def __init__(self, method: Callable[[], None]) -> None:
        self._method: Optional[weakref.WeakMethod[Callable[[], None]]] = weakref.WeakMethod(method)

    def drop(self) -> None:
        self._method = None

    def __call__(self) -> None:
        method = None if self._method is None else self._method()
        if method is not None:
            method()


def _ordered_ids(
    _job: Optional[Job[tuple[Optional[int], Sequence[Any]]]],
    source: TableSource[Any],
    sort: Optional[Sort],
    search: str,
    filters: Mapping[str, Filter],
    *,
    is_counting: bool,
) -> tuple[Optional[int], Sequence[Any]]:
    """Ask `source` for its rows' count, if `is_counting`, then the ids of those shown."""
    total = source.count() if is_counting else None
    return total, _compact_ids(source.ordered_ids(sort, search, filters))


def _compact_ids(ids: Sequence[Any]) -> Sequence[Any]:
    """Keep integer ids in an `array` (8 bytes each), any other ids in a list."""
    if all(isinstance(row_id, int) and not isinstance(row_id, bool) for row_id in ids):
        with contextlib.suppress(OverflowError):
            return array.array("q", ids)
    return list(ids)


@define_view
class SourceTableView(View):
    """A large table, whose rows a source keeps and the table reads a window at a time.

    `source` (a `TableSource`) sorts, searches and filters the rows. For each
    `sort_column`, `sort_descending`, `search` and `filters`, the view asks it once for
    the ids of the rows shown, in order, and keeps only these ids (in an `array` when
    they are integers). `rows` gives the cells of the rows at some positions, formatted
    as `column_formats` says. It reads them from the source by windows of
    `SOURCE_TABLE_WINDOW` rows, and keeps the values of the last `SOURCE_TABLE_CACHE` rows.
    The source's `changed` makes it read the order and the cells again. A source of
    `SOURCE_TABLE_JOB_ROWS` rows or more orders them in a job on Qt and Textual
    (`is_ordering`), and `ordered` emits once the rows have their new order.

    The columns are the source's, by name: `sort_column`, the keys of `filters` and of
    `column_formats`. A filter is the text the user typed (see `parse_filter`), and the
    search looks in the text columns. The user selects rows as `selection_mode` allows:
    `selected_ids` holds their ids, and `selection_changed` emits them when the user
    changes them. The ids the app sets are kept as they are. A new order (a search, a
    filter, the source's `changed`) drops the selected rows it hides, and
    `selection_changed` emits. `row_activated` emits a row's id (a double click, Enter).

    A study saves the settings and `selected_ids`, as JSON values (e.g. integers), and
    never the rows or the source: the app gives the view its source again.

    Each backend scrolls the rows, drawing only those around the view. A click on a
    column's header sorts by it (`sort_by`). A click on a row selects it (`select_at`);
    on Qt and Textual, Shift extends the selection (`extend_to`), and a double click or
    Enter activates the row (`activate_at`). Ctrl+C copies the selected rows to the
    clipboard (`selection_text`). Export CSV writes the rows shown to a file
    (`export_csv`): Qt's context menu, Textual's key `e`, the web's link under the rows.

    While `filterable_columns` names columns, a filter bar shows above the rows, as a
    `TableView`'s: a search, "+ Filter" opening an editor of a column and a value, and the
    filters as chips. It counts the rows shown while some are hidden (`count_text`).
    """

    _renderer_key = "source_table"

    def _check_sort_column(self, _attribute: attrs.Attribute[Any], column: Optional[str]) -> None:
        if column is not None:
            self._source_column(column, "sort by")

    def _check_filters(self, _attribute: attrs.Attribute[Any], filters: dict[str, str]) -> None:
        for column, text in filters.items():
            parse_filter(text, self._source_column(column, "filter").type)

    def _check_selected_ids(self, _attribute: attrs.Attribute[Any], ids: list[Any]) -> None:
        name = type(self).__name__
        if self.selection_mode is SelectionMode.SINGLE and len(ids) > 1:
            msg = f"Cannot set {name}.selected_ids to {ids}: the table selects a single row."
            raise ValueError(msg)
        if len(set(ids)) != len(ids):
            msg = f"Cannot set {name}.selected_ids to {ids}: a row is selected twice."
            raise ValueError(msg)

    def _reconcile_source(
        self, attribute: attrs.Attribute[Any], source: Optional[TableSource[Any]]
    ) -> Optional[TableSource[Any]]:
        """Read the new source's rows, and read them again each time they change.

        The renderer shows the new source's columns, e.g. in the filter bar. The filters
        and the sort on columns it doesn't have go: they'd filter and sort nothing, and
        the bar couldn't show them.
        """
        object.__setattr__(self, attribute.name, source)
        if source is not None:
            self._drop_other_columns_settings(source)
        if self._listener is not None:
            # the old source's `changed` keeps it, inert: a signal can't drop one callback
            self._listener.drop()
            self._listener = None
        if source is not None:
            self._listener = _WeakCallback(self._read_source_again)
            source.changed.connect(self._listener)
        self._source_changed()
        renderer = self.renderer
        if isinstance(renderer, (Renderer, RendererContainer)):
            renderer.refresh_attribute(attribute.name, source)
        return source

    def _drop_other_columns_settings(self, source: TableSource[Any]) -> None:
        """Drop the filters and the sort on columns `source` doesn't have, e.g. set before it."""
        names = {column.name for column in source.columns}
        fields = attrs.fields(cast("type[AttrsInstance]", type(self)))
        filters = {name: text for name, text in self.filters.items() if name in names}
        if filters != self.filters:
            _store(self, fields.filters, filters)
        if self.sort_column is not None and self.sort_column not in names:
            _store(self, fields.sort_column, None)
            _store(self, fields.sort_descending, value=False)

    def _reconcile_mode(
        self, attribute: attrs.Attribute[Any], mode: SelectionMode
    ) -> SelectionMode:
        """Keep only the first selected row when the table comes to select a single one."""
        if mode is SelectionMode.SINGLE and len(self.selected_ids) > 1:
            self.selected_ids = self.selected_ids[:1]
        return cast("SelectionMode", notify_renderer(self, attribute, mode))

    def _reorder(self, attribute: attrs.Attribute[Any], value: Any) -> Any:
        """Read the order of the rows as `value` sorts or filters them."""
        if getattr(self, attribute.name) == value:
            return value
        _store(self, attribute, value)
        self._read_order()
        return value

    # first: the settings check their columns against it
    source: Optional[TableSource[Any]] = attrs.field(
        default=None, on_setattr=_reconcile_source, repr=False, metadata={OMIT: True}
    )
    #: the format of each column's values, by column name (e.g. ``".6g"``): `format`'s
    column_formats: dict[str, str] = attrs.field(factory=dict[str, str])
    #: the text the web shows (see `SOURCE_TABLE_TEXTS`)
    texts: dict[str, str] = attrs.field(
        factory=lambda: dict(SOURCE_TABLE_TEXTS), metadata={UI_TEXT: True}
    )
    #: the text of the filter bar, by what it's for (see `FILTER_TEXTS`)
    filter_texts: dict[str, str] = attrs.field(
        factory=lambda: dict(FILTER_TEXTS), metadata={UI_TEXT: True}
    )
    #: the columns the user filters in the table's bar, by name: none hides the bar
    filterable_columns: list[str] = attrs.field(factory=list[str])
    #: the name Export CSV offers for the file; the app's, not a study's
    export_filename: str = attrs.field(default="table.csv", metadata={OMIT: True})
    selection_mode: SelectionMode = attrs.field(
        default=SelectionMode.SINGLE, on_setattr=_reconcile_mode
    )
    sort_column: Optional[str] = attrs.field(
        default=None,
        validator=[_check_sort_column],
        on_setattr=[attrs.setters.validate, _reorder],
    )
    sort_descending: bool = attrs.field(default=False, on_setattr=_reorder)
    #: text the shown rows contain in a text column, ignoring case
    search: str = attrs.field(default="", on_setattr=_reorder)
    #: the filters by column name, as typed (see `parse_filter`)
    filters: dict[str, str] = attrs.field(
        factory=dict[str, str],
        validator=[_check_filters],
        on_setattr=[attrs.setters.validate, _reorder],
    )

    def _reconcile_selected(self, attribute: attrs.Attribute[Any], ids: list[Any]) -> list[Any]:
        """Keep the selected ids in a set too, for `is_selected`, and notify the renderer."""
        object.__setattr__(self, "_selected", set(ids))
        return cast("list[Any]", notify_renderer(self, attribute, ids))

    # after the settings: loading saved state selects the rows once in their order
    selected_ids: list[Any] = attrs.field(
        factory=list,
        validator=[_check_selected_ids],
        on_setattr=[attrs.setters.validate, _reconcile_selected],
    )
    # signals
    selection_changed: Signal[list[Any]] = attrs.Factory(Signal[list[Any]])
    row_activated: Signal[Any] = attrs.Factory(Signal[Any])
    #: the rows shown have a new order, e.g. to show `row_count`: a sort, a search, a
    #: filter, the source's change
    ordered: SignalNoArgs = attrs.Factory(SignalNoArgs)
    #: the ids of the rows shown, in order
    _order: Sequence[Any] = attrs.field(factory=list, init=False, repr=False, metadata={OMIT: True})
    #: the values of the rows read last, by id, the oldest first
    _cache: OrderedDict[Any, Sequence[Any]] = attrs.field(
        factory=OrderedDict, init=False, repr=False, metadata={OMIT: True}
    )
    #: `selected_ids`, as a set
    _selected: set[Any] = attrs.field(factory=set, init=False, repr=False, metadata={OMIT: True})
    #: the number of the source's rows, before any search or filter
    _total: int = attrs.field(default=0, init=False, repr=False, metadata={OMIT: True})
    #: the position the user selected last, where a range they extend starts
    _anchor: Optional[int] = attrs.field(
        default=None, init=False, repr=False, metadata={OMIT: True}
    )
    #: the source whose ids `_order` holds
    _order_source: Optional[TableSource[Any]] = attrs.field(
        default=None, init=False, repr=False, eq=False, metadata={OMIT: True}
    )
    #: a job is ordering the rows
    _ordering: bool = attrs.field(default=False, init=False, repr=False, metadata={OMIT: True})
    #: the main view's jobs' `running_changed` is connected
    _watches_jobs: bool = attrs.field(default=False, init=False, repr=False, metadata={OMIT: True})
    #: connected to the source's `changed`, until the source is replaced
    _listener: Optional[_WeakCallback] = attrs.field(
        default=None, init=False, repr=False, eq=False, metadata={OMIT: True}
    )
    #: the requests for the order: each new one makes the orders asked before outdated
    _order_request: int = attrs.field(default=0, init=False, repr=False, metadata={OMIT: True})
    #: the latest request waits for the job running to be over
    _order_pending: bool = attrs.field(default=False, init=False, repr=False, metadata={OMIT: True})
    #: the source changed since `_total` counted its rows: the next order counts them
    _recount: bool = attrs.field(default=False, init=False, repr=False, metadata={OMIT: True})

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self._selected = set(self.selected_ids)
        self.source = self.source

    @property
    def headers(self) -> list[str]:
        """Get the headers of the source's columns, in its order."""
        if self.source is None:
            return []
        return [translate_again(column.header, self._tr) for column in self.source.columns]

    @property
    def column_names(self) -> list[str]:
        """Get the names of the source's columns, in its order."""
        return [] if self.source is None else [column.name for column in self.source.columns]

    @property
    def row_count(self) -> int:
        """Get the number of rows shown: the rows the search and the filters pass."""
        return len(self._order)

    def sort_by(self, column: str) -> None:
        """Sort as a click on the column's header does: ascending, descending, then not.

        The source orders the rows once, for the column and the direction together.
        """
        fields = attrs.fields(cast("type[AttrsInstance]", type(self)))
        self._check_sort_column(fields.sort_column, column)
        if self.sort_column != column:
            settings: tuple[Optional[str], bool] = (column, False)
        elif not self.sort_descending:
            settings = (column, True)
        else:
            settings = (None, False)
        for attribute, value in zip((fields.sort_column, fields.sort_descending), settings):
            _store(self, attribute, value)
        self._read_order()

    @property
    def count_text(self) -> str:
        """Count the rows shown, while the search or the filters hide some: else "".

        E.g. "1,234 of 1,000,000", in `filter_texts`' words.
        """
        if self.row_count == self._total or self._order_source is not self.source:
            return ""  # all shown, or the source's rows not ordered yet
        count = self.filter_texts.get("count", "")
        return count.format(shown=f"{self.row_count:,}", total=f"{self._total:,}")

    def filter_error(self, column: str, text: str) -> Optional[str]:
        """Say why `text` can't filter `column`, translated; None if it can."""
        return _filter_error(self.tr, text, self._source_column(column, "filter").type)

    def filter_takes_pattern(self, column: str) -> bool:
        """Tell whether a regular expression filters `column`: a text column."""
        return column_kind(self._source_column(column, "filter").type) is ColumnKind.TEXT

    def filter_placeholder(self, column: str, *, is_pattern: bool = False) -> str:
        """Hint at what filters `column`, translated: a regular expression, or else text."""
        field_type = self._source_column(column, "filter").type
        return _filter_placeholder(self.tr, field_type, is_pattern=is_pattern)

    def filter_chip(self, column: str) -> str:
        """Show the filter of `column` as its chip does: its header, then the text typed."""
        header = self.header(column)
        takes_pattern = self.filter_takes_pattern(column)
        return _filter_chip(
            self.filter_texts, header, self.filters[column], takes_pattern=takes_pattern
        )

    def header(self, column: str) -> str:
        """Get the header of the source's column `column`, translated."""
        names = self.column_names
        return self.headers[names.index(column)] if column in names else column

    def selection_text(self) -> str:
        """Get the selected rows as Ctrl+C copies them: tab-separated text, a line per row.

        The rows in their order, the cells as the table shows them, without the headers,
        as a spreadsheet takes them. A tab or a line break in a cell is a space. The rows
        are read from the source a window at a time, outside the table's cache.
        """
        if self.source is None or len(self._selected) == 0:
            return ""
        selected = self._selected
        ids = [row_id for row_id in self._order if row_id in selected]
        columns = self.source.columns
        names = [column.name for column in columns]
        lines: list[str] = []
        for start in range(0, len(ids), SOURCE_TABLE_WINDOW):
            window = ids[start : start + SOURCE_TABLE_WINDOW]
            values = self.source.cells(window, names)
            for row_id in window:
                cells = self._cells(columns, values.get(row_id, ()))
                lines.append("\t".join(" ".join(cell.split()) for cell in cells))
        return "\n".join(lines)

    def csv_chunks(self) -> Iterator[str]:
        """Get the rows shown as CSV, in pieces: the headers, then a window of rows each.

        The rows in their order, each value in full, not as `column_formats` shows it:
        None as an empty cell, an enum by its value, a date as ISO. The order is the one
        shown at the call: a new order, while the pieces are read, changes none of them.
        The rows are read from the source a window at a time, outside the table's cache.
        """
        source, order = self.source, self._order
        if source is None:
            return iter(())
        names = [column.name for column in source.columns]
        headers = self.headers

        def chunks() -> Iterator[str]:
            buffer = io.StringIO()
            writer = csv.writer(buffer)
            writer.writerow(headers)
            yield buffer.getvalue()
            for start in range(0, len(order), SOURCE_TABLE_WINDOW):
                buffer.seek(0)
                buffer.truncate()
                window = order[start : start + SOURCE_TABLE_WINDOW]
                values = source.cells(window, names)
                writer.writerows(
                    [_cell_text(value) for value in values.get(row_id, [None] * len(names))]
                    for row_id in window
                )
                yield buffer.getvalue()

        return chunks()

    def export_csv(self, path: Path) -> None:
        """Write the rows shown to the CSV file `path`, in UTF-8, as `csv_chunks` gives them.

        In an app, a job writes them, the app staying responsive, and the status bar says
        when it's done, or why it failed. Else they are written before the call returns.
        """
        chunks, count = self.csv_chunks(), self.row_count
        main_view = None if self._main_view is None else self._main_view()
        if main_view is None:
            _write_csv(None, chunks, path)
            return
        job = main_view.jobs.start(_write_csv, chunks, path)
        done = self.tr("Exported {count} rows to {name}.")
        failed = self.tr("Can't export to {name}: {error}.")
        show = main_view.status_bar.show_message
        job.finished.connect(lambda _: show(done.format(count=f"{count:,}", name=path.name)))
        job.failed.connect(lambda error: show(failed.format(name=path.name, error=error)))

    def is_selected(self, row_id: Any) -> bool:
        """Tell whether the row `row_id` is selected."""
        return row_id in self._selected

    def select_at(self, position: int) -> None:
        """Select the row at `position` as the user's click does, and say so if it changed.

        One row at most selects it; any number of rows add it, or remove it if selected.
        """
        ids = self.ids(position, position + 1)
        if len(ids) == 0:
            return
        self._anchor = position
        (row_id,) = ids
        if self.selection_mode is SelectionMode.SINGLE:
            selected = [row_id]
        elif row_id in self._selected:
            selected = [selected_id for selected_id in self.selected_ids if selected_id != row_id]
        else:
            selected = [*self.selected_ids, row_id]
        self._select(selected)

    def extend_to(self, position: int) -> None:
        """Add the rows from the one selected last to `position`, as a Shift+click does.

        One row at most, or none selected last: as `select_at`.
        """
        if self.selection_mode is SelectionMode.SINGLE or self._anchor is None:
            self.select_at(position)
            return
        first, last = sorted((self._anchor, position))
        added = [row_id for row_id in self.ids(first, last + 1) if row_id not in self._selected]
        self._select([*self.selected_ids, *added])

    def activate_at(self, position: int) -> None:
        """Emit `row_activated` with the id of the row at `position`, as a double click."""
        ids = self.ids(position, position + 1)
        if len(ids) > 0:
            self.row_activated.emit(ids[0])

    def _select(self, selected: list[Any]) -> None:
        if selected != self.selected_ids:
            self.selected_ids = selected
            self.selection_changed.emit(selected)

    def ids(self, start: int, stop: int) -> list[Any]:
        """Get the ids of the rows shown from position `start` to `stop` (excluded)."""
        return list(self._order[max(start, 0) : max(stop, 0)])

    def rows(self, start: int, stop: int) -> list[tuple[Any, list[str]]]:
        """Get the id and the formatted cells of the rows shown from `start` to `stop`.

        A row gone from the source since the order was read has empty cells, until its
        `changed` reads the order again.
        """
        ids = self.ids(start, stop)
        if self.source is None or len(ids) == 0:
            return []
        for row_id in ids:  # the latest read: the windows read next don't evict them
            if row_id in self._cache:
                self._cache.move_to_end(row_id)
        if any(row_id not in self._cache for row_id in ids):
            self._read_windows(self.source, max(start, 0), max(start, 0) + len(ids))
        columns = self.source.columns
        empty = [""] * len(columns)
        rows: list[tuple[Any, list[str]]] = []
        for row_id in ids:
            values = self._cache.get(row_id)
            cells = empty if values is None else self._cells(columns, values)
            rows.append((row_id, cells))
        return rows

    def _read_windows(self, source: TableSource[Any], start: int, stop: int) -> None:
        """Read the values of the windows of rows from `start` to `stop` into the cache."""
        first = start - start % SOURCE_TABLE_WINDOW
        last = min(-(-stop // SOURCE_TABLE_WINDOW) * SOURCE_TABLE_WINDOW, len(self._order))
        ids = [row_id for row_id in self._order[first:last] if row_id not in self._cache]
        values = source.cells(ids, [column.name for column in source.columns])
        for row_id in ids:
            # a row gone: its cells are empty until the source says it changed
            self._cache[row_id] = values.get(row_id, ())
        while len(self._cache) > max(SOURCE_TABLE_CACHE, last - first):
            self._cache.popitem(last=False)

    def _cells(self, columns: Sequence[SourceColumn], values: Sequence[Any]) -> list[str]:
        if len(values) == 0:  # gone
            return [""] * len(columns)
        return [
            self._format(value, self.column_formats.get(column.name, ""))
            for column, value in zip(columns, values)
        ]

    @staticmethod
    def _format(value: Any, spec: str) -> str:
        """Format a cell's value: None as an empty cell, an enum by its text, else by `spec`."""
        if value is None or spec == "" or isinstance(value, enum.Enum):
            return _cell_text(value)
        try:
            return format(value, spec)
        except (TypeError, ValueError):  # a format for another type of value
            return _cell_text(value)

    def _source_changed(self) -> None:
        """Count the rows of the source, new or changed, then order them."""
        source = self.source
        self._cache.clear()
        if source is None:
            self._total, self._recount = 0, False
        elif source is not self._order_source or self._ordering_jobs() is None:
            # a new source: its count says whether a job orders its rows
            self._total, self._recount = source.count(), False
        else:
            self._recount = True  # in the ordering job, the rows' count costing a query too
        if source is not self._order_source and len(self._order) > 0:
            # the old source's ids: no row until the new source's order, selected ones kept
            self._order, self._order_source = [], None
            self._refresh_order()
        self._read_order()

    @property
    def total(self) -> int:
        """Get the number of the source's rows, before the search and the filters."""
        return self._total

    @property
    def is_ordering(self) -> bool:
        """Tell whether a job is ordering the rows, the old order shown meanwhile."""
        return self._ordering

    def _read_order(self) -> None:
        """Ask the source for the ids of the rows shown, in their order, then show them.

        A source of `SOURCE_TABLE_JOB_ROWS` rows or more, in an app whose window the main
        thread draws (Qt, Textual), orders them in a job, the app staying responsive
        meanwhile (`is_ordering`). One job at a time: the settings changed while it runs
        order the rows again once it's over, its order dropped.
        """
        # any order asked before, a job's still running, is outdated
        self._order_request += 1
        self._order_pending = False
        source = self.source
        jobs = self._ordering_jobs()
        if source is None:
            self._show_order(None, 0, [])
        elif jobs is None:
            settings = self._order_settings(source)
            order = _ordered_ids(None, source, *settings, is_counting=self._recount)
            self._show_order(source, *order)
        elif self._ordering:
            self._order_pending = True
        else:
            request = self._order_request
            self._set_ordering(is_ordering=True)
            settings = self._order_settings(source)
            job = jobs.start(_ordered_ids, source, *settings, is_counting=self._recount)
            job.finished.connect(lambda order: self._ordered(request, order))
            job.failed.connect(lambda _error: self._ordered(request, None))

    def _ordering_jobs(self) -> Optional[Jobs]:
        """Get the jobs to order the rows in, or None to order them on the main thread."""
        main_view = None if self._main_view is None else self._main_view()
        if main_view is None or self._total < SOURCE_TABLE_JOB_ROWS:
            return None
        renderer = main_view.renderer
        if not isinstance(renderer, MainRenderer) or not renderer.draws_on_main_thread:
            return None
        if not self._watches_jobs:
            # New and Open drop the jobs, the ordering's too: its order never comes
            main_view.jobs.running_changed.connect(self._jobs_running)
            self._watches_jobs = True
        return main_view.jobs

    def _jobs_running(self, is_running: bool) -> None:
        if not is_running and self._ordering:  # dropped
            self._set_ordering(is_ordering=False)
            self._read_order()

    def _ordered(self, request: int, order: Optional[tuple[Optional[int], Sequence[Any]]]) -> None:
        """Show the order a job got for `request`, unless a newer one was asked meanwhile.

        A newer request waiting for the job orders now; one answered at once (e.g. the
        source got smaller) is shown already: the job's order is dropped.
        """
        self._set_ordering(is_ordering=False)
        if request == self._order_request:
            if order is not None:  # else it failed, logged: the old order stays
                self._show_order(self.source, *order)
        elif self._order_pending:
            self._read_order()

    def _set_ordering(self, *, is_ordering: bool) -> None:
        self._ordering = is_ordering
        renderer = self.renderer
        if isinstance(renderer, (Renderer, RendererContainer)):
            renderer.refresh_attribute("is_ordering", is_ordering)

    def _refresh_order(self) -> None:
        """Give the renderer the new `row_count`: it shows the rows from their new order."""
        self._anchor = None  # a position of the old order
        renderer = self.renderer
        if isinstance(renderer, (Renderer, RendererContainer)):
            renderer.refresh_attribute("row_count", self.row_count)

    def _read_source_again(self) -> None:
        self._source_changed()

    def _show_order(
        self,
        source: Optional[TableSource[Any]],
        total: Optional[int],
        ids: Sequence[Any],
    ) -> None:
        """Show the rows `ids`, in order, drop the selected ones it hides, emit `ordered`.

        `total` is the source's rows' count, if counted with the order.
        """
        if total is not None:
            self._total, self._recount = total, False
        self._order, self._order_source = ids, source
        self._refresh_order()
        self.ordered.emit()
        if len(self.selected_ids) > 0:
            selected = self._selected
            shown = {row_id for row_id in self._order if row_id in selected}
            kept = [row_id for row_id in self.selected_ids if row_id in shown]
            if kept != self.selected_ids:
                self.selected_ids = kept
                self.selection_changed.emit(kept)

    def _order_settings(
        self, source: TableSource[Any]
    ) -> tuple[Optional[Sort], str, dict[str, Filter]]:
        """Get what `source` orders the rows by: the sort, the search, the filters parsed."""
        columns = {column.name: column for column in source.columns}
        filters: dict[str, Filter] = {}
        for name, text in self.filters.items():
            # a filter its column no longer takes (e.g. a new source) filters nothing
            with contextlib.suppress(FilterError):
                if name in columns:
                    filters[name] = parse_filter(text, columns[name].type)
        sort = None
        if self.sort_column is not None and self.sort_column in columns:
            sort = Sort(self.sort_column, descending=self.sort_descending)
        return sort, self.search, filters

    def _source_column(self, name: str, action: str) -> SourceColumn:
        """Get the source's column `name`, for `action`; any column without a source yet."""
        if self.source is None:
            return SourceColumn(name, name)
        column = next((column for column in self.source.columns if column.name == name), None)
        if column is None:
            msg = f"Cannot {action} {type(self).__name__}'s column {name!r}: its source has none."
            raise ValueError(msg)
        return column


class SourceTableLike(Protocol):
    """What `SourceTableByPosition` reads and sets of a `SourceTableView`."""

    search: str
    filters: dict[str, str]
    sort_column: Optional[str]
    sort_descending: bool

    @property
    def headers(self) -> list[str]: ...
    @property
    def column_names(self) -> list[str]: ...
    @property
    def filter_texts(self) -> dict[str, str]: ...
    @property
    def filterable_columns(self) -> list[str]: ...
    def header(self, column: str) -> str: ...
    def filter_error(self, column: str, text: str) -> Optional[str]: ...
    def filter_takes_pattern(self, column: str) -> bool: ...
    def filter_placeholder(self, column: str, *, is_pattern: bool = False) -> str: ...
    def filter_chip(self, column: str) -> str: ...
    def sort_by(self, column: str) -> None: ...
    def select_at(self, position: int) -> None: ...
    def extend_to(self, position: int) -> None: ...


class SourceTableByPosition:
    """A large table as a backend's widgets know it: its columns by their positions.

    A `SourceTableView` knows its columns by name, and the widgets (a header, a filter bar,
    as a `TableView`'s) by position in its source. The renderers of every backend read
    and set the view through it, so the names map to positions in one place.
    """

    def __init__(self, view: SourceTableLike) -> None:
        self._view = view

    @property
    def headers(self) -> list[str]:
        return self._view.headers

    @property
    def filter_texts(self) -> dict[str, str]:
        return self._view.filter_texts

    @property
    def search(self) -> str:
        return self._view.search

    @search.setter
    def search(self, text: str) -> None:
        self._view.search = text

    @property
    def filters(self) -> dict[int, str]:
        names = self._view.column_names
        return {
            names.index(name): text for name, text in self._view.filters.items() if name in names
        }

    @filters.setter
    def filters(self, filters: dict[int, str]) -> None:
        names = self._view.column_names
        self._view.filters = {names[column]: text for column, text in filters.items()}

    @property
    def filterable_columns(self) -> list[int]:
        return [column for column, _header in self.bar_columns(self._view.filterable_columns)]

    @property
    def sort(self) -> Optional[tuple[int, bool]]:
        """Get the sorted column's position and whether it's descending; None if none."""
        names = self._view.column_names
        if self._view.sort_column not in names:
            return None
        return names.index(self._view.sort_column), self._view.sort_descending

    def bar_columns(self, filterable_columns: list[str]) -> list[tuple[int, str]]:
        """Get the position and the header of each of `filterable_columns`, as a bar lists them.

        Takes the names, as a renderer refreshes them before the view holds them.
        """
        names = self._view.column_names
        return [
            (names.index(name), self._view.header(name))
            for name in names
            if name in filterable_columns
        ]

    def chips(self, filters: dict[str, str]) -> list[tuple[int, str, str, str]]:
        """Get each of `filters` as a bar's chip, by name: as `bar_columns` takes them.

        Each its position, the chip's text, the text typed and the header.
        """
        names = self._view.column_names
        return [
            (
                names.index(name),
                self._view.filter_chip(name),
                filters[name],
                self._view.header(name),
            )
            for name in names
            if name in filters
        ]

    def filter_error(self, column: int, text: str) -> Optional[str]:
        return self._view.filter_error(self._name(column), text)

    def filter_takes_pattern(self, column: int) -> bool:
        return self._view.filter_takes_pattern(self._name(column))

    def filter_placeholder(self, column: int, *, is_pattern: bool = False) -> str:
        return self._view.filter_placeholder(self._name(column), is_pattern=is_pattern)

    def filter_chip(self, column: int) -> str:
        return self._view.filter_chip(self._name(column))

    def add_filter(self, column: int, text: str) -> None:
        """Filter the column at `column` with `text`, as the bar's Add does."""
        self.filters = {**self.filters, column: text}

    def remove_filter(self, column: int) -> None:
        """Stop filtering the column at `column`, as its chip's remove button does."""
        self.filters = {other: text for other, text in self.filters.items() if other != column}

    def clear_filters(self) -> None:
        self._view.filters = {}

    def sort_by(self, column: int) -> None:
        """Sort by the column at `column`, as a click on its header does."""
        names = self._view.column_names
        assert column < len(names)  # a header's
        self._view.sort_by(names[column])

    def select(self, position: int, *, is_extended: bool) -> None:
        """Select the row at `position`, as a click does: extended to it with Shift."""
        if is_extended:
            self._view.extend_to(position)
        else:
            self._view.select_at(position)

    def _name(self, column: int) -> str:
        return self._view.column_names[column]


TValue = TypeVar("TValue")


@define_view
class ValuesGroupMixin(Generic[TValue]):
    """The fields of one choice among `values`: the choices by label, and the `value` selected.

    `value` is None, or one of `values`; new `values` without it clear it. None selects
    nothing, unless None is one of `values`, such as a filter's "All": then it selects that
    choice, shown and saved as any other.
    """

    def _check_value(self, _attribute: attrs.Attribute[Any], value: Optional[TValue]) -> None:
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
        self, attribute: attrs.Attribute[Any], values: dict[str, TValue]
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
        """Serialize `value` as its key: its label could be in another language on load.

        None for nothing selected: a None `value` that isn't one of `values`.
        """
        # one of `values`, as its validator keeps it, unless it's None
        return next(
            (
                self._value_key(index, candidate)
                for index, candidate in enumerate(self.values.values())
                if candidate == self.value
            ),
            None,
        )

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
    """A group of radio buttons, for one choice among a few `values`."""

    _renderer_key = "radio_group"


@define_view
class ComboBoxView(ValuesGroupMixin[TValue], View):
    """A drop-down list, for one choice among `values`."""

    _renderer_key = "combobox"


@define_view
class FormRowView(LogMixin, View):
    """A row of a form: a field, and the message of its check under it."""

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

    @classmethod
    def _renderer_keys(cls) -> tuple[str, ...]:
        return () if cls._field_renderer_key is None else (cls._field_renderer_key, "log")

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
    """A row of a form with a label before its field, and a help button if it has `help`."""

    label: str = attrs.field(default="", metadata={UI_TEXT: True})
    #: what to enter in the field, shown by a "?" button beside the label (a hint on Textual)
    help: str = attrs.field(default="", metadata={UI_TEXT: True})
    #: the "?" button's name for screen readers
    help_button_text: str = attrs.field(default=T("Help"), metadata={UI_TEXT: True})

    @classmethod
    def _renderer_keys(cls) -> tuple[str, ...]:
        keys = super()._renderer_keys()
        return (*keys, "form_label") if len(keys) > 0 else ()

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
    """A row of a form with a field for one line of text, without a label."""

    _field_renderer_key = "input"


@define_view
class LabelRowInputView(FormLabelRowView, InputMixin):
    """A row of a form with a label and a field for one line of text."""

    _field_renderer_key = "input"


@define_view
class RowFloatInputView(FormRowView, FloatInputMixin):
    """A row of a form with a field for a decimal number, without a label."""

    _field_renderer_key = "float_input"


@define_view
class LabelRowFloatInputView(FormLabelRowView, FloatInputMixin):
    """A row of a form with a label and a field for a decimal number."""

    _field_renderer_key = "float_input"


@define_view
class RowIntInputView(FormRowView, IntInputMixin):
    """A row of a form with a field for a whole number, without a label."""

    _field_renderer_key = "int_input"


@define_view
class LabelRowIntInputView(FormLabelRowView, IntInputMixin):
    """A row of a form with a label and a field for a whole number."""

    _field_renderer_key = "int_input"


@define_view
class RowDateInputView(FormRowView, DateInputMixin):
    """A row of a form with a date field, without a label."""

    _field_renderer_key = "date_input"


@define_view
class LabelRowDateInputView(FormLabelRowView, DateInputMixin):
    """A row of a form with a label and a date field."""

    _field_renderer_key = "date_input"


@define_view
class RowFilePathInputView(FormRowView, FilePathInputMixin):
    """A row of a form with a file path field, without a label."""

    _field_renderer_key = "file_path_input"


@define_view
class LabelRowFilePathInputView(FormLabelRowView, FilePathInputMixin):
    """A row of a form with a label and a file path field."""

    _field_renderer_key = "file_path_input"


@define_view
class RowSavePathInputView(FormRowView, SavePathInputMixin):
    """A row of a form with a field of a path to save a file to, without a label."""

    _field_renderer_key = "save_path_input"


@define_view
class LabelRowSavePathInputView(FormLabelRowView, SavePathInputMixin):
    """A row of a form with a label and a field of a path to save a file to."""

    _field_renderer_key = "save_path_input"


@define_view
class RowFolderPathInputView(FormRowView, FolderPathInputMixin):
    """A row of a form with a folder path field, without a label."""

    _field_renderer_key = "folder_path_input"


@define_view
class LabelRowFolderPathInputView(FormLabelRowView, FolderPathInputMixin):
    """A row of a form with a label and a folder path field."""

    _field_renderer_key = "folder_path_input"


@define_view
class RowSliderView(FormRowView, SliderMixin):
    """A row of a form with a slider, without a label."""

    _field_renderer_key = "slider"


@define_view
class LabelRowSliderView(FormLabelRowView, SliderMixin):
    """A row of a form with a label and a slider."""

    _field_renderer_key = "slider"


@define_view
class RowCheckBoxView(FormRowView, CheckBoxMixin):
    """A row of a form with a check box, without a label."""

    _field_renderer_key = "checkbox"


@define_view
class LabelRowCheckBoxView(FormLabelRowView, CheckBoxMixin):
    """A row of a form with a label and a check box."""

    _field_renderer_key = "checkbox"


@define_view
class RowRadioGroupView(FormRowView, ValuesGroupMixin[TValue]):
    """A row of a form with a group of radio buttons, without a label."""

    _field_renderer_key = "radio_group"


@define_view
class LabelRowRadioGroupView(FormLabelRowView, ValuesGroupMixin[TValue]):
    """A row of a form with a label and a group of radio buttons."""

    _field_renderer_key = "radio_group"


@define_view
class RowComboBoxView(FormRowView, ValuesGroupMixin[TValue]):
    """A row of a form with a drop-down list, without a label."""

    _field_renderer_key = "combobox"


@define_view
class LabelRowComboBoxView(FormLabelRowView, ValuesGroupMixin[TValue]):
    """A row of a form with a label and a drop-down list."""

    _field_renderer_key = "combobox"


@define_view
class FormView(View):
    """A form: its rows, one above the other, and the message of its cross-field checks.

    Its `FormRowView` and `FormView` fields are its rows, in order (`field_rows`). Its
    other view fields, such as a table or a row of buttons, show in their place between
    the rows, as wide as the form (`content_views`). Its checks run on its rows only.
    """

    _renderer_key = "form"

    log_view: LogView = attrs.field(factory=LogView)
    #: the form's cross-field checks ran (`validate`), passing or not
    checked: SignalNoArgs = attrs.Factory(SignalNoArgs)
    #: each cross-field check with the rows it is about
    _validators: list[tuple[Validator, tuple[FormRowView, ...]]] = attrs.field(
        factory=list, init=False, repr=False, metadata={OMIT: True}
    )

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.log_view.is_visible = False

    @property
    def content_views(self) -> list[View]:
        """Get the views the form shows, in order: its rows and its other views, not its log."""
        return [view for view in self.children_views if view is not self.log_view]

    @property
    def field_rows(self) -> list[Union[FormRowView, FormView]]:
        """Get the rows of the form and its nested forms, in order."""
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

        Unlike `LogMixin.set_validator` (one validator per row, in that row's own log), a form
        can have several independent cross-field checks. The form combines each failing
        (non-None) result into its shared `log_view`, instead of the last one winning. See
        ``PipeFormView`` in ``examples/pipeform.py``: it has two independent checks spanning
        ``main_pipe`` and ``incident_pipe``. It doesn't run immediately: call `validate`
        afterward for an initial check.

        `rows` are the rows that the check is about. While the check fails, each of them shows
        its field as invalid (`FormRowView.has_form_error`). So the user sees which values to
        fix, even though the message is in the form's log. The form that last validated a row
        flags it, so name a row in the checks of one form only.
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
        self.checked.emit()

    def check(self) -> None:
        """Run every check now: each row's, then each form's, nested forms first."""
        for row in self.field_rows:
            if isinstance(row, FormView):
                row.check()
            else:
                row.run_validator()
        self.validate()

    @property
    def is_valid(self) -> bool:
        """Whether no check shown fails: a row's own, the form's, or a nested form's.

        As last checked: a check that hasn't run yet passes (see `check`).
        """
        if self.log_view.log_type is LogType.ERROR and self.log_view.log_message != "":
            return False
        return all(
            row.is_valid if isinstance(row, FormView) else not row.is_invalid
            for row in self.field_rows
        )


@define_view
class GroupFormView(FormView):
    """A form in a box with a `title`, for example a group of related fields."""

    _renderer_key = "group_form"

    title: str = attrs.field(default="", metadata={UI_TEXT: True})


FormT = TypeVar("FormT", bound=FormView)


@define_view
class TypedFormDialogView(DialogView, Generic[FormT]):
    """A modal holding a form, e.g. editing a record from its Edit button, with OK and Cancel.

    Pass a form, or give a subclass its typed ``form`` default. Its `text` shows above it. OK can't
    be pressed while a check of the form fails (`is_accept_enabled`). Accepting runs every
    check first, even one the user hasn't triggered yet, and the dialog stays open while
    one fails. The answer comes through `accepted` or `rejected`. The form keeps its
    values, for the app to read, or to fill before opening the dialog again.
    """

    _renderer_key = "form_dialog"

    form: FormT = attrs.field()
    #: whether OK can be pressed: no check shown fails on the form
    is_accept_enabled: bool = attrs.field(default=True)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.kind = DialogKind.CONFIRM
        forms: list[FormView] = [self.form]
        while len(forms) > 0:
            form = forms.pop()
            form.checked.connect(self._follow_form)
            for row in form.field_rows:
                if isinstance(row, FormView):
                    forms.append(row)
                else:
                    row.checked.connect(self._follow_form)
        self._follow_form()

    def open(self) -> None:
        """Show the dialog, OK as the form's checks last left it."""
        self._follow_form()
        super().open()

    def accept(self) -> None:
        """Close the dialog with its accepting answer, once every check of the form passes.

        Ignored unless it's open; while a check fails, it stays open, showing why.
        """
        if not self.is_visible:
            return
        self.form.check()
        if self.form.is_valid:
            super().accept()

    @property
    def content(self) -> FormT:
        """Get the view the dialog shows: its form."""
        return self.form

    def _follow_form(self) -> None:
        self.is_accept_enabled = self.form.is_valid


@define_view
class FormDialogView(TypedFormDialogView[FormView]):
    """A form dialog with a default empty `FormView`, with OK and Cancel.

    Use `TypedFormDialogView` to declare a subclass with a more specific form type.
    Both classes use the same validation, signals, and renderers.
    """

    form: FormView = attrs.Factory(FormView)


ContentT = TypeVar("ContentT", bound=View)


@define_view
class ContentDialogView(DialogView, Generic[ContentT]):
    """A modal holding a view, e.g. a table to pick a file from, with OK and Cancel.

    Pass the view as ``content``, or give a subclass its typed ``content`` default. Its
    `text` shows above it. The app sets `is_accept_enabled`, e.g. once a row is selected:
    OK can't be pressed before. The answer comes through `accepted` or `rejected`. A
    button of the content acts without closing the dialog. To keep it open on OK too,
    e.g. to show the folder selected rather than open it, a subclass overrides `accept`
    and calls ``super().accept()`` only to close it.
    """

    _renderer_key = "content_dialog"

    content: ContentT = attrs.field()
    #: whether OK can be pressed
    is_accept_enabled: bool = attrs.field(default=True)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.kind = DialogKind.CONFIRM

    def accept(self) -> None:
        """Close the dialog with its accepting answer; ignored unless it's open and OK enabled."""
        if self.is_accept_enabled:
            super().accept()


#: a dialog showing a view above OK and Cancel, as the backends render it
OkCancelDialogView = Union[TypedFormDialogView[Any], ContentDialogView[Any]]


class Align(enum.Enum):
    """Where a row packs its views when they leave some of its width free."""

    START = enum.auto()
    END = enum.auto()


@define_view
class HorizontalView(View):
    """Its view fields laid out side by side, in a row.

    Each field takes a share of the row's width, set by its `STRETCH` metadata:
    ``rooms: TableView = attrs.field(factory=TableView, metadata={STRETCH: 3})``. When the
    metadata is unset, the share is the view's `default_stretch` (1). A view with a share
    of 0 keeps its content's width, as a button does by default. When all views do,
    `align` packs them at the row's start or end: a subclass sets ``align = Align.END``.
    On the web, a row narrower than 42rem stacks its views, unless none takes a share.
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


class Orientation(enum.Enum):
    """How a splitter lays out its panes."""

    #: side by side, sharing its width
    HORIZONTAL = enum.auto()
    #: one above the other, sharing its height
    VERTICAL = enum.auto()


@define_view
class SplitterView(View):
    """Its view fields in panes, side by side, the user dragging the border between two.

    E.g. a study tree beside its result. Each pane starts with its share of the width, set
    by its field's `STRETCH` metadata as in a `HorizontalView`. The share is at least 1:
    every pane takes some width. `sizes` holds the shares. The user changes them by
    dragging a border, or with the arrow keys on it, and never shrinks a pane to nothing.
    A hidden pane leaves its width to the others. On the web, a splitter narrower than
    42rem stacks its panes, as a row does.

    A subclass that sets ``orientation = Orientation.VERTICAL`` lays out the panes one
    above the other instead, e.g. a chart above its table. The panes then share its
    height: the window's spare height on Qt, a set height elsewhere (24 rows on Textual,
    32rem on the web). Each pane scrolls within its share.
    """

    _renderer_key = "splitter"

    #: how the panes are laid out: side by side, or one above the other
    orientation: ClassVar[Orientation] = Orientation.HORIZONTAL

    def _check_sizes(self, _attribute: attrs.Attribute[Any], sizes: list[int]) -> None:
        count = len(self.children_views)
        if len(sizes) not in (0, count) or any(size <= 0 for size in sizes):
            msg = f"Cannot share {type(self).__name__}'s {count} panes as {sizes}."
            raise ValueError(msg)

    #: each pane's share of the width (the height, vertical), in order; once the user drags
    #: a border, the panes shown in percent of theirs. Layout, not study data: never saved,
    #: loaded or reset
    sizes: list[int] = attrs.field(factory=list, validator=[_check_sizes], metadata={OMIT: True})
    #: names a border between two panes for a screen reader, on the web
    border_text: str = attrs.field(default=T("Resize the panes"), metadata={UI_TEXT: True})
    #: the user dragged a border (once dropped) or moved one with a key, giving the new
    #: `sizes`; not emitted when `sizes` is set in code
    resized: Signal[list[int]] = attrs.Factory(Signal[list[int]])

    def __attrs_post_init__(self) -> None:
        if len(self.sizes) == 0:
            self.sizes = [
                max(f.metadata.get(STRETCH, view.default_stretch), 1)
                for f in attrs.fields(cast("type[AttrsInstance]", type(self)))
                if isinstance(view := getattr(self, f.name), View)
            ]
        super().__attrs_post_init__()

    @property
    def panes(self) -> list[View]:
        """Get the panes' views, in order."""
        return self.children_views

    def shares_of(self, lengths: Sequence[float]) -> list[int]:
        """Get the `sizes` of panes `lengths` wide (tall, vertical), as the user dragged them.

        In any unit: a pane shown gets its percent of the shown panes' length, at least 1;
        a hidden one keeps its share.
        """
        shown = [view.is_visible for view in self.panes]
        total = sum(length for length, is_shown in zip(lengths, shown) if is_shown)
        if total <= 0:  # not laid out yet
            return list(self.sizes)
        return [
            max(round(100 * length / total), 1) if is_shown else size
            for length, is_shown, size in zip(lengths, shown, self.sizes)
        ]


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


@define_view
class TabPage(View):
    """A tab of a `TabView`: its `title` on the tab, its view fields its content, in a column.

    Hidden, its tab is too; disabled, its tab can't be picked.
    """

    _renderer_key = "tab_page"

    title: str = attrs.field(default="", metadata={UI_TEXT: True})


@define_view
class TabView(View):
    """Views shown a tab at a time, picked from a row of tabs, e.g. a record's details and history.

    Its `TabPage` fields are the tabs, in order; it starts on the first. Distinct from
    pages: tabs live inside a page or a form, and have no address of their own.
    """

    _renderer_key = "tabs"

    def _check_current_index(self, _attribute: attrs.Attribute[Any], index: int) -> None:
        count = len(self.tabs)
        if not 0 <= index < max(count, 1):
            msg = f"Cannot show tab {index} of {type(self).__name__}: it has {count} tabs."
            raise ValueError(msg)

    #: the tab shown, counted from 0. Navigation, not study data: never saved, loaded or reset
    current_index: int = attrs.field(
        default=0, validator=[_check_current_index], metadata={OMIT: True}
    )
    #: the user picked another tab, by its index; not emitted when `current_index` is set in code
    current_changed: Signal[int] = attrs.Factory(Signal[int])

    @property
    def tabs(self) -> list[TabPage]:
        """Get the tabs, in order."""
        return [view for view in self.children_views if isinstance(view, TabPage)]

    @property
    def current_tab(self) -> Optional[TabPage]:
        """Get the tab shown, or None without tabs."""
        tabs = self.tabs
        return tabs[self.current_index] if len(tabs) > 0 else None


class GridPosition(NamedTuple):
    """A view's cell in a `GridView`, counted from 0, spanning more cells to its right or below."""

    row: int
    column: int
    row_span: int = 1
    column_span: int = 1

    @property
    def cells(self) -> list[tuple[int, int]]:
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
    top. A view with no share of a row (`default_stretch` 0, e.g. a button) keeps its
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


#: what a page's route can be: it also names the page in a web address (``/<route>``)
_ROUTE_PATTERN = re.compile(r"[A-Za-z0-9_-]+")


@define_view
class PageView(View):
    """A page of the app, shown while its `Router` is on the page's `route`.

    Its view fields are its content, laid out in a column. `action` is its entry in the
    router's toolbar, which shows the page's `title` and `icon`. The action isn't content.
    It is navigation, not study data: never saved, loaded or reset.
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

    Make it a field of the main view, not of its router, rather than repeat a view on each
    page. Its view fields are its content, laid out in a column on the window's left. Qt
    docks it, and Textual shows it left of the scrolling content. The web shows a column
    left of the pages, and on a phone a drawer that a button in the header opens. The user
    retracts it to a narrow strip, and back, with a button (`is_expanded`).
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

    A subclass builds a record's view (`build_item`). Set `items` to the records, e.g. the
    model's, to show them. A new record gets a view of its own, and a record gone takes
    its view along. A record still there keeps its view, told by its key (`item_key`). A
    changed record keeps its view if `update_item` shows the change in it. The view then
    keeps what the user did to it, e.g. an expander stays expanded. Else the record gets a
    new view. The records and their views are the model's, not study data: never saved,
    loaded or reset.
    """

    _renderer_key = "list"

    #: the records' views, in the records' order; made by setting `items`
    item_views: list[View] = attrs.field(factory=list, init=False, metadata={OMIT: True})
    _items: list[ItemT] = attrs.field(factory=list, init=False, repr=False, metadata={OMIT: True})
    #: the model the signals of the views built pass on (see `set_references`)
    _model: Optional[Callable[[], Optional[Model]]] = attrs.field(
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
    def items(self, items: Iterable[ItemT]) -> None:
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


#: a node of a `TreeView`, by the keys from its top-level node down to it
TreePath = tuple[str, ...]


def _to_tree_nodes(nodes: Iterable[TreeNode]) -> tuple[TreeNode, ...]:
    return tuple(nodes)


class NodeMark(enum.Enum):
    """A mark of a tree node's state, shown after its label."""

    #: done, e.g. an analysis that ran: a green check
    DONE = enum.auto()
    #: to look at, e.g. an analysis whose results are out of date: an orange "!"
    WARNING = enum.auto()
    #: failed, e.g. an analysis that stopped on an error: a red cross
    ERROR = enum.auto()


@attrs.frozen
class TreeNode:
    """A node of a `TreeView`: its text, and the nodes under it.

    Its `key`, its label unless given, tells it apart from its siblings. The tree knows a
    node by its path (see `TreeView`). So nodes under different parents may share a key,
    e.g. a "Pipes" folder under each building.
    """

    label: str
    children: tuple[TreeNode, ...] = attrs.field(default=(), converter=_to_tree_nodes)
    key: str = attrs.field(default=attrs.Factory(lambda node: node.label, takes_self=True))
    #: an image file's path, before the label (not on Textual); set by the app, not
    #: study data: never saved or loaded, as `ActionView.icon`
    icon: Optional[str] = None
    mark: Optional[NodeMark] = None
    is_bold: bool = False
    is_underlined: bool = False


def _unstructure_tree_node(node: TreeNode) -> dict[str, Any]:
    # by hand: Python 3.9 doesn't resolve the class naming itself in `children`
    return {
        "label": node.label,
        "key": node.key,
        "children": [_unstructure_tree_node(child) for child in node.children],
        "mark": None if node.mark is None else node.mark.name,
        "is_bold": node.is_bold,
        "is_underlined": node.is_underlined,
    }


def _structure_tree_node(data: Mapping[str, Any], _type: type) -> TreeNode:
    children = [_structure_tree_node(child, TreeNode) for child in data.get("children", [])]
    mark = data.get("mark")
    return TreeNode(
        str(data["label"]),
        children,
        str(data.get("key", data["label"])),
        mark=None if mark is None else NodeMark[str(mark)],
        is_bold=bool(data.get("is_bold", False)),
        is_underlined=bool(data.get("is_underlined", False)),
    )


CONVERTER.register_unstructure_hook(TreeNode, _unstructure_tree_node)
CONVERTER.register_structure_hook(TreeNode, _structure_tree_node)


def walk_tree(
    nodes: Iterable[TreeNode], parent: TreePath = ()
) -> Iterator[tuple[TreePath, TreeNode]]:
    """Get each node of `nodes` and under them with its path, depth first, in order."""
    for node in nodes:
        path = (*parent, node.key)
        yield path, node
        yield from walk_tree(node.children, path)


@define_view
class TreeView(View):
    """Nodes in a tree, e.g. a site's buildings, their floors and their rooms.

    A node is known by its path, the keys from its top-level node down to it (see
    `TreeNode`). The user expands and collapses the nodes that have children. `expanded`
    holds the paths of the expanded nodes, and `toggled` emits a node's path and whether
    it is now expanded. The user selects one node: `selected` holds its path, and
    `selection_changed` emits it. Assign new `nodes` to update the tree: they keep the
    paths of `expanded` and `selected` still in them, and drop the others.
    """

    _renderer_key = "tree"

    def _check_nodes(self, _attribute: attrs.Attribute[Any], nodes: list[TreeNode]) -> None:
        paths: set[TreePath] = set()
        for path, _node in walk_tree(nodes):
            if path in paths:
                msg = (
                    f"Cannot set {type(self).__name__}.nodes: two nodes at {list(path)} share"
                    " the key; give them each a key of their own."
                )
                raise ValueError(msg)
            paths.add(path)

    def _check_expanded(self, _attribute: attrs.Attribute[Any], expanded: list[TreePath]) -> None:
        paths = {path for path, _node in walk_tree(self.nodes)}
        for path in expanded:
            if path not in paths:
                msg = (
                    f"Cannot expand the node {list(path)} of {type(self).__name__}: none is there."
                )
                raise ValueError(msg)

    def _check_selected(
        self, _attribute: attrs.Attribute[Any], selected: Optional[TreePath]
    ) -> None:
        if selected is not None and selected not in {path for path, _node in walk_tree(self.nodes)}:
            msg = (
                f"Cannot select the node {list(selected)} of {type(self).__name__}: none is there."
            )
            raise ValueError(msg)

    def _reconcile_nodes(
        self, attribute: attrs.Attribute[Any], nodes: list[TreeNode]
    ) -> list[TreeNode]:
        """Drop the paths of `expanded` and `selected` gone, then notify the renderer.

        Unnotified: the renderer shows them with the nodes.
        """
        paths = {path for path, _node in walk_tree(nodes)}
        object.__setattr__(self, "expanded", [path for path in self.expanded if path in paths])
        if self.selected not in paths:
            object.__setattr__(self, "selected", None)
        return cast("list[TreeNode]", notify_renderer(self, attribute, nodes))

    nodes: list[TreeNode] = attrs.field(
        factory=list[TreeNode],
        validator=[_check_nodes],
        on_setattr=[attrs.setters.validate, _reconcile_nodes],
    )
    # after `nodes`: loading saved state checks them against the nodes already loaded
    expanded: list[TreePath] = attrs.field(factory=list[TreePath], validator=[_check_expanded])
    selected: Optional[TreePath] = attrs.field(default=None, validator=[_check_selected])
    #: the user expanded (True) or collapsed a node; not emitted when `expanded` is set in code
    toggled: Signal[TreePath, bool] = attrs.Factory(Signal[TreePath, bool])
    #: the user selected a node; not emitted when `selected` is set in code
    selection_changed: Signal[TreePath] = attrs.Factory(Signal[TreePath])
    #: each `NodeMark`'s name, for screen readers (web) and as a tooltip (Qt)
    done_text: str = attrs.field(default=T("Done"), metadata={UI_TEXT: True})
    warning_text: str = attrs.field(default=T("Warning"), metadata={UI_TEXT: True})
    error_text: str = attrs.field(default=T("Error"), metadata={UI_TEXT: True})

    def mark_text(self, mark: NodeMark) -> str:
        """Get the name of `mark` in the main view's language."""
        if mark is NodeMark.DONE:
            return self.done_text
        return self.warning_text if mark is NodeMark.WARNING else self.error_text

    def node(self, path: TreePath) -> TreeNode:
        """Get the node at `path`, e.g. the selected one's label; KeyError if none is there."""
        for node_path, node in walk_tree(self.nodes):
            if node_path == path:
                return node
        raise KeyError(path)

    def expanded_with(self, path: TreePath, *, is_expanded: bool) -> list[TreePath]:
        """Get `expanded` with the node at `path` expanded or collapsed, the others kept."""
        kept = [expanded for expanded in self.expanded if expanded != path]
        return [*kept, path] if is_expanded else kept

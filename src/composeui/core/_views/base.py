"""The base of the views: `View`, `define_view`, the converter and the lazy signals."""

from __future__ import annotations

import contextlib
import contextvars
import copy
import datetime
import decimal
import enum
import logging
import re
import sys
import threading
import weakref
from collections import deque
from collections.abc import Callable, Sequence
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    NoReturn,
    Optional,
    TypeVar,
    Union,
    cast,
    overload,
)

import attrs
import cattrs
from typing_extensions import ParamSpec, dataclass_transform, override

from composeui.core.jobs import Jobs, Task, _check_main_thread
from composeui.core.model import Model, RefusedError
from composeui.core.reactivity import (
    register_types,
    register_view_class,
    set_value,
)
from composeui.core.registry import RendererType, create_renderer
from composeui.core.renderer import Renderer, RendererContainer
from composeui.core.signal import Signal
from composeui.core.translation import (
    Translate,
    TranslatedText,
    no_translation,
    translate_again,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping
    from contextlib import AbstractContextManager
    from typing import SupportsIndex

    from attrs import AttrsInstance
    from typing_extensions import Concatenate

    # attrs resolves it at run time: `main`, which imports this module, sets it here
    from composeui.core._views.main import MainView  # noqa: TC004
    from composeui.core.jobs import Job, P, ProgressT, R


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
#: Field metadata key for a field left out of a study (`OMIT`) that a session keeps when it
#: is saved and opened again, idle on the web (`WebSettings.session_idle`) or across a
#: ``--reload``: where the user is, such as the tab shown, not study data
SESSION = "session"
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


class LogType(enum.Enum):
    """How a log message reads: an error, a warning or information."""

    ERROR = enum.auto()
    WARNING = enum.auto()
    INFO = enum.auto()


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


def _attach_jobs(root: View, jobs: Jobs) -> None:
    """Give `root` and its children the jobs that run their tasks, and adopt those built."""
    reference = weakref.ref(jobs)
    views: deque[View] = deque([root])
    while len(views) > 0:
        view = views.popleft()
        # once: a view is in the main view as it is built, or a list builds it
        view._task_jobs = reference  # noqa: SLF001
        for task in view._own_tasks or ():  # noqa: SLF001 (the view's jobs, which this module keeps)
            jobs._adopt(task)  # noqa: SLF001 (shared task lifecycle)
        views.extend(view.children_views)


def _release_tasks(root: View) -> None:
    """Forget the tasks of `root` and its children, a list's row view removed."""
    views: deque[View] = deque([root])
    while len(views) > 0:
        view = views.popleft()
        jobs = None if view._task_jobs is None else view._task_jobs()  # noqa: SLF001 (the view's jobs, which this module keeps)
        view._task_jobs = None  # noqa: SLF001 (the view's jobs, which this module keeps)
        if jobs is not None:
            for task in view._own_tasks or ():  # noqa: SLF001 (the view's jobs, which this module keeps)
                jobs._release(task)  # noqa: SLF001 (shared task lifecycle)
        views.extend(view.children_views)


def set_references(root: View, main_view: MainView, model: Optional[Model]) -> None:
    """Give `root` and its children their main view, and their signals the main view and model.

    What the signals pass to a callback asking for ``main_view`` or ``model`` by name.
    A list of views keeps both, for the views it builds later.
    """
    views: deque[View] = deque([root])
    main_view_reference = weakref.ref(main_view)
    if model is not None:
        main_view._model_reference = weakref.ref(model)  # noqa: SLF001 (set as the main view is built)
    while len(views) > 0:
        current_view = views.popleft()
        current_view._main_view = main_view_reference  # noqa: SLF001 (set as the main view is built)
        current_view._keep_model(model)  # noqa: SLF001 (set as the main view is built)
        # its children, not only its view fields: e.g. a language menu's actions
        views.extend(current_view.children_views)
        # the signals made so far: the others get them as they're made (see `_LazySignal`)
        for _name, signal in made_signals(current_view):
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
    view._tr = translate  # noqa: SLF001 (set as the views are translated)
    for f in view_fields(type(view)):
        value = getattr(view, f.name)
        translated = translate_again(value, translate)
        if translated is value:
            continue
        if f.on_setattr is attrs.setters.frozen:
            # set once by the app, e.g. the main view's title: only a language changes it
            translated = _fix_collections(view, f, translated)
            notify_renderer(view, f, translated)
            set_value(view, f.name, translated)
        else:
            setattr(view, f.name, translated)
    view.retranslate()
    view._check_again()  # noqa: SLF001 (View's hook for this)


_ListItemT = TypeVar("_ListItemT")


class FixedList(list[_ListItemT]):
    """A view field's list: read it as any list, and set a new one to change it.

    A change in place would reach neither the renderer nor anything that follows the field,
    so it raises `TypeError`. ``view.points += [point]`` sets a new list, and so works.
    """

    __slots__ = ("_field",)

    def __init__(self, items: Iterable[_ListItemT] = (), field: str = "") -> None:
        super().__init__(items)
        self._field = field

    @property
    def field(self) -> str:
        """Get the view field holding it, e.g. ``MapView.points``, for the error."""
        return self._field

    def _refuse(self) -> NoReturn:
        msg = (
            f"{self._field} can't change in place, which nothing would see: set a new list,"
            " e.g. with += or [*items, item]"
        )
        raise TypeError(msg)

    @override
    def append(self, _item: _ListItemT, /) -> NoReturn:
        self._refuse()

    @override
    def extend(self, _items: Iterable[_ListItemT], /) -> NoReturn:
        self._refuse()

    @override
    def insert(self, _index: SupportsIndex, _item: _ListItemT, /) -> NoReturn:
        self._refuse()

    @override
    def pop(self, _index: SupportsIndex = -1, /) -> NoReturn:
        self._refuse()

    @override
    def remove(self, _item: _ListItemT, /) -> NoReturn:
        self._refuse()

    @override
    def clear(self) -> NoReturn:
        self._refuse()

    @override
    def sort(self, *_args: Any, **_kwargs: Any) -> NoReturn:
        self._refuse()

    @override
    def reverse(self) -> NoReturn:
        self._refuse()

    @override
    def __setitem__(self, _index: Any, _value: Any, /) -> NoReturn:
        self._refuse()

    @override
    def __delitem__(self, _index: Any, /) -> NoReturn:
        self._refuse()

    @override
    def __iadd__(self, items: Iterable[_ListItemT], /) -> list[_ListItemT]:  # type: ignore[override]
        return [*self, *items]  # a new list, which `+=` then sets on the view

    @override
    def __imul__(self, count: SupportsIndex, /) -> list[_ListItemT]:  # type: ignore[override]
        return list(self) * count

    @override
    def __reduce__(self) -> tuple[type[list[_ListItemT]], tuple[list[_ListItemT]]]:
        return (list, (list(self),))  # a copy, or a pickle, is a plain list


_KeyT = TypeVar("_KeyT")
_ValueT = TypeVar("_ValueT")


class FixedDict(dict[_KeyT, _ValueT]):
    """A view field's dict: read it as any dict, and set a new one to change it.

    A change in place would reach neither the renderer nor the field's checks, so it raises
    `TypeError`. ``view.filters |= {0: "a"}`` sets a new dict, and so works.
    """

    __slots__ = ("_field",)

    def __init__(self, items: Mapping[_KeyT, _ValueT], field: str) -> None:
        super().__init__(items)
        self._field = field

    @property
    def field(self) -> str:
        """Get the view field holding it, e.g. ``TableView.filters``, for the error."""
        return self._field

    def _refuse(self) -> NoReturn:
        msg = (
            f"{self._field} can't change in place, which nothing would see: set a new dict,"
            " e.g. with |= or {**items, key: value}"
        )
        raise TypeError(msg)

    @override
    def __setitem__(self, _key: _KeyT, _value: _ValueT, /) -> NoReturn:
        self._refuse()

    @override
    def __delitem__(self, _key: _KeyT, /) -> NoReturn:
        self._refuse()

    @override
    def update(self, *_args: Any, **_kwargs: Any) -> NoReturn:
        self._refuse()

    @override
    def pop(self, *_args: Any) -> NoReturn:
        self._refuse()

    @override
    def popitem(self) -> NoReturn:
        self._refuse()

    @override
    def setdefault(self, *_args: Any) -> NoReturn:
        self._refuse()

    @override
    def clear(self) -> NoReturn:
        self._refuse()

    @override
    def __ior__(self, items: Any, /) -> dict[_KeyT, _ValueT]:  # type: ignore[override]
        changed = dict(self)
        changed.update(items)
        return changed  # a new dict, which `|=` then sets on the view

    @override
    def __reduce__(self) -> tuple[type[dict[_KeyT, _ValueT]], tuple[dict[_KeyT, _ValueT]]]:
        return (dict, (dict(self),))  # a copy, or a pickle, is a plain dict


def _refuse_in_item(field: str) -> NoReturn:
    owner = field.partition(".")[0]
    msg = (
        f"{field} can't change in place, which nothing would see: make a new {owner}, e.g."
        " with attrs.evolve"
    )
    raise TypeError(msg)


class ItemList(FixedList[_ListItemT]):
    """A list of a frozen item, such as `Series.x`: make a new item to change it.

    A copy of it, as a copy of its item makes, stays so: ``list(series.x)`` is a plain list.
    """

    __slots__ = ()

    @override
    def _refuse(self) -> NoReturn:
        _refuse_in_item(self.field)

    @override
    def __reduce__(self) -> tuple[type[ItemList[_ListItemT]], tuple[list[_ListItemT], str]]:  # type: ignore[override]
        # kept in a copy: a copy of its item, such as `child`'s, holds it as it is
        return (ItemList, (list(self), self.field))


class ItemDict(FixedDict[_KeyT, _ValueT]):
    """A dict of a frozen item, such as `CellWidget.editors`: make a new item to change it.

    A copy of it, as a copy of its item makes, stays so: ``dict(widget.editors)`` is a plain
    dict.
    """

    __slots__ = ()

    @override
    def _refuse(self) -> NoReturn:
        _refuse_in_item(self.field)

    @override
    def __reduce__(  # type: ignore[override]
        self,
    ) -> tuple[type[ItemDict[_KeyT, _ValueT]], tuple[dict[_KeyT, _ValueT], str]]:
        # kept in a copy: a copy of its item, such as `child`'s, holds it as it is
        return (ItemDict, (dict(self), self.field))


def _unstructure_fixed_list(value: FixedList[Any]) -> list[Any]:
    """Unstructure a view's list as any list: cattrs takes its subclass for another type."""
    return [CONVERTER.unstructure(item) for item in value]


CONVERTER.register_unstructure_hook(FixedList, _unstructure_fixed_list)


def _fixed(value: Any, field: str) -> Any:
    """Get `value` as `FixedList` or `FixedDict`, the lists and dicts it holds too.

    Anything else stays as it is, a subclass of `dict` such as a `defaultdict` too: as a
    `FixedDict`, it would lose what it does.
    """
    if type(value) in (FixedList, FixedDict) and value.field == field:
        return value  # what it holds is fixed already
    if type(value) is dict or isinstance(value, FixedDict):
        return FixedDict({key: _fixed(item, field) for key, item in value.items()}, field)
    if isinstance(value, list):
        return FixedList((_fixed(item, field) for item in value), field)
    return value


def _fix_collections(instance: View, attribute: Any, value: Any) -> Any:
    """Set a list or a dict as a `FixedList` or `FixedDict` (a hook of every view field).

    Not in a private field: the view's own code may change it in place.
    """
    if attribute.name.startswith("_"):
        return value
    return _fixed(value, f"{type(instance).__name__}.{attribute.name}")


#: field metadata key of a signal field made on its first read (see `_LazySignal`): its factory
_LAZY_SIGNAL = "lazy_signal"
#: held while a view's signal is made, so two threads reading it first share one
_MAKING_SIGNAL = threading.Lock()


def _signal_factory(field: attrs.Attribute[Any]) -> Optional[Callable[[], Signal[Any]]]:
    """Get the factory of `field`'s signal, if its default makes one, else None."""
    made = field.metadata.get(_LAZY_SIGNAL)
    if made is not None:
        return cast("Callable[[], Signal[Any]]", made)
    default: Any = field.default  # an `attrs.Factory`, whose type attrs doesn't export
    factory = getattr(default, "factory", None)
    if factory is None or getattr(default, "takes_self", False):
        return None
    made_class = getattr(factory, "__origin__", factory)
    if isinstance(made_class, type) and issubclass(made_class, Signal):
        return cast("Callable[[], Signal[Any]]", factory)
    return None


class _LazySignal:
    """A view's signal field, made on its first read, as most signals are never connected.

    A page has views by the hundred, each with signals, and a web session a page: a signal
    that nothing reads costs nothing. It keeps the signals made in the view's
    `_signals`, so the view's attributes stay the ones every view of its class has: a list
    of names and signals, smaller than a dict, as a view has few signals.
    """

    __slots__ = ("_factory", "_name")

    def __init__(self, name: str, factory: Callable[[], Signal[Any]]) -> None:
        self._name = name
        self._factory = factory

    def __get__(self, view: Optional[View], owner: Optional[type] = None) -> Any:
        if view is None:
            return self
        signal = made_signal(view, self._name)
        if signal is None:
            with _MAKING_SIGNAL:
                signal = made_signal(view, self._name)
                if signal is None:
                    signal = self._factory()
                    self._store(view, signal)
        return signal

    def __set__(self, view: View, value: Optional[Signal[Any]]) -> None:
        if value is not None:  # None: `__init__`'s, for a signal not made yet
            with _MAKING_SIGNAL:
                self._store(view, value)

    def _store(self, view: View, signal: Signal[Any]) -> None:
        # first: a signal another view owns is refused, and keeps its name for the error
        signal.set_view(view)
        # interned: each instance of the view, e.g. each session's, shares the name
        signal.set_name(sys.intern(f"{type(view).__name__}.{self._name}"))
        main_view = None if view._main_view is None else view._main_view()  # noqa: SLF001 (set as the main view is built)
        if main_view is not None:
            signal.set_main_view(main_view)
            reference = main_view._model_reference  # noqa: SLF001 (set as the main view is built)
            model = None if reference is None else reference()
            if model is not None:
                signal.set_model(model)
        signals = view._signals  # noqa: SLF001 (the signals that this module makes)
        if signals is None:
            object.__setattr__(view, "_signals", [self._name, signal])
            return
        for index in range(0, len(signals), 2):
            if signals[index] == self._name:  # a signal set in its place
                signals[index + 1] = signal
                return
        signals.extend((self._name, signal))


def made_signal(view: View, name: str) -> Optional[Signal[Any]]:
    """Get the signal of `view`'s field `name` if it's made, without making it."""
    signals = view._signals  # noqa: SLF001 (the signals that this module makes)
    if signals is not None:
        for index in range(0, len(signals), 2):
            if signals[index] == name:
                return cast("Signal[Any]", signals[index + 1])
    return None


def emit_if_made(view: View, name: str, *args: object) -> None:
    """Emit `view`'s signal `name` if it's made: one never read has no callback to call."""
    signal = made_signal(view, name)
    if signal is not None:
        signal.emit(*args)


def made_signals(view: View) -> list[tuple[str, Signal[Any]]]:
    """Get the signals of `view` made so far, with their field names, without making others."""
    signals = view._signals or []  # noqa: SLF001 (the signals that this module makes)
    return list(zip(signals[::2], signals[1::2]))


def _lazy_signals_on_set(_cls: type, fields: list[Any]) -> list[Any]:
    """Make each signal field one made on its first read (see `_LazySignal`)."""
    lazy = []
    for field in fields:
        factory = _signal_factory(field)
        if factory is not None:
            # not in `repr`, which reads every field: it would make them all
            field = field.evolve(  # noqa: PLW2901
                default=None, repr=False, metadata={**field.metadata, _LAZY_SIGNAL: factory}
            )
        lazy.append(field)
    return lazy


_VIEW_FIELDS: dict[type, tuple[attrs.Attribute[Any], ...]] = {}


def view_fields(cls: type) -> tuple[attrs.Attribute[Any], ...]:
    """Get the fields of the view class `cls` but its signals, which a read would make."""
    fields = _VIEW_FIELDS.get(cls)
    if fields is None:
        fields = tuple(
            f
            for f in attrs.fields(cast("type[AttrsInstance]", cls))
            if _LAZY_SIGNAL not in f.metadata
        )
        _VIEW_FIELDS[cls] = fields
    return fields


def _fix_collections_on_set(_cls: type, fields: list[Any]) -> list[Any]:
    """Run `_fix_collections` first among the hooks of each field that has hooks of its own."""
    fields = _lazy_signals_on_set(_cls, fields)
    fixed = []
    for field in fields:
        hooks = field.on_setattr
        if (
            hooks is not None
            and hooks is not attrs.setters.NO_OP
            and hooks is not attrs.setters.frozen
        ):
            field = field.evolve(on_setattr=attrs.setters.pipe(_fix_collections, hooks))  # noqa: PLW2901 (the field, replaced by its changed copy)
        fixed.append(field)
    return fixed


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
    after the validators, before the renderer hears the change. A field whose default makes
    a `Signal` makes it on its first read, and its `repr` leaves it out.
    """

    def wrap(cls: _ClassT) -> _ClassT:
        options = {"kw_only": True, "slots": False, **kwargs}
        own = options.pop("on_setattr", [])
        hooks = list(own) if isinstance(own, Sequence) else [own]
        defined = attrs.define(
            cls,
            on_setattr=[_fix_collections, attrs.setters.validate, *hooks, notify_renderer],
            field_transformer=_fix_collections_on_set,
            **options,
        )
        for f in attrs.fields(defined):
            factory = f.metadata.get(_LAZY_SIGNAL)
            inherited = getattr(defined, f.name, None)
            if factory is None and isinstance(inherited, _LazySignal):
                # the signal's descriptor, inherited, would take the field's values
                msg = f"{defined.__name__}.{f.name} replaces a signal with another kind of field"
                raise TypeError(msg)
            if factory is not None and not isinstance(defined.__dict__.get(f.name), _LazySignal):
                type.__setattr__(defined, f.name, _LazySignal(f.name, factory))
        register_view_class(defined)
        return defined

    if cls is None:
        return wrap
    return wrap(cls)


_P = ParamSpec("_P")
_ViewT = TypeVar("_ViewT", bound="View")


def catching_context(
    func: Callable[_P, Iterator[None]],
) -> Callable[_P, AbstractContextManager[None, bool]]:
    """Make a context manager, as `contextlib.contextmanager`, that may catch the error.

    Its type says so: mypy then knows that the code after the `with` block can run.
    """
    return cast("Callable[_P, AbstractContextManager[None, bool]]", contextlib.contextmanager(func))


def child(cls: Callable[_P, _ViewT], /, *args: _P.args, **kwargs: _P.kwargs) -> _ViewT:
    """Get a view field's default: a `cls` view built with these arguments, one per view.

    E.g. ``add: ButtonView = child(ButtonView, text=T("Add"))``. The arguments are copied
    for each view built, so a list among them is never shared.
    """

    def build() -> _ViewT:
        return cls(*copy.deepcopy(args), **copy.deepcopy(kwargs))

    return attrs.Factory(build)


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

    #: its signals made so far, each after its field name; None until its first (`_LazySignal`)
    _signals: Optional[list[Any]] = attrs.field(
        default=None, init=False, repr=False, eq=False, metadata={OMIT: True}
    )
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
    #: the jobs of the main view holding this view, which run its tasks; weak, as `_main_view`
    _task_jobs: Optional[Callable[[], Optional[Jobs]]] = attrs.field(
        default=None, init=False, repr=False, eq=False, metadata={OMIT: True}
    )
    #: the tasks that `build_task` built, released with a list's row view removed
    _own_tasks: Optional[list[Task[Any, Any, Any]]] = attrs.field(
        default=None, init=False, repr=False, eq=False, metadata={OMIT: True}
    )

    def __attrs_post_init__(self) -> None:
        for f in view_fields(type(self)):
            value = getattr(self, f.name, None)
            if isinstance(value, (list, dict)) and not f.name.startswith("_"):
                # as `_fix_collections` sets it: the hooks don't run in `__init__`
                object.__setattr__(self, f.name, _fixed(value, f"{type(self).__name__}.{f.name}"))
        self.retranslate()

    def build_task(
        self, work: Callable[Concatenate[Job[R, ProgressT], P], R], *, debounce: float = 0.2
    ) -> Task[R, P, ProgressT]:
        """Build a reusable task for `work`, run by the jobs of this view's main view.

        Call it on the main thread, e.g. in `__attrs_post_init__`. The task can start once a
        main view holds this view: once the main view is built, or a list builds the row.
        `debounce` is the seconds `Task.start_latest` waits for a newer call.
        """
        _check_main_thread("View.build_task")
        jobs = None if self._task_jobs is None else self._task_jobs()
        task: Task[R, P, ProgressT] = Task(None, work, debounce=debounce)
        if jobs is not None:
            jobs._adopt(task)  # noqa: SLF001 (shared task lifecycle)
        if self._own_tasks is None:
            self._own_tasks = []
        self._own_tasks.append(task)
        return task

    def tr(self, text: str) -> TranslatedText:
        """Translate `text`, as written in the code, into the main view's language.

        A view that keeps the translation, in a field or in a list or dict of one, shows it in
        the next language that `MainView.set_language` sets. Formatted text follows too.
        """
        return TranslatedText(self._tr(text), text)

    @catching_context
    def refusing(self, message: str) -> Iterator[None]:
        """Show the model's refusal of the block's change as an error above the page (`notify`).

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
            main_view.notify(self._refusal(message, error), LogType.ERROR)
            if _editing_cell.get():
                raise EditRefusedError from error

    def _refusal(self, message: str, error: RefusedError) -> str:
        """Get `message` telling the user of `error`, its reason translated, as ``{error}``."""
        reason = error.args[0] if error.args else ""
        if not isinstance(reason, TranslatedText):
            reason = self.tr(str(reason))
        return message.format(error=reason)

    def retranslate(self) -> None:
        """Update text that `tr` alone doesn't follow, e.g. built from other text.

        Called once while the view is built, before the rest of `__attrs_post_init__`. Then
        `MainView.set_language` calls it on every view once their text is translated,
        children before their parent.
        """

    def _check_again(self) -> None:
        """Run the view's check again: its message on show is in the previous language.

        `MainView.set_language` calls it after `retranslate`. A view with a check sets it.
        """

    def _keep_model(self, model: Optional[Model]) -> None:
        """Keep `model` for the views that the view builds later (see `set_references`)."""

    @property
    def children_views(self) -> list[View]:
        """Get the views in the fields of this view, in order."""
        children_views: list[View] = []
        for field_row_attr in view_fields(type(self)):
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


register_types(View, Signal)


def _unstructure_date(value: datetime.date) -> str:
    return value.isoformat()


def _structure_date(value: Any, _type: type) -> datetime.date:
    return datetime.date.fromisoformat(str(value))


#: a UTC offset of less than a second, which `fromisoformat` reads as UTC on older Pythons
_OFFSET_UNDER_A_SECOND = re.compile(r"([+-])00:00:00\.(\d{6})$")


def _structure_datetime(value: Any, _type: type) -> datetime.datetime:
    if isinstance(value, datetime.datetime):
        return value
    text = str(value)
    parsed = datetime.datetime.fromisoformat(text)
    offset = _OFFSET_UNDER_A_SECOND.search(text)
    if offset is None:
        return parsed
    microseconds = int(offset[1] + offset[2])
    return parsed.replace(tzinfo=datetime.timezone(datetime.timedelta(microseconds=microseconds)))


def _unstructure_decimal(value: decimal.Decimal) -> str:
    # its exact text: JSON has no decimals, and a float would round it
    return str(value)


def _structure_decimal(value: Any, _type: type) -> decimal.Decimal:
    try:
        return decimal.Decimal(str(value))
    except decimal.InvalidOperation as error:  # an `ArithmeticError`: a bad state's error
        msg = f"{value!r} isn't a decimal number"
        raise ValueError(msg) from error


# registered with their type: cattrs can't read a postponed annotation on 3.9
CONVERTER.register_unstructure_hook(datetime.date, _unstructure_date)
CONVERTER.register_structure_hook(datetime.date, _structure_date)
CONVERTER.register_structure_hook(datetime.datetime, _structure_datetime)
CONVERTER.register_unstructure_hook(decimal.Decimal, _unstructure_decimal)
CONVERTER.register_structure_hook(decimal.Decimal, _structure_decimal)


def _check_height(view: View, _attribute: attrs.Attribute[Any], height: Optional[int]) -> None:
    if height is not None and height <= 0:
        msg = f"Cannot set {type(view).__name__}.height to {height}: it must be positive."
        raise ValueError(msg)


_COLOR_PATTERN = re.compile(r"#[0-9a-fA-F]{6}")


class EditRefusedError(Exception):
    """Raised by a `cell_edited` callback to refuse the edit: the cell keeps its old text."""


#: whether a `cell_edited` callback is running, for `View.refusing` to refuse its edit
_editing_cell: contextvars.ContextVar[bool] = contextvars.ContextVar("_editing_cell", default=False)

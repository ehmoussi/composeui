"""Reactive methods: view methods that run again when a view field they read changes."""

from __future__ import annotations

import contextvars
import datetime
import enum
import heapq
import inspect
import itertools
import logging
import pathlib
import threading
import weakref
from collections import deque
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Callable, TypeVar, cast

if TYPE_CHECKING:
    from collections.abc import Generator

    from attrs import AttrsInstance

    from composeui.core.view import View

__all__ = [
    "ReactiveLoopError",
    "reactive",
    "reactive_inputs",
    "start_reactions",
    "stop_reactions",
]

_ViewT = TypeVar("_ViewT", bound="View")

LOGGER = logging.getLogger("COMPOSEUI")

#: the most runs of one method while one change settles: past it, methods change each other
_MAX_RUNS = 100
#: the attribute marking a reactive method
_MARK = "__composeui_reactive__"
#: where a view keeps what reactions read of its fields, by field name
_SOURCES = "_composeui_sources"
#: where a view keeps its reactions, by method name
_REACTIONS = "_composeui_reactions"
#: values compared by equality: setting an equal one changes nothing; others by identity
_PLAIN = (str, int, float, bool, bytes, enum.Enum, datetime.date, datetime.time, pathlib.PurePath)

#: the reaction recording its reads; None outside one, and in ComposeUI's own code
_TRACKING: contextvars.ContextVar[_Reaction | None] = contextvars.ContextVar(
    "composeui_tracking", default=None
)
#: the reaction running, even where its reads aren't recorded
_RUNNING: contextvars.ContextVar[_Reaction | None] = contextvars.ContextVar(
    "composeui_running", default=None
)
#: the reactions to run once the current batch of changes is over
_PENDING: contextvars.ContextVar[dict[_Reaction, None] | None] = contextvars.ContextVar(
    "composeui_pending", default=None
)


class ReactiveLoopError(RuntimeError):
    """A reactive method set a field that it reads, or methods kept changing each other."""


class _State:
    #: whether a reactive method exists: until then, the view fields cost nothing more
    enabled = False
    #: the view classes defined, to track once a reactive method exists
    view_classes: list[type[Any]] = []  # noqa: RUF012 (one shared registry)
    #: the view class: a field holding one, or a list of them, is a branch of the tree
    view_type: type[Any] = object
    #: the values that may hold views: a view, or a list of them
    view_holders: tuple[type[Any], ...] = (list, tuple)
    #: values whose read isn't an input, e.g. a signal, set once
    not_inputs: tuple[type[Any], ...] = ()
    #: the batches of reactions running, in all threads: their reads are recorded
    running_batches = 0
    lock = threading.Lock()


def reactive(method: Callable[[_ViewT], None]) -> Callable[[_ViewT], None]:
    """Run this view method again each time a view field that it read changes.

    The application runs it once when the app starts, after `setup_model`, and records the
    fields that it reads. A run records them again: a branch not taken isn't an input. A
    `Task`'s state is an input too. An event, such as the callbacks of one signal, runs it
    once after the event, with the other methods in the order they started. The method must
    not set a field that it reads. Slow work goes to a task's `Task.start_latest`.
    """
    if inspect.iscoroutinefunction(method):
        msg = "A reactive method must be synchronous"
        raise TypeError(msg)
    setattr(method, _MARK, True)
    _enable()
    return method


def start_reactions(root: View) -> None:
    """Run the reactive methods of `root` and its children once, recording their inputs.

    The application calls it. A view set later in a field of a started view, e.g. a list's
    item, starts its own. A method started already isn't run again.
    """
    if not _State.enabled:
        return
    with batch():
        views: deque[View] = deque([root])
        while len(views) > 0:
            view = views.popleft()
            reactions: dict[str, _Reaction] = view.__dict__.setdefault(_REACTIONS, {})
            for name, method in _reactive_methods(type(view)).items():
                if name not in reactions:
                    reactions[name] = reaction = _Reaction(view, method)
                    _schedule(reaction)
            views.extend(view.children_views)


def stop_reactions(root: View) -> None:
    """Stop the reactive methods of `root` and its children: forget their inputs.

    A web session stops its main view's when it ends, and a view removed from a started
    view's field stops its own.
    """
    views: deque[View] = deque([root])
    while len(views) > 0:
        view = views.popleft()
        for reaction in view.__dict__.pop(_REACTIONS, {}).values():
            reaction.stop()
        views.extend(view.children_views)


def follow(owner: View, name: str, function: Callable[[], None]) -> None:
    """Run `function` now, and again each time an input that it read changes, as a method.

    For ComposeUI's helpers, e.g. `Task.show_state`: they follow their inputs as a view's
    reactive methods do, and `reactive_inputs` lists them under `name`. It stops with
    `owner`'s methods (see `stop_reactions`), and a view started again later doesn't start
    it again.
    """
    _enable()
    reaction = _Reaction(owner, lambda _owner: function(), name)
    reactions: dict[str, _Reaction] = owner.__dict__.setdefault(_REACTIONS, {})
    # a helper may follow several times on one view: "shows", then "shows 2"
    key, count = name, 1
    while key in reactions:
        count += 1
        key = f"{name} {count}"
    reactions[key] = reaction
    with batch():
        _schedule(reaction)


def reactive_inputs(view: View) -> dict[str, list[str]]:
    """Get the inputs that each reactive method of `view` read in its last run, to debug it.

    By method name: a field as its path from `view`, e.g. ``filters.hour.value``, and a
    task by its function's name.
    """
    paths = _paths(view)
    return {
        # a child view read on the way to its fields: they say more
        name: [
            reaction_input.label(paths)
            for reaction_input in reaction.inputs
            if not reaction_input.holds_view
        ]
        for name, reaction in view.__dict__.get(_REACTIONS, {}).items()
    }


@contextmanager
def batch() -> Generator[None]:
    """Run the reactions to the changes made in the block once, after the outermost block.

    Even after an error in the block: the changes made before it stay.
    """
    if _PENDING.get() is not None:
        yield
        return
    pending: dict[_Reaction, None] = {}
    token = _PENDING.set(pending)
    try:
        yield
    finally:
        try:
            _flush(pending)
        finally:
            _PENDING.reset(token)


@contextmanager
def untracked() -> Generator[None]:
    """Record no read in the block: ComposeUI's own reads aren't a method's inputs."""
    token = _TRACKING.set(None)
    try:
        yield
    finally:
        _TRACKING.reset(token)


def is_enabled() -> bool:
    """Get whether a reactive method exists, so that changes are batched and reads tracked."""
    return _State.enabled


class Source:
    """An input of reactive methods: a view's field, or a task's state."""

    __slots__ = ("__weakref__", "_label", "_readers", "holds_view")

    def __init__(self, label: Callable[[dict[int, str]], str]) -> None:
        # weak keys: a dropped view's reactions go; the run order is the start order
        self._readers: weakref.WeakKeyDictionary[_Reaction, None] = weakref.WeakKeyDictionary()
        self._label = label
        #: whether a reaction read a child view from it
        self.holds_view = False

    def read(self) -> None:
        """Record that the reaction running, if any, reads this input."""
        reaction = _TRACKING.get()
        if reaction is not None:
            self._readers[reaction] = None
            reaction.inputs[self] = None

    def changed(self) -> None:
        """Run again the reactions that read this input, once the batch is over."""
        if len(self._readers) == 0:
            return
        with batch():
            for reaction in tuple(self._readers):
                _schedule(reaction)

    def label(self, paths: dict[int, str]) -> str:
        return self._label(paths)


def register_view_class(cls: type[Any]) -> None:
    """Track the reads of `cls`'s fields once a reactive method exists (`define_view` calls it)."""
    _State.view_classes.append(cls)
    if _State.enabled:
        _track_fields(cls)


def register_types(view_type: type[Any], *not_inputs: type[Any]) -> None:
    """Know the view class, and record no read of a field holding one of `not_inputs`.

    `view` calls it, e.g. with the signal class.
    """
    _State.view_type = view_type
    _State.view_holders = (view_type, list, tuple)
    _State.not_inputs = not_inputs


def check_write(view: View, name: str) -> None:
    """Refuse the change of a field by the reactive method running, if it read the field."""
    source = view.__dict__.get(_SOURCES, {}).get(name)
    if source is not None:
        check_change(
            source,
            f"sets {type(view).__name__}.{name}",
            instead="Set it from a signal's callback instead",
        )


def check_change(source: Source, change: str, instead: str = "") -> None:
    """Refuse the `change` of `source` by a reactive method that read it in its run.

    `instead` tells what to write in its place.
    """
    reaction = _RUNNING.get()
    if reaction is not None and source in reaction.inputs:
        msg = (
            f"The reactive method {reaction.name} {change}, which it reads: it would run"
            " again each time"
        )
        if instead:
            msg = f"{msg}. {instead}"
        raise ReactiveLoopError(msg)


#: the start order of the reactions: they run in it
_START_ORDER = itertools.count()


class _Reaction:
    __slots__ = ("__weakref__", "function", "inputs", "name", "order", "owner", "stopped")

    def __init__(
        self, owner: View, function: Callable[[Any], None], name: str | None = None
    ) -> None:
        # tree order, then the class's, as `start_reactions` builds them
        self.order = next(_START_ORDER)
        self.owner = weakref.ref(owner)
        self.function = function
        self.name = function.__qualname__ if name is None else name
        # ordered: `reactive_inputs` lists them as read
        self.inputs: dict[Source, None] = {}
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True
        self._forget_inputs()

    def run(self) -> None:
        owner = self.owner()
        if self.stopped or owner is None:
            return
        self._forget_inputs()
        tracking = _TRACKING.set(self)
        running = _RUNNING.set(self)
        try:
            self.function(owner)
        finally:
            _RUNNING.reset(running)
            _TRACKING.reset(tracking)

    def _forget_inputs(self) -> None:
        for source in self.inputs:
            source._readers.pop(self, None)  # noqa: SLF001 (the reaction's own registration)
        self.inputs.clear()


class _FieldReader:
    """A view field read through it while reactions run: the read is an input of the one running.

    Its `__get__` and `__set__` exist only then (`_recording_reads`). Without them, a read
    finds the value in the view's ``__dict__``, and a write stores it there, without calling
    Python, as before a reactive method existed: `__init__` sets each field that way. The
    class's ``__setattr__`` finds the changes (`_track_fields`), and `set_value` those that
    a hook makes.
    """

    __slots__ = ("name",)

    def __init__(self, name: str) -> None:
        self.name = name


def _store_field(self: _FieldReader, instance: Any, value: Any) -> None:
    """`_FieldReader.__set__` while reactions run: a data descriptor's, which `__get__` needs."""
    instance.__dict__[self.name] = value


def _read_field(self: _FieldReader, instance: Any, _owner: Any = None) -> Any:
    """`_FieldReader.__get__` while reactions run: record the read."""
    if instance is None:  # pragma: no cover (a class's field, read in a reactive method)
        return self  # as outside one
    try:
        value = instance.__dict__[self.name]
    except KeyError:  # pragma: no cover (attrs sets each field: kept for `hasattr`)
        raise AttributeError(self.name) from None
    if _TRACKING.get() is not None and not isinstance(value, _State.not_inputs):
        source = field_source(instance, self.name)
        # a child view replaced is a change of what the method reads through it
        if isinstance(value, _State.view_type):
            source.holds_view = True
        source.read()
    return value


def field_source(view: View, name: str) -> Source:
    """Get the input that the field `name` of `view` is to reactive methods."""
    sources: dict[str, Source] = view.__dict__.setdefault(_SOURCES, {})
    source = sources.get(name)
    if source is None:
        reference = weakref.ref(view)

        def label(paths: dict[int, str]) -> str:
            current = reference()
            if current is None:
                return name
            path = paths.get(id(current))
            if path is None:
                return f"{type(current).__name__}.{name}"
            return f"{path}.{name}" if path != "" else name

        sources[name] = source = Source(label)
    return source


def _differs(old: Any, new: Any) -> bool:
    if old is new:
        return False
    # e.g. a frame's `==` compares cell by cell: other values change when replaced
    if isinstance(old, _PLAIN) and type(old) is type(new):
        return bool(old != new)
    return True


def _enable() -> None:
    if _State.enabled:
        return
    _State.enabled = True
    for cls in _State.view_classes:
        _track_fields(cls)


def _track_fields(cls: type[Any]) -> None:
    import attrs  # noqa: PLC0415 (only once a reactive method exists)

    for field in attrs.fields(cls):
        if not field.name.startswith("_") and field.name != "renderer":
            type.__setattr__(cls, field.name, _FieldReader(field.name))
    # attrs's, which runs the fields' hooks: `define_view` always gives it one
    set_field = cls.__dict__["__setattr__"]

    def set_attribute(view: View, name: str, value: Any) -> None:
        values = view.__dict__
        if _SOURCES in values or _TRACKING.get() is not None:
            _set_watched(view, name, value, set_field)
            return
        # no method reads this view's fields, and no reads are recorded: a write costs one
        # call more only, a field is set often
        old = values.get(name)
        set_field(view, name, value)
        if (
            _REACTIONS in values
            and old is not value
            and (isinstance(old, _State.view_holders) or isinstance(value, _State.view_holders))
        ):
            _replace_views(old, value)

    type.__setattr__(cls, "__setattr__", set_attribute)


def _set_watched(
    view: View, name: str, value: Any, set_field: Callable[[View, str, Any], None]
) -> None:
    """Set the field `name` of a view that a method reads, or of any view while one runs.

    `batch` and `untracked` without their context managers: a field is set often.
    """
    if _RUNNING.get() is not None:
        check_write(view, name)
    pending: dict[_Reaction, None] = {}
    batching = _PENDING.set(pending) if _PENDING.get() is None else None
    # the hooks' reads, e.g. the renderer's old value, aren't the method's inputs
    tracking = _TRACKING.set(None) if _TRACKING.get() is not None else None
    values = view.__dict__
    old = values.get(name)
    try:
        set_field(view, name, value)
        source = values.get(_SOURCES, {}).get(name)
        if source is not None and _differs(old, values[name]):
            source.changed()
        if _REACTIONS in values and old is not value:
            _replace_views(old, value)
    finally:
        if tracking is not None:
            _TRACKING.reset(tracking)
        if batching is not None:
            # even if a hook failed: the fields that it set before stay
            try:
                if len(pending) > 0:
                    _flush(pending)
            finally:
                _PENDING.reset(batching)


def set_value(view: object, name: str, value: Any) -> None:
    """Set the field `name` of `view` without its hooks, e.g. from another field's hook.

    The reactive methods that read it run again, as after a write of the field.
    """
    values = view.__dict__
    old = values.get(name)
    values[name] = value
    sources = values.get(_SOURCES)
    if sources is not None:
        source = sources.get(name)
        if source is not None and _differs(old, value):
            source.changed()


def _replace_views(old: Any, new: Any) -> None:
    """Stop the methods of the views that `old` held and `new` doesn't; start the new ones'."""
    old_views, new_views = _views_in(old), _views_in(new)
    kept = {id(view) for view in new_views}
    for view in old_views:
        if id(view) not in kept:
            stop_reactions(view)
    olds = {id(view) for view in old_views}
    for view in new_views:
        if id(view) not in olds:
            start_reactions(view)


def _views_in(value: Any) -> list[View]:
    """Get the views that a field's `value` holds: a view, or a list of them, e.g. a list's."""
    if isinstance(value, _State.view_type):
        return [value]
    # the first item only, so that a long list of other values costs nothing
    if (
        isinstance(value, (list, tuple))
        and len(value) > 0
        and isinstance(value[0], _State.view_type)
    ):
        return [view for view in value if isinstance(view, _State.view_type)]
    return []


def _reactive_methods(cls: type[Any]) -> dict[str, Callable[[Any], None]]:
    methods: dict[str, Callable[[Any], None]] = {}
    for base in reversed(cls.__mro__):
        for name, value in vars(base).items():
            if getattr(value, _MARK, False):
                methods[name] = value
            else:
                # a subclass's plain method replaces a reactive one of its base
                methods.pop(name, None)
    return methods


def _schedule(reaction: _Reaction) -> None:
    """Run `reaction` once the current batch is over: its callers open one."""
    pending = _PENDING.get()
    assert pending is not None
    pending[reaction] = None


@contextmanager
def _recording_reads() -> Generator[None]:
    """Record the reads of view fields in the block: give `_FieldReader` its `__get__`.

    And its `__set__`: only a data descriptor's `__get__` comes before the view's
    ``__dict__``. For all the views at once, in one class attribute; until the last block
    ends, in any thread. Another thread's reads meanwhile aren't recorded: no reaction of
    theirs runs.
    """
    with _State.lock:
        if _State.running_batches == 0:
            _FieldReader.__get__ = _read_field  # type: ignore[attr-defined]
            _FieldReader.__set__ = _store_field  # type: ignore[attr-defined]
        _State.running_batches += 1
    try:
        yield
    finally:
        with _State.lock:
            _State.running_batches -= 1
            if _State.running_batches == 0:
                del _FieldReader.__get__  # type: ignore[attr-defined]
                del _FieldReader.__set__  # type: ignore[attr-defined]


def _flush(pending: dict[_Reaction, None]) -> None:
    """Run the `pending` reactions, and those they make pending, then raise the first error.

    One method's error doesn't keep the others from showing the change.
    """
    if len(pending) == 0:
        return
    with _recording_reads():
        _run_all(pending)


def _run_all(pending: dict[_Reaction, None]) -> None:
    """Run the `pending` reactions in their start order, and those they make pending."""
    runs: dict[_Reaction, int] = {}
    error: Exception | None = None
    # by start order: the orders are unique, so the reactions are never compared
    queue: list[tuple[int, _Reaction]] = []
    queued: set[_Reaction] = set()

    def take_pending() -> None:
        for reaction in pending:
            if reaction not in queued:
                queued.add(reaction)
                heapq.heappush(queue, (reaction.order, reaction))
        pending.clear()

    take_pending()
    while len(queue) > 0:
        _order, reaction = heapq.heappop(queue)
        queued.discard(reaction)
        runs[reaction] = runs.get(reaction, 0) + 1
        if runs[reaction] > _MAX_RUNS:
            msg = (
                f"The reactive method {reaction.name} ran {_MAX_RUNS} times for one change:"
                " reactive methods keep changing each other's inputs"
            )
            raise ReactiveLoopError(msg)
        try:
            reaction.run()
        except Exception as raised:  # raised once the others ran
            if error is None:
                error = raised
            else:  # only one is raised: the others aren't lost
                LOGGER.exception("The reactive method %s failed too", reaction.name)
        take_pending()
    if error is not None:
        raise error


def _paths(root: View) -> dict[int, str]:
    """Get the path of each view under `root`, and of each task in their attributes, by id."""
    import attrs  # noqa: PLC0415 (only to debug)

    from composeui.core.jobs import Task  # noqa: PLC0415 (it imports this module)
    from composeui.core.view import View  # noqa: PLC0415 (it imports this module)

    paths: dict[int, str] = {id(root): ""}
    views: deque[tuple[View, str]] = deque([(root, "")])
    while len(views) > 0:
        view, path = views.popleft()
        names = [f.name for f in attrs.fields(cast("type[AttrsInstance]", type(view)))]
        names.extend(name for name in view.__dict__ if name not in names)
        for name in names:
            value = view.__dict__.get(name)
            child_path = f"{path}.{name}" if path != "" else name
            if isinstance(value, View) and id(value) not in paths:
                paths[id(value)] = child_path
                views.append((value, child_path))
            elif isinstance(value, Task) and id(value) not in paths:
                paths[id(value)] = child_path
    return paths

"""Opt-in reactions to view fields and task-state notifications."""

from __future__ import annotations

import contextvars
import inspect
import weakref
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, TypeVar

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from composeui.core.view import View

_T = TypeVar("_T")
_MAX_RUNS = 100
_CURRENT: contextvars.ContextVar[_Reaction | None] = contextvars.ContextVar(
    "composeui_reaction", default=None
)
_UPDATES: contextvars.ContextVar[_Updates | None] = contextvars.ContextVar(
    "composeui_updates", default=None
)


class ReactiveCycleError(RuntimeError):
    """A group of reactions did not settle within 100 runs of one method."""


def reactive(method: Callable[[_T], None]) -> Callable[[_T], None]:
    """Mark a synchronous view method to rerun when the observable values it reads change.

    Call `View.activate_reactions` after initialization or model setup. Reads of view
    fields and task state are tracked on every run, including reads in helper functions.
    Keep actions such as starting jobs, saving files and showing dialogs in callbacks.
    """
    if inspect.iscoroutinefunction(method):
        msg = "Reactive methods must be synchronous"
        raise TypeError(msg)
    method.__composeui_reactive__ = True  # type: ignore[attr-defined]
    return method


class _Dependency:
    def __init__(self) -> None:
        self.reactions: weakref.WeakSet[_Reaction] = weakref.WeakSet()

    def read(self, reaction: _Reaction) -> None:
        self.reactions.add(reaction)
        reaction.dependencies.add(self)

    def changed(self) -> None:
        with batch_updates():
            updates = _UPDATES.get()
            assert updates is not None
            for reaction in tuple(self.reactions):
                updates.pending[reaction] = None


class _Updates:
    def __init__(self) -> None:
        self.pending: dict[_Reaction, None] = {}

    def flush(self) -> None:
        runs: dict[_Reaction, int] = {}
        while self.pending:
            reaction = next(iter(self.pending))
            del self.pending[reaction]
            runs[reaction] = runs.get(reaction, 0) + 1
            if runs[reaction] > _MAX_RUNS:
                msg = f"Reactive cycle involving {reaction.method.__qualname__}"
                raise ReactiveCycleError(msg)
            reaction.run()


@contextmanager
def batch_updates() -> Iterator[None]:
    """Defer reactions until the outermost batch completes, then settle them synchronously.

    Assignments are not rolled back on an error. Pending reactions are discarded when
    the batch fails. Batches are local to the current context, not a thread-safety lock.
    """
    if _UPDATES.get() is not None:
        yield
        return
    updates = _Updates()
    token = _UPDATES.set(updates)
    try:
        yield
        updates.flush()
    finally:
        _UPDATES.reset(token)


@contextmanager
def untracked() -> Iterator[None]:
    """Exclude framework reads from the current reaction's dependencies."""
    token = _CURRENT.set(None)
    try:
        yield
    finally:
        _CURRENT.reset(token)


def read_field(view: View, name: str) -> None:
    reaction = _CURRENT.get()
    if reaction is not None and not name.startswith("_"):
        fields = object.__getattribute__(view, "__attrs_attrs__")
        if any(field.name == name for field in fields):
            sources = view.__dict__.setdefault("_reactive_sources", {})
            sources.setdefault(name, _Dependency()).read(reaction)


def field_source(instance: Any, name: str) -> _Dependency | None:
    return getattr(instance, "__dict__", {}).get("_reactive_sources", {}).get(name)


def track_signal(signal: Any) -> None:
    reaction = _CURRENT.get()
    if reaction is not None:
        source = signal.__dict__.setdefault("_reactive_source", _Dependency())
        source.read(reaction)


def notify_signal(signal: Any) -> None:
    source = signal.__dict__.get("_reactive_source")
    if source is not None:
        source.changed()


class _Reaction:
    def __init__(self, owner: View, method: Callable[[Any], None]) -> None:
        self.owner = weakref.ref(owner)
        self.method = method
        self.dependencies: set[_Dependency] = set()
        self.active = True

    def disconnect(self) -> None:
        self.active = False
        for dependency in self.dependencies:
            dependency.reactions.discard(self)
        self.dependencies.clear()

    def run(self) -> None:
        owner = self.owner()
        if not self.active or owner is None:
            return
        for dependency in self.dependencies:
            dependency.reactions.discard(self)
        self.dependencies.clear()
        token = _CURRENT.set(self)
        try:
            self.method(owner)
        finally:
            _CURRENT.reset(token)


def activate(view: View) -> None:
    reactions = view.__dict__.setdefault("_reactions", {})
    methods: dict[str, Any] = {}
    for cls in reversed(type(view).__mro__):
        methods.update(vars(cls))
    with batch_updates():
        updates = _UPDATES.get()
        assert updates is not None
        for name, method in methods.items():
            if getattr(method, "__composeui_reactive__", False) and name not in reactions:
                reaction = _Reaction(view, method)
                reactions[name] = reaction
                updates.pending[reaction] = None


def refresh_tree(view: View) -> None:
    with batch_updates():
        updates = _UPDATES.get()
        assert updates is not None
        for reaction in view.__dict__.get("_reactions", {}).values():
            updates.pending[reaction] = None
        for child in view.children_views:
            refresh_tree(child)


def stop(view: View) -> None:
    for reaction in view.__dict__.pop("_reactions", {}).values():
        reaction.disconnect()

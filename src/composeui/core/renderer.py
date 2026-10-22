"""The base classes of the renderers, which show a view with a widget of a toolkit."""

from __future__ import annotations

import contextlib
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, ClassVar, Generic, TypeVar

from typing_extensions import Protocol

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Mapping
    from pathlib import Path


class ViewLike(Protocol):
    """What a renderer needs of every view: whether it is visible and enabled."""

    is_visible: bool
    is_enabled: bool


TView = TypeVar("TView", bound=ViewLike)
TObject = TypeVar("TObject")


class NoRenderedObjectError(Exception):
    """A renderer used before `Renderer.render` built its widget."""

    def __init__(self) -> None:
        super().__init__(
            "Cannot access rendered object because nothing has been rendered yet. "
            "Call `render()` first."
        )


class MissingRefreshAttributeFunctionError(Exception):
    """A changed field of a view that its renderer has no handler for."""

    def __init__(self, renderer: Renderer[Any, Any], attr_name: str) -> None:
        super().__init__(
            f"The attribute {attr_name} don't have a corresponding "
            f"refresh function in {type(renderer)}"
        )


class Renderer(ABC, Generic[TView, TObject]):
    """The base of a backend's renderers: one shows a view with a widget of its toolkit.

    `render` builds the widget. `refresh_attribute` shows a new value of a field of the view,
    with the handler of `_refresh_dispatcher` for that field. `update_state` copies the state
    of the widget into the view.
    """

    def __init__(self, view: TView) -> None:
        self._view = view
        self._rendered_object: TObject | None = None
        self._refresh_dispatcher: dict[str, Callable[[TView, TObject, Any], None]] = {}
        self._is_updating_state = False

    def has_attr(self, attr_name: str) -> bool:
        """Check if the attribute has an associated refresh function."""
        return attr_name in self._refresh_dispatcher

    def is_updating_state(self) -> bool:
        return self._is_updating_state

    def call_on_main_thread(self, callback: Callable[[], None]) -> None:
        """Invoke `callback` on the thread that owns the GUI event loop.

        Default: no real thread affinity to worry about outside a GUI toolkit, so
        just call it directly. Toolkit-bound renderers (e.g. Qt, whose widgets can
        only be touched from the thread that created them) must override this to
        marshal the call onto their main thread instead.
        """
        callback()

    @abstractmethod
    def render(self) -> None:
        """Build the widget that shows the view."""

    def refresh(self) -> None:
        """Show every field of the view that has a handler in `_refresh_dispatcher`."""
        if self._rendered_object is None:
            raise NoRenderedObjectError
        for attr_name in self._refresh_dispatcher:
            if not hasattr(self._view, attr_name):
                msg = f"{attr_name} is not an attribute of the view {type(self._view).__name__}"
                raise AttributeError(msg)
            refresh = self._refresh_dispatcher[attr_name]
            value = getattr(self._view, attr_name)
            refresh(self._view, self._rendered_object, value)

    def refresh_attribute(self, attr_name: str, value: Any) -> None:
        """Show `value`, the new value of the view's field `attr_name`.

        Raises `MissingRefreshAttributeFunctionError` when no handler shows the field.
        """
        if self._rendered_object is None:
            raise NoRenderedObjectError
        if hasattr(self._view, attr_name):
            if attr_name in self._refresh_dispatcher:
                refresh = self._refresh_dispatcher[attr_name]
                refresh(self._view, self._rendered_object, value)
            else:
                raise MissingRefreshAttributeFunctionError(self, attr_name)
        else:
            msg = f"{attr_name} is not an attribute of the view {type(self._view)}"
            raise AttributeError(msg)

    def update_state(self) -> None:
        """Copy the state of the widget into the view."""
        if self._rendered_object is None:
            raise NoRenderedObjectError
        with self.stop_refresh():
            self._update_state(self._view, self._rendered_object)

    @contextlib.contextmanager
    def stop_refresh(self) -> Generator[None]:
        self._is_updating_state = True
        try:
            yield
        finally:
            self._is_updating_state = False

    @staticmethod
    @abstractmethod
    def _update_state(view: TView, rendered_object: TObject) -> None: ...


class MainRenderer(Renderer[TView, TObject]):
    """A root-window renderer: the app-level operations a `MainView` relies on.

    Lets `MainView` talk to whichever backend rendered it through `isinstance`
    checks against this class alone, without importing any backend package.
    """

    #: whether the app's window is drawn on the main thread, which long work there
    #: freezes (Qt, Textual): a view then runs it in a job. The web's requests have
    #: threads of their own
    draws_on_main_thread: ClassVar[bool] = True

    @abstractmethod
    def close(self) -> None:
        """Close the application."""

    @abstractmethod
    def open_file(self) -> Path | None:
        """Ask the user for an existing file path, blocking until answered."""

    @abstractmethod
    def save_file(self) -> Path | None:
        """Ask the user for a file path to save to, blocking until answered."""


class RendererContainer(Generic[TView]):
    """The renderers of a view shown by several widgets, e.g. a form row's label and field."""

    def __init__(self, view: TView, renderers: Mapping[str, Renderer[TView, Any]]) -> None:
        self._view = view
        self._renderers = dict(renderers)

    def is_updating_state(self) -> bool:
        return any(r.is_updating_state() for r in self._renderers.values())

    def call_on_main_thread(self, callback: Callable[[], None]) -> None:
        """Invoke `callback` on the thread that owns the GUI event loop.

        Delegates to a bound renderer: every renderer in the container shares the same
        toolkit and thread. Falls back to a direct call if no renderer is bound yet.
        """
        renderer = next(iter(self._renderers.values()), None)
        if renderer is not None:
            renderer.call_on_main_thread(callback)
        else:
            callback()

    def get_renderer(self, name: str) -> Renderer[TView, Any]:
        return self._renderers[name]

    @property
    def renderers(self) -> list[Renderer[TView, Any]]:
        return list(self._renderers.values())

    def render(self) -> None:
        """Build the widgets of every renderer."""
        for renderer in self._renderers.values():
            renderer.render()

    def refresh(self) -> None:
        """Show every field of the view that a renderer has a handler for."""
        if len(self._renderers) == 0:
            raise NoRenderedObjectError
        for renderer in self._renderers.values():
            renderer.refresh()

    def refresh_attribute(self, attr_name: str, value: Any) -> None:
        """Show `value` with each renderer that has a handler for the field `attr_name`."""
        if len(self._renderers) == 0:
            raise NoRenderedObjectError
        for renderer in self._renderers.values():
            if renderer.has_attr(attr_name):
                renderer.refresh_attribute(attr_name, value)

    def update_state(self) -> None:
        """Copy the state of every widget into the view."""
        if len(self._renderers) == 0:
            raise NoRenderedObjectError
        for renderer in self._renderers.values():
            renderer.update_state()

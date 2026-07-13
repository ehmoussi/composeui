from __future__ import annotations

import contextlib
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from typing_extensions import Protocol

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Mapping
    from pathlib import Path


class ViewLike(Protocol):
    is_visible: bool
    is_enabled: bool


TView = TypeVar("TView", bound=ViewLike)
TObject = TypeVar("TObject")


class NoRenderedObjectError(Exception):
    def __init__(self) -> None:
        super().__init__(
            "Cannot access rendered object because nothing has been rendered yet. "
            "Call `render()` first."
        )


class MissingRefreshAttributeFunctionError(Exception):
    def __init__(self, renderer: Renderer[Any, Any], attr_name: str) -> None:
        super().__init__(
            f"The attribute {attr_name} don't have a corresponding "
            f"refresh function in {type(renderer)}"
        )


class Renderer(ABC, Generic[TView, TObject]):
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
        """Render the view in the appropriate framework."""

    def refresh(self) -> None:
        """Refresh the framework view object using the view state."""
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
        """Refresh the framework view object using the view state."""
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
        """Update the state of the view using framework view object."""
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
    def __init__(self, view: TView, renderers: Mapping[str, Renderer[TView, Any]]) -> None:
        self._view = view
        self._renderers = dict(renderers)

    def is_updating_state(self) -> bool:
        return any(r.is_updating_state() for r in self._renderers.values())

    def call_on_main_thread(self, callback: Callable[[], None]) -> None:
        """Invoke `callback` on the thread that owns the GUI event loop.

        Delegates to a bound renderer, since every renderer in the container shares
        the same underlying toolkit/thread; falls back to a direct call if none is
        bound yet.
        """
        renderer = next(iter(self._renderers.values()), None)
        if renderer is not None:
            renderer.call_on_main_thread(callback)
        else:
            callback()

    def get_renderer(self, name: str) -> Renderer[TView, Any]:
        return self._renderers[name]

    def render(self) -> None:
        """Render the view in the appropriate framework."""
        for renderer in self._renderers.values():
            renderer.render()

    def refresh(self) -> None:
        """Refresh the framework view object using the view state."""
        if len(self._renderers) == 0:
            raise NoRenderedObjectError
        for renderer in self._renderers.values():
            renderer.refresh()

    def refresh_attribute(self, attr_name: str, value: Any) -> None:
        """Refresh the framework view object using the view state."""
        if len(self._renderers) == 0:
            raise NoRenderedObjectError
        for renderer in self._renderers.values():
            if renderer.has_attr(attr_name):
                renderer.refresh_attribute(attr_name, value)

    def update_state(self) -> None:
        """Update the state of the view using framework view object."""
        if len(self._renderers) == 0:
            raise NoRenderedObjectError
        for renderer in self._renderers.values():
            renderer.update_state()

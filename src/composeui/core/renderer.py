"""The base classes of the renderers, which show a view with a widget of a toolkit."""

from __future__ import annotations

import contextlib
from abc import ABCMeta, abstractmethod
from types import MappingProxyType, MethodType
from typing import TYPE_CHECKING, Any, ClassVar, Generic, TypeVar

from typing_extensions import Protocol

from composeui.core.reactivity import batch

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Mapping
    from pathlib import Path
    from typing import Optional

    from composeui.core.view import DownloadedFile

    #: for each field in order, the function of the renderer's method showing it, or None
    #: for a handler of the renderer's own
    _HandlerTable = tuple[tuple[str, Optional[Callable[..., None]]], ...]

__all__ = [
    "MainRenderer",
    "MissingRefreshAttributeFunctionError",
    "NoRenderedObjectError",
    "Renderer",
    "RendererContainer",
    "ViewLike",
]


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


#: the handler tables the renderers share, by their content
_NO_HANDLERS: Mapping[str, Any] = MappingProxyType({})
_HANDLER_TABLES: dict[_HandlerTable, dict[str, Callable[..., None] | None]] = {}


class _RendererMeta(ABCMeta):
    """Shares a renderer's handlers once its `__init__`, and its subclasses', registered them."""

    def __call__(cls, *args: Any, **kwargs: Any) -> Any:
        renderer = super().__call__(*args, **kwargs)
        renderer._share_handlers()  # noqa: SLF001
        return renderer


class Renderer(Generic[TView, TObject], metaclass=_RendererMeta):
    """The base of a backend's renderers: one shows a view with a widget of its toolkit.

    `render` builds the widget. `refresh_attribute` shows a new value of a field of the view,
    with the handler of `_refresh_dispatcher` for that field. The renderer sets the view's
    fields from the widget's signals, inside `stop_refresh`, so the view doesn't show them
    back.
    """

    #: none until the renderer is built: no handler runs during `__init__`
    _shared_handlers: Mapping[str, Callable[..., None] | None] = _NO_HANDLERS
    _own_handlers: Mapping[str, Callable[..., None]] = _NO_HANDLERS

    def __init__(self, view: TView) -> None:
        self._view = view
        self._rendered_object: TObject | None = None
        self._refresh_dispatcher: dict[str, Callable[[TView, TObject, Any], None]] = {}
        self._is_updating_state = False

    def _share_handlers(self) -> None:
        """Move the handlers of `_refresh_dispatcher` to the shared table and `_own_handlers`."""
        # its handlers are mostly its own methods, the same for each renderer of its class: a
        # page has a renderer per widget, and a web session a page. It shares a table with
        # the renderers registering the same methods for the same fields; only the others,
        # e.g. a lambda, stay its own
        own: dict[str, Callable[..., None]] = {}
        key: list[tuple[str, Callable[..., None] | None]] = []
        for name, handler in self._refresh_dispatcher.items():
            if isinstance(handler, MethodType) and handler.__self__ is self:
                key.append((name, handler.__func__))
            else:
                key.append((name, None))
                own[name] = handler
        table = tuple(key)
        self._shared_handlers = _HANDLER_TABLES.setdefault(table, dict(table))
        if own:
            self._own_handlers = own
        # read-only: a handler registered after `__init__` would be lost. Not `del`, which
        # would cost each renderer the dict of attribute names it shares with its class's
        self._refresh_dispatcher = _NO_HANDLERS  # type: ignore[assignment]

    def _handler(self, attr_name: str) -> Callable[[TView, TObject, Any], None]:
        function = self._shared_handlers[attr_name]
        if function is None:
            return self._own_handlers[attr_name]
        return MethodType(function, self)

    def has_attr(self, attr_name: str) -> bool:
        """Check if the attribute has an associated refresh function."""
        return attr_name in self._shared_handlers

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

    def post_on_main_thread(self, callback: Callable[[], None]) -> None:
        """Have `callback` run on the GUI's thread, in order, if possible without waiting for it.

        For a job's thread, which may hold a lock that the callback needs. Default: as
        `call_on_main_thread`. A renderer whose `call_on_main_thread` waits overrides it.
        """
        self.call_on_main_thread(callback)

    @abstractmethod
    def render(self) -> None:
        """Build the widget that shows the view."""

    def refresh(self) -> None:
        """Show every field of the view that has a handler in `_refresh_dispatcher`."""
        if self._rendered_object is None:
            raise NoRenderedObjectError
        for attr_name in self._shared_handlers:
            if not hasattr(self._view, attr_name):
                msg = f"{attr_name} is not an attribute of the view {type(self._view).__name__}"
                raise AttributeError(msg)
            refresh = self._handler(attr_name)
            value = getattr(self._view, attr_name)
            refresh(self._view, self._rendered_object, value)

    def refresh_attribute(self, attr_name: str, value: Any) -> None:
        """Show `value`, the new value of the view's field `attr_name`.

        Raises `MissingRefreshAttributeFunctionError` when no handler shows the field.
        """
        if self._rendered_object is None:
            raise NoRenderedObjectError
        if hasattr(self._view, attr_name):
            if attr_name in self._shared_handlers:
                refresh = self._handler(attr_name)
                refresh(self._view, self._rendered_object, value)
            else:
                raise MissingRefreshAttributeFunctionError(self, attr_name)
        else:
            msg = f"{attr_name} is not an attribute of the view {type(self._view)}"
            raise AttributeError(msg)

    @contextlib.contextmanager
    def stop_refresh(self) -> Generator[None]:
        # the reactive methods run after the block: the changes they make to this view
        # reach its widget, which the block keeps from being refreshed
        with batch():
            self._is_updating_state = True
            try:
                yield
            finally:
                self._is_updating_state = False


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

    @abstractmethod
    def download(self, file: DownloadedFile) -> None:
        """Give the user `file`, as `MainView.download` says; don't wait."""


class RendererContainer(Generic[TView]):
    """The renderers of a view shown by several widgets, e.g. a form row's label and field."""

    def __init__(self, view: TView, renderers: Mapping[str, Renderer[TView, Any]]) -> None:
        self._view = view
        self._renderers = dict(renderers)

    def is_updating_state(self) -> bool:
        return any(r.is_updating_state() for r in self._renderers.values())

    def call_on_main_thread(self, callback: Callable[[], None]) -> None:
        """Invoke `callback` on the thread that owns the GUI event loop.

        Delegates to one of its renderers: they all share the same toolkit and thread.
        """
        next(iter(self._renderers.values())).call_on_main_thread(callback)

    def post_on_main_thread(  # pragma: no cover (a main view, which `Jobs` asks, has one renderer)
        self, callback: Callable[[], None]
    ) -> None:
        """Have `callback` run on the GUI's thread, as `Renderer.post_on_main_thread` says."""
        next(iter(self._renderers.values())).post_on_main_thread(callback)

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
        for renderer in self._renderers.values():
            renderer.refresh()

    def refresh_attribute(self, attr_name: str, value: Any) -> None:
        """Show `value` with each renderer that has a handler for the field `attr_name`."""
        for renderer in self._renderers.values():
            if renderer.has_attr(attr_name):
                renderer.refresh_attribute(attr_name, value)

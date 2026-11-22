"""Web backend renderers: each view renders to an HTML fragment swapped in by htmx.

There is no live widget to mutate between requests, so a renderer's rendered object is
just the stable id of its fragment. Changing a view attribute marks the renderer dirty
in a request-scoped set (`collect_dirty`); the route then re-renders every dirty
fragment as an htmx out-of-band swap (`render_dirty`). A change made outside any request,
by a thread handing it over with `call_on_main_thread`, waits in its session's `pending`
for the next response.
"""

from __future__ import annotations

import contextlib
import re
from abc import abstractmethod
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    ClassVar,
    Final,
    TypeVar,
    cast,
)

from markupsafe import Markup
from typing_extensions import override

from composeui.core.renderer import (
    NoRenderedObjectError,
    Renderer,
    RendererContainer,
    ViewLike,
)
from composeui.core.view import (
    FormLabelRowView,
    FormRowView,
    NodeMark,
    View,
)
from composeui.webcore.changes import _DIRTY, collect_dirty
from composeui.webcore.icons import icon_url
from composeui.webcore.rendertarget import (
    _RENDER_TARGET,
    RenderTarget,
    call_in_session,
    rendering_into,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from composeui.webcore._renderers.forms import WebFormLabelRenderer


TView = TypeVar("TView", bound=ViewLike)

_ID_PATTERN = re.compile(r'\sid="([^"]+)"')


class UnsupportedEventError(Exception):
    def __init__(self, renderer: WebRenderer[Any], event: str) -> None:
        super().__init__(f"{type(renderer).__name__} does not handle the event {event!r}")


def render_dirty(dirty: Mapping[str, WebRenderer[Any]]) -> Markup:
    """Render every dirty fragment as an out-of-band swap.

    A fragment already contained in another dirty fragment (e.g. a row inside a group
    that also changed) is dropped, otherwise htmx would swap it twice. So is one not in
    the page (on a page not shown): its page brings it along once shown.
    """
    fragments = {
        widget_id: renderer.to_html(oob=True)
        for widget_id, renderer in dirty.items()
        if renderer.is_in_page
    }
    nested = {
        nested_id
        for widget_id, fragment in fragments.items()
        for nested_id in _ID_PATTERN.findall(fragment)
        if nested_id != widget_id
    }
    return Markup("").join(
        fragment for widget_id, fragment in fragments.items() if widget_id not in nested
    )


def handle_event(renderer: WebRenderer[Any], event: str, form: Mapping[str, str]) -> Markup:
    """Apply a browser event to `renderer`'s view and return the resulting OOB fragments."""
    with collect_dirty() as dirty:
        renderer.dispatch(event, form)
        return render_dirty(dirty)


class WebRenderer(Renderer[TView, str]):
    #: distinguishes the renderers a `RendererContainer` binds to one same view
    _role: ClassVar[str]
    #: whether a `<label for=...>` can point at the root element (a `<div>` can't)
    is_labelable: ClassVar[bool] = True
    #: whether the page draws it at its end, whatever holds it, as a dialog
    is_drawn_apart: ClassVar[bool] = False

    def __init__(self, view: TView) -> None:
        super().__init__(view)
        self._target: RenderTarget | None = None
        #: the container drawing this view, if it passes its enabled state on (`is_enabled`)
        self.parent: WebRenderer[Any] | None = None
        #: the renderers this one is the `parent` of
        self.children: list[WebRenderer[Any]] = []
        self._refresh_dispatcher.update(
            {
                "is_visible": self._mark_dirty,
                "is_enabled": self._refresh_enabled,
            }
        )

    @property
    def widget_id(self) -> str:
        if self._rendered_object is None:
            raise NoRenderedObjectError
        return self._rendered_object

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = f"cui-{id(self._view)}-{self._role}"
            target = _RENDER_TARGET.get()
            if target is not None:
                target.renderers[self._rendered_object] = self
                self._target = target

    @property
    def takes_events(self) -> bool:
        """Whether a browser's event may act on the view: enabled and shown, as its page says."""
        return self.is_enabled and self._is_view_shown

    @property
    def _is_view_shown(self) -> bool:
        return self._view.is_visible and (self.parent is None or self.parent._is_view_shown)  # noqa: SLF001

    @property
    def is_enabled(self) -> bool:
        """Whether the view and every container around it are enabled.

        As disabling a Qt or Textual container disables its children. The container
        swaps whole. So its views come back disabled with it, and so do the dialogs
        drawn apart from it (see `_refresh_enabled`).
        """
        return self._view.is_enabled and (self.parent is None or self.parent.is_enabled)

    @property
    def is_in_page(self) -> bool:
        """Whether the browser's page holds this view's fragment: not on a page or tab not shown."""
        renderer: WebRenderer[Any] = self
        # a dialog is drawn at the end of the page, with its content, whatever holds it
        while renderer.parent is not None and not renderer.is_drawn_apart:
            parent = renderer.parent
            if not parent.shows(renderer):
                return False
            renderer = parent
        return True

    def shows(self, _child: WebRenderer[Any]) -> bool:
        """Tell whether the page holds `_child`'s fragment, e.g. a router's page shown."""
        return True

    def _adopt(self, views: Iterable[View]) -> None:
        """Make this renderer the parent of `views`' renderers (see `is_enabled`)."""
        for view in views:
            renderer: Any = view.renderer
            if renderer is None:  # e.g. on a page not built yet (see `_BuiltWhenShown`)
                continue
            children = renderer.renderers if isinstance(renderer, RendererContainer) else [renderer]
            for child in children:
                if isinstance(child, WebRenderer) and child not in self.children:
                    child.parent = self
                    self.children.append(child)

    @override
    def call_on_main_thread(self, callback: Callable[[], None]) -> None:
        call_in_session(self._target, callback)

    def _in_session(self) -> contextlib.AbstractContextManager[None]:
        """Register the renderers built in the block into this one's session, if it has one."""
        return contextlib.nullcontext() if self._target is None else rendering_into(self._target)

    @abstractmethod
    def to_html(self, *, oob: bool = False) -> Markup:
        """Render the view's fragment; `oob` marks it as an htmx out-of-band swap."""

    def dispatch(self, event: str, form: Mapping[str, str]) -> None:
        """Apply a browser `event` (with its submitted `form` fields) to the view."""
        raise UnsupportedEventError(self, event)

    def _root_attributes(self, *, oob: bool) -> Markup:
        """Get the attributes of the fragment's root tag, kept even when hidden for later swaps.

        Its ``data-cui``, the kind of widget, is what an app's stylesheet selects it by
        (`WebStyle`): it stays when the markup changes.
        """
        attributes = [Markup('id="{}"').format(self.widget_id)]
        if not self._view.is_visible:
            attributes.append(Markup("hidden"))
        if oob:
            attributes.append(Markup('hx-swap-oob="true"'))
        attributes.append(Markup('data-cui="{}"').format(self._role))
        return Markup(" ").join(attributes)

    def _row_attributes(self) -> Markup:
        """ARIA links from a form row's field to the row's log and label.

        The field is described by the row's help, if any, and its log, read out with the
        field, and is `aria-invalid` while the log shows an error (the page script keeps
        that in step when only the log is swapped, see `page.js`). A field a `<label for>`
        can't name, a radio group or a checkbox, is labelled by the row's label instead.
        Nothing outside a row.
        """
        attributes: list[Markup] = []
        log = self._row_renderer("log")
        # a row's label is a form label's: a cast, so the base names no renderer at run time
        label = cast("WebFormLabelRenderer | None", self._row_renderer("label"))
        if log is not None:
            described_by = (
                f"{label.help_id} {log.widget_id}"
                if label is not None and label.has_help()
                else log.widget_id
            )
            attributes.append(Markup('aria-describedby="{}"').format(described_by))
            if isinstance(self._view, FormRowView) and self._view.is_invalid:
                attributes.append(Markup('aria-invalid="true"'))
        if not self.is_labelable and label is not None:
            attributes.append(Markup('aria-labelledby="{}"').format(label.text_id))
        return Markup("").join(Markup(" {}").format(attribute) for attribute in attributes)

    def _row_renderer(self, part: str) -> WebRenderer[Any] | None:
        """Get another renderer of the view's row, e.g. its "log", if it has one."""
        container = self._view.renderer  # type: ignore[attr-defined]
        if not isinstance(container, RendererContainer):
            return None
        try:
            renderer = container.get_renderer(part)
        except KeyError:
            return None
        assert isinstance(renderer, WebRenderer)  # a row's part, rendered by this backend
        return renderer

    def _refresh_enabled(self, view: TView, rendered_object: str, value: Any) -> None:
        self._mark_dirty(view, rendered_object, value)
        # the dialogs below, drawn at the end of the page rather than in this fragment
        dirty = _DIRTY.get()
        descendants = list(self.children)
        while dirty is not None and len(descendants) > 0:
            descendant = descendants.pop()
            descendants.extend(descendant.children)
            if descendant.is_drawn_apart:
                dirty[descendant.widget_id] = descendant

    def _mark_dirty(self, _view: TView, _rendered_object: str, _value: Any) -> None:
        dirty = _DIRTY.get()
        if dirty is not None:
            dirty[self.widget_id] = self


def _file_types(extensions: dict[str, tuple[str, ...]]) -> list[str]:
    """Get the file types a picker offers, e.g. [".md", ".markdown"]; empty for any."""
    return list(dict.fromkeys(t.lower() for ts in extensions.values() for t in ts))


def _is_shown(view: View) -> bool:
    """Tell whether this backend shows `view`: with a renderer of its own, or as a form row."""
    return isinstance(view.renderer, WebRenderer) or (
        isinstance(view, FormRowView) and isinstance(view.renderer, RendererContainer)
    )


def _view_html(view: View) -> Markup:
    """Get `view`'s HTML in a layout; a form row's anywhere, as a form shows it."""
    renderer = view.renderer
    if isinstance(view, FormRowView) and isinstance(renderer, RendererContainer):
        parts = (
            ["label", "field", "log"] if isinstance(view, FormLabelRowView) else ["field", "log"]
        )
        # field right before log: the page's stylesheet marks a field followed by an error
        return Markup('<div data-cui="row" class="flex flex-col gap-1">{}</div>').format(
            Markup("").join(_fragment(renderer.get_renderer(part)) for part in parts)
        )
    return _fragment(renderer)


def _fragment(renderer: Any) -> Markup:
    return renderer.to_html() if isinstance(renderer, WebRenderer) else Markup()


#: a header button's icon, by the kind of action it runs (Lucide's, inlined: no CDN)
_ICONS: Final[dict[str, str]] = {
    "new": Markup('<path d="M12 5v14M5 12h14"/>'),
    "open": Markup(
        '<path d="M12 15V3M7 8l5-5 5 5"/><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>'
    ),
    "save": Markup(
        '<path d="M12 3v12M7 10l5 5 5-5"/><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>'
    ),
    "more": Markup(
        '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/>'
        '<circle cx="19" cy="12" r="1"/>'
    ),
    "chevron": Markup('<path d="m6 9 6 6 6-6"/>'),
    "search": Markup('<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>'),
    "help": Markup(
        '<circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/>'
        '<path d="M12 17h.01"/>'
    ),
    "pencil": Markup(
        '<path d="M21.17 6.81a1 1 0 0 0-3.98-3.98L3.84 16.17a2 2 0 0 0-.5.83l-1.32'
        ' 4.35a.5.5 0 0 0 .62.62l4.35-1.32a2 2 0 0 0 .83-.5z"/><path d="m15 5 4 4"/>'
    ),
    "sidebar": Markup('<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 3v18"/>'),
    "calendar": (
        Markup(
            '<rect x="3" y="4" width="18" height="18" rx="2"/>'
            '<path d="M16 2v4"/><path d="M8 2v4"/><path d="M3 10h18"/>'
        )
    ),
    "parent": Markup('<path d="m5 12 7-7 7 7"/><path d="M12 19V5"/>'),
    "folder": Markup(
        '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0'
        ' 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>'
    ),
    "file": Markup(
        '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/>'
        '<path d="M14 2v4a2 2 0 0 0 2 2h4"/>'
    ),
    "reload": Markup(
        '<path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/>'
    ),
    "circle-check": Markup('<circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/>'),
    "circle-alert": Markup(
        '<circle cx="12" cy="12" r="10"/><path d="M12 8v4"/><path d="M12 16h.01"/>'
    ),
    "circle-x": Markup('<circle cx="12" cy="12" r="10"/><path d="m15 9-6 6"/><path d="m9 9 6 6"/>'),
    "x": Markup('<path d="M18 6 6 18"/><path d="m6 6 12 12"/>'),
}

#: a tree node's mark: its icon and its color, as a log's are colored
_MARK_ICONS: Final = {
    NodeMark.DONE: ("circle-check", "text-success"),
    NodeMark.WARNING: ("circle-alert", "text-warning"),
    NodeMark.ERROR: ("circle-x", "text-error"),
}


def _icon(name: str, size: str = "size-4") -> Markup:
    return Markup(
        '<svg class="{}" viewBox="0 0 24 24" fill="none" stroke="currentColor"'
        ' stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
        "{}</svg>"
    ).format(size, _ICONS[name])


def _file_icon(icon: str | None) -> Markup:
    """Show an action's icon file, or nothing without one (see `icons.py`).

    An SVG is drawn in the text's color, as the built-in icons are, so it follows the
    theme: only its shape counts. Any other image shows as it is.
    """
    url = None if icon is None else icon_url(icon)
    if url is None:
        return Markup()
    if url.endswith(".svg"):
        mask = f"url('{url}') center / contain no-repeat"
        return Markup(
            '<span aria-hidden="true" class="size-4 shrink-0 bg-current"'
            ' style="mask: {}; -webkit-mask: {}"></span>'
        ).format(mask, mask)
    return Markup(
        '<img src="{}" alt="" aria-hidden="true" class="size-4 shrink-0 object-contain">'
    ).format(url)

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
import enum
import json
import math
import re
from abc import abstractmethod
from collections import deque
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

from composeui.core.registry import RendererType
from composeui.core.renderer import (
    MainRenderer,
    NoRenderedObjectError,
    Renderer,
    RendererContainer,
    ViewLike,
)
from composeui.core.view import (
    ActionView,
    Align,
    DialogKind,
    DialogView,
    ExitAppAction,
    ExpanderView,
    FormLabelRowView,
    FormRowView,
    FormView,
    GridView,
    GroupFormView,
    HorizontalView,
    ListView,
    MainView,
    Menu,
    NewAction,
    NodeMark,
    OkCancelDialogView,
    OpenFileAction,
    Orientation,
    PageView,
    PageWidth,
    PickFileAction,
    Router,
    SaveAction,
    SaveAsAction,
    SeparatorAction,
    SidebarView,
    SplitterView,
    StatusBar,
    TabPage,
    TabView,
    ToolBar,
    TreeView,
    VerticalView,
    View,
    dialogs_in,
    walk_tree,
)
from composeui.webcore.changes import _DIRTY, collect_dirty
from composeui.webcore.downloads import Downloads, downloads_marker
from composeui.webcore.icons import icon_url
from composeui.webcore.page import SAVE_FORM_ID, get_page, jobs_poller, reload_poller
from composeui.webcore.rendertarget import (
    _RENDER_TARGET,
    RenderTarget,
    call_in_session,
    rendering_into,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from pathlib import Path

    from composeui.core.view import (
        DownloadedFile,
        TreeNode,
        TreePath,
    )

TView = TypeVar("TView", bound=ViewLike)

_ID_PATTERN = re.compile(r'\sid="([^"]+)"')
#: seconds a status bar waits past its message's timeout before fetching itself again
_AUTO_CLEAR_MARGIN = 0.25


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
        """Get the attributes of the fragment's root tag, kept even when hidden for later swaps."""
        attributes = [Markup('id="{}"').format(self.widget_id)]
        if not self._view.is_visible:
            attributes.append(Markup("hidden"))
        if oob:
            attributes.append(Markup('hx-swap-oob="true"'))
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


class WebFormLabelRenderer(WebRenderer[FormLabelRowView]):
    """The label of a form row, pointing at the row's field for clicks/screen readers.

    With help, a "?" button beside the label opens it in a popover: a click, a tap, or
    Enter once Tab reached it, as hovering can't on a phone. The button is outside the
    `<label>`, so it isn't part of the field's name.
    """

    _role = "form_label"

    def __init__(self, view: FormLabelRowView) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "label": self._mark_dirty,
                "help": self._refresh_help,
                "help_button_text": self._mark_dirty,
            }
        )

    @property
    def text_id(self) -> str:
        """The id of the ``<label>`` itself, which names a field ``<label for>`` can't."""
        return f"{self.widget_id}-text"

    @property
    def help_id(self) -> str:
        """The id of the row's help, which describes the field while there is help."""
        return f"{self.widget_id}-help"

    def has_help(self) -> bool:
        return self._view.help != ""

    def to_html(self, *, oob: bool = False) -> Markup:
        field = self._field_renderer()
        # a radio group or a checkbox is a `<div>`, which isn't labelable: its
        # `aria-labelledby` names it instead
        target = Markup(' for="{}"').format(field.widget_id) if field.is_labelable else ""
        return Markup(
            '<div {root_attributes} class="flex items-center gap-1">'
            '<label id="{text_id}"{target}'
            ' class="label text-sm font-medium text-base-content"'
            ">{label}</label>{help_html}</div>"
        ).format(
            root_attributes=self._root_attributes(oob=oob),
            text_id=self.text_id,
            target=target,
            label=self._view.label,
            help_html=self._help_html(),
        )

    def _help_html(self) -> Markup:
        """Render the "?" button and the help it opens, which also describes the field.

        Closed, the popover is hidden, which `aria-describedby` still reads. The page's
        script places it beside the button (see `page.js`).
        """
        if not self.has_help():
            return Markup()
        return Markup(
            '<button type="button" popovertarget="{help_id}"'
            ' class="inline-flex cursor-pointer rounded-full text-base-content/40'
            " transition-colors hover:text-primary focus-visible:text-primary"
            ' focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"'
            ' aria-label="{help_button_text}">{help_icon}</button>'
            # `cui-help`: the arrow pointing at the button, see `css/app.css`
            '<div id="{help_id}" popover data-help class="cui-help m-0 w-max max-w-80'
            " rounded-field border border-base-300 bg-base-100 px-3 py-2 text-xs"
            ' leading-relaxed text-base-content shadow-lg">'
            "{help}</div>"
        ).format(
            help_id=self.help_id,
            help_button_text=self._view.help_button_text,
            help_icon=_icon("help"),
            help=self._view.help,
        )

    def _refresh_help(self, view: FormLabelRowView, rendered_object: str, value: str) -> None:
        self._mark_dirty(view, rendered_object, value)
        dirty = _DIRTY.get()
        if dirty is not None and (view.help == "") != (value == ""):
            # its `aria-describedby` gains or loses the help
            field = self._field_renderer()
            dirty[field.widget_id] = field

    def _field_renderer(self) -> WebRenderer[Any]:
        assert isinstance(self._view.renderer, RendererContainer)  # a row's label's
        field_renderer = self._view.renderer.get_renderer("field")
        assert isinstance(field_renderer, WebRenderer)
        return field_renderer


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
        return Markup('<div class="flex flex-col gap-1">{}</div>').format(
            Markup("").join(_fragment(renderer.get_renderer(part)) for part in parts)
        )
    return _fragment(renderer)


def _fragment(renderer: Any) -> Markup:
    return renderer.to_html() if isinstance(renderer, WebRenderer) else Markup()


class WebFormRenderer(WebRenderer[FormView]):
    """A form: each row's label, field and log stacked together, then the form's log.

    A `<fieldset>`, so disabling the form disables every control in it, as disabling a
    Qt container disables its children. Rows have no fragment of their own: each of a
    row's renderers hides itself when the row does, and swaps on its own.
    """

    _role = "form"

    def render(self) -> None:
        super().render()
        self._adopt(self._view.children_views)

    def to_html(self, *, oob: bool = False) -> Markup:
        return self._fieldset(oob=oob, classes="flex min-w-0 flex-col gap-5", legend="")

    def _fieldset(self, *, oob: bool, classes: str, legend: str) -> Markup:
        disabled = "" if self.is_enabled else " disabled"
        # its rows and its other views, e.g. a table; a view this backend doesn't support:
        # empty
        rows = Markup("").join(_view_html(view) for view in self._view.content_views)
        return Markup(
            "<fieldset {root_attributes}"
            ' class="{classes}"{disabled}>{legend}{rows}{fragment}</fieldset>'
        ).format(
            root_attributes=self._root_attributes(oob=oob),
            classes=classes,
            disabled=disabled,
            legend=legend,
            rows=rows,
            fragment=_fragment(self._view.log_view.renderer),
        )


class WebGroupFormRenderer(WebFormRenderer):
    """A titled group of rows, e.g. `pipeform.py`'s "Main Pipe"."""

    _role = "group_form"

    def __init__(self, view: GroupFormView) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update({"title": self._mark_dirty})

    def to_html(self, *, oob: bool = False) -> Markup:
        title = self._view.title if isinstance(self._view, GroupFormView) else ""
        return self._fieldset(
            oob=oob,
            classes="fieldset form-grid min-w-0 gap-4 rounded-box border border-base-300"
            " bg-base-200 p-4",
            legend=(
                Markup(
                    '<legend class="fieldset-legend px-1 text-sm font-semibold text-primary">'
                    "{}</legend>"
                ).format(title)
            ),
        )


class WebStatusBarRenderer(WebRenderer[StatusBar]):
    _role = "status_bar"

    def __init__(self, view: StatusBar) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "message": self._mark_dirty,
                "timeout": self._mark_dirty,
            }
        )

    def to_html(self, *, oob: bool = False) -> Markup:
        # docked like Qt/Textual's status bar; an empty message leaves a quiet empty line
        return Markup(
            "<footer {root_attributes}{auto_clear_attributes}"
            ' role="status" aria-live="polite"'
            ' class="status-bar fixed inset-x-0 bottom-0 z-20 flex min-h-9 items-center gap-2'
            ' border-t border-base-300 px-4 text-sm">'
            "{message}"
            "</footer>"
        ).format(
            root_attributes=self._root_attributes(oob=oob),
            auto_clear_attributes=self._auto_clear_attributes(),
            message=self._view.message,
        )

    def _auto_clear_attributes(self) -> Markup:
        """Fetch the bar again once its message has timed out.

        `show_message`'s timer clears the message on the server outside any request,
        so no response ever tells the browser. Instead, a bar showing a message asks
        for its own current state once, just after `timeout`; by then the timer has
        cleared it. A message that was replaced or re-shown meanwhile comes back with
        its own fresh delay, so a stale fetch is harmless.
        """
        if self._view.message == "" or self._view.timeout <= 0:
            return Markup()
        # margin: the browser's delay starts after the server's timer did, but not by much
        delay_ms = round((self._view.timeout + _AUTO_CLEAR_MARGIN) * 1000)
        return Markup(
            ' hx-get="/widget/{}" hx-trigger="load delay:{}ms" hx-swap="outerHTML"'
        ).format(self.widget_id, delay_ms)


#: closes an open daisyUI dropdown (it stays open while something in it has focus)
_CLOSE_DROPDOWN = "data-close-dropdown"


def _web_shortcut(shortcut: str | None) -> tuple[str, str] | None:
    """Map a view's `Ctrl+<letter or digit>` shortcut to one the browser leaves free.

    Browsers keep most Ctrl shortcuts for themselves (Ctrl+N opens a window, Ctrl+O a
    file, Ctrl+S saves the page, Ctrl+Q quits Firefox on Linux). So `Ctrl+x` becomes
    `Alt+Shift+X`, the combination web apps use for their own shortcuts. Returns the
    label to show and the physical key (`KeyboardEvent.code`) the page's key handler
    matches (see `page.js`); None for any other shortcut, which has no free web
    equivalent (e.g. `Ctrl+Shift+s` would collide with `Ctrl+s`'s `Alt+Shift+S`).
    """
    match = re.fullmatch(r"ctrl\+([a-z0-9])", shortcut or "", flags=re.IGNORECASE)
    if match is None:
        return None
    key = match.group(1).upper()
    code = f"Key{key}" if key.isalpha() else f"Digit{key}"
    return f"Alt+Shift+{key}", code


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


class Placement(enum.Enum):
    """Where a menu's action shows in the header (see `WebMenuRenderer`)."""

    ITEM = "item"  # an item of a dropdown
    BUTTON = "button"  # a button of its own
    PAGE = "page"  # a link to a page, in the header's toolbar of pages
    TOOL = "tool"  # a button of a `ToolBar`
    OMITTED = "omitted"  # not shown: Save As next to Save (both download), Exit


def _between_items(items: list[tuple[bool, str]]) -> list[tuple[bool, str]]:
    """Keep only the separators between two items: the others separated buttons."""
    kept: list[tuple[bool, str]] = []
    for is_separator, item in items:
        if is_separator and (len(kept) == 0 or kept[-1][0]):
            continue
        kept.append((is_separator, item))
    if len(kept) > 0 and kept[-1][0]:
        kept.pop()
    return kept


class WebMenuRenderer(WebRenderer[Menu]):
    """A menu in the header, shaped like a web app's rather than a desktop menu bar.

    A menu with New, Open or Save actions (`FileMenu`) puts them in plain sight as
    header buttons, Save highlighted, and any other action in a "⋯" dropdown named after
    the menu. Save As is left out next to Save, as in a browser both download the same
    file, and so is Exit. A web page is left by closing its tab, and New already starts
    over. Any other menu is a dropdown under its title.

    `Menu.is_visible` means "popped up" (it starts False, a Qt notion): a dropdown is
    always shown and opens on click, so it is ignored here.
    """

    _role = "menu"

    def __init__(self, view: Menu) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "is_visible": self._ignore,
                "title": self._mark_dirty,
            }
        )

    def to_html(self, *, oob: bool = False) -> Markup:
        oob_attribute = Markup(' hx-swap-oob="true"') if oob else ""
        has_save = any(isinstance(child, SaveAction) for child in self._view.children_views)
        buttons: list[str] = []
        items: list[tuple[bool, str]] = []  # (is a separator, its html)
        for child in self._view.children_views:
            renderer = child.renderer
            if not isinstance(renderer, WebRenderer):
                continue
            if isinstance(renderer, WebActionRenderer):
                renderer.placement = self._placement(child, has_save=has_save)
                if renderer.placement is not Placement.ITEM:
                    buttons.append(renderer.to_html())
                    continue
            items.append((isinstance(child, SeparatorAction), renderer.to_html()))
        items = _between_items(items)
        title = self._view.title
        if len(buttons) == 0:
            # a chevron: it opens a menu, unlike the header buttons next to it
            trigger = Markup(
                '<div tabindex="0" role="button" class="btn btn-ghost btn-sm gap-1 pr-2"'
                ' aria-haspopup="menu">'
                '{}<span class="opacity-60">{}</span></div>'
            ).format(title, _icon("chevron"))
        else:
            trigger = Markup(
                '<div tabindex="0" role="button" class="btn btn-ghost btn-sm btn-square"'
                ' aria-label="{title}" title="{title}">{more_icon}</div>'
            ).format(title=title, more_icon=_icon("more"))
        dropdown = (
            Markup(
                '<div class="dropdown dropdown-end">'
                "{}"
                # as wide as its longest item, its text and shortcut on one line
                '<ul tabindex="0" class="menu dropdown-content z-30 mt-2 w-max min-w-56'
                ' rounded-box border border-base-300 bg-base-100 p-2 shadow-lg">'
                "{}</ul></div>"
            ).format(trigger, Markup("").join(item for (_, item) in items))
            if len(items) > 0
            else ""
        )
        return Markup(
            '<div id="{widget_id}"{oob_attribute} class="flex items-center'
            ' gap-1">{join}{dropdown}</div>'
        ).format(
            widget_id=self.widget_id,
            oob_attribute=oob_attribute,
            join=Markup("").join(buttons),
            dropdown=dropdown,
        )

    @staticmethod
    def _placement(action: View, *, has_save: bool) -> Placement:
        if isinstance(action, SaveAsAction):
            return Placement.OMITTED if has_save else Placement.BUTTON
        if isinstance(action, ExitAppAction):
            return Placement.OMITTED
        if isinstance(action, (NewAction, SaveAction, OpenFileAction)):
            return Placement.BUTTON
        return Placement.ITEM

    def _ignore(self, _view: Menu, _rendered_object: str, _value: Any) -> None:
        pass


class WebActionRenderer(WebRenderer[ActionView]):
    """A menu or toolbar action posting `triggered`; Save/Open are a download and an upload.

    Those two can't go through the generic widget event: a download has to be a form's
    post (htmx can't start one), and a file has to be uploaded. Both name the action
    (`trigger`), so its `triggered` still fires first, for whatever user code is
    connected to it.
    """

    _role = "action"

    def __init__(self, view: ActionView) -> None:
        super().__init__(view)
        #: the file types Open's picker offers, e.g. ".hello"; an action doesn't know its
        #: main view, so `WebMainRenderer.render` sets it
        self.accept: str | None = None
        #: set by its menu or toolbar: kept for when the action is swapped on its own
        self.placement = Placement.ITEM
        #: the address of the page a page's action shows, set by `WebRouterRenderer`
        self.href: str | None = None
        #: whether the page has it: a menu, a toolbar or a router put it there
        self._is_shown = False
        self._refresh_dispatcher.update(
            dict.fromkeys(
                ("text", "icon", "data", "shortcut", "is_checkable", "is_checked"),
                self._mark_dirty,
            )
        )
        if isinstance(view, PickFileAction):
            self._refresh_dispatcher["extensions"] = self._mark_dirty  # the picker's types

    def _mark_dirty(self, view: ActionView, rendered_object: str, value: Any) -> None:
        # e.g. the entry of a page outside a router: no element on the page to swap
        if self._is_shown:
            super()._mark_dirty(view, rendered_object, value)

    def to_html(self, *, oob: bool = False) -> Markup:
        self._is_shown = True
        if self.placement is Placement.OMITTED:
            return Markup("<span {} hidden></span>").format(self._root_attributes(oob=oob))
        if self.placement is Placement.BUTTON:
            return self._button_html(oob=oob)
        if self.placement is Placement.PAGE:
            return self._page_link_html(oob=oob)
        if self.placement is Placement.TOOL:
            return self._tool_html(oob=oob)
        view = self._view
        check = "✓ " if view.is_checkable and view.is_checked else ""
        shortcut = _web_shortcut(view.shortcut)
        # the shortcut a hint, lighter than the action's text and kept apart from it
        kbd = (
            Markup('<kbd class="ml-6 font-sans text-xs text-base-content/50">{}</kbd>').format(
                shortcut[0]
            )
            if shortcut
            else ""
        )
        label = Markup(
            '<span class="flex items-center gap-2'
            ' whitespace-nowrap">{file_icon}{check}{text}</span>{kbd}'
        ).format(file_icon=_file_icon(view.icon), check=check, text=view.text, kbd=kbd)
        key = Markup(' data-shortcut="{}"').format(shortcut[1]) if shortcut else ""
        if not view.is_enabled:
            item = Markup(
                '<button type="button" class="justify-between" disabled>{}</button>'
            ).format(label)
        else:
            item = self._active_html(Markup('class="justify-between"'), label, key)
        menu_disabled = "" if view.is_enabled else Markup(' class="menu-disabled"')
        return Markup("<li {root_attributes}{menu_disabled}>{item}</li>").format(
            root_attributes=self._root_attributes(oob=oob), menu_disabled=menu_disabled, item=item
        )

    def _button_html(self, *, oob: bool) -> Markup:
        """Render a header button: Save the highlighted one, its shortcut in the tooltip."""
        view = self._view
        shortcut = _web_shortcut(view.shortcut)
        text = view.text
        tooltip = f"{text} ({shortcut[0]})" if shortcut else text
        style = "btn-primary" if isinstance(view, SaveAction) else "btn-ghost"
        icon = _file_icon(view.icon)
        if icon == "":
            if isinstance(view, NewAction):
                icon = _icon("new")
            else:
                icon = _icon("open" if isinstance(view, OpenFileAction) else "save")
        attributes = Markup(
            '{root_attributes} class="btn btn-sm {style}" title="{tooltip}"'
        ).format(root_attributes=self._root_attributes(oob=oob), style=style, tooltip=tooltip)
        label = Markup('{}<span class="toolbar-label">{}</span>').format(icon, text)
        if not view.is_enabled:
            return Markup('<button {} type="button" disabled>{}</button>').format(attributes, label)
        key = Markup(' data-shortcut="{}"').format(shortcut[1]) if shortcut else ""
        return self._active_html(attributes, label, key)

    def _tool_html(self, *, oob: bool) -> Markup:
        """Render a toolbar button, pressed while checked, its shortcut in the tooltip.

        With an icon, it keeps only the icon on a phone, as the header's buttons do: the
        tooltip then names it.
        """
        view = self._view
        shortcut = _web_shortcut(view.shortcut)
        text = view.text
        icon = _file_icon(view.icon)
        label = (
            Markup('{}<span class="toolbar-label">{}</span>').format(icon, text) if icon else text
        )
        if shortcut:
            tooltip = Markup(' title="{} ({})"').format(text, shortcut[0])
        else:
            tooltip = Markup(' title="{}"').format(text) if icon else Markup()
        is_checked = view.is_checkable and view.is_checked
        active = " btn-active" if is_checked else ""
        pressed = (
            Markup(' aria-pressed="{}"').format(str(is_checked).lower())
            if view.is_checkable
            else ""
        )
        attributes = Markup(
            '{root_attributes} class="btn btn-ghost btn-sm{active}"{tooltip}{pressed}'
        ).format(
            root_attributes=self._root_attributes(oob=oob),
            active=active,
            tooltip=tooltip,
            pressed=pressed,
        )
        if not self.is_enabled:
            return Markup('<button {} type="button" disabled>{}</button>').format(attributes, label)
        key = Markup(' data-shortcut="{}"').format(shortcut[1]) if shortcut else ""
        return self._active_html(attributes, label, key)

    def _page_link_html(self, *, oob: bool) -> Markup:
        """Render a toolbar link to a page: still a link to its address, for a new tab.

        A click posts `triggered` instead of following the link: the router navigates,
        and the response puts the page's address in the browser's history.
        """
        view = self._view
        is_current = view.is_checkable and view.is_checked
        shortcut = _web_shortcut(view.shortcut)
        text = view.text
        tooltip = Markup(' title="{} ({})"').format(text, shortcut[0]) if shortcut else ""
        icon = _file_icon(view.icon)
        label = Markup("{}{}").format(icon, text)
        gap = " gap-2" if icon else ""
        classes = f"tab tab-active{gap}" if is_current else f"tab{gap}"
        current = Markup(' aria-current="page"') if is_current else ""
        if not view.is_enabled:
            return Markup(
                '<a {root_attributes} class="tab tab-disabled{gap}"'
                ' aria-disabled="true"{tooltip}>{label}</a>'
            ).format(
                root_attributes=self._root_attributes(oob=oob),
                gap=gap,
                tooltip=tooltip,
                label=label,
            )
        key = Markup(' data-shortcut="{}"').format(shortcut[1]) if shortcut else ""
        href = self.href or ""
        return Markup(
            '<a {root_attributes} class="{classes}" href="{href}"{current}'
            '{tooltip} hx-post="/widget/{widget_id}"'
            """ hx-vals='{{"event": "triggered"}}' hx-swap="none"{key}>{label}</a>"""
        ).format(
            root_attributes=self._root_attributes(oob=oob),
            classes=classes,
            href=href,
            current=current,
            tooltip=tooltip,
            widget_id=self.widget_id,
            key=key,
            label=label,
        )

    def _active_html(self, attributes: str, label: str, key: str) -> Markup:
        """Render the element a click (or the page's key handler, through `key`) activates."""
        view = self._view
        if isinstance(view, (SaveAction, SaveAsAction)):
            # it fires the action, so it posts the page's form, a download as answer
            return Markup(
                '<button {attributes} type="submit" form="{SAVE_FORM_ID}" name="trigger"'
                ' value="{widget_id}" {CLOSE_DROPDOWN}{key}>{label}</button>'
            ).format(
                attributes=attributes,
                SAVE_FORM_ID=SAVE_FORM_ID,
                widget_id=self.widget_id,
                CLOSE_DROPDOWN=_CLOSE_DROPDOWN,
                key=key,
                label=label,
            )
        if isinstance(view, OpenFileAction):
            accept = "" if self.accept is None else Markup(' accept="{}"').format(self.accept)
            return Markup(
                '<label {attributes}>{label}<input type="file" name="file"{accept}'
                ' class="hidden" hx-post="/state" hx-encoding="multipart/form-data"'
                """ hx-trigger="change" hx-vals='{{"trigger": "{widget_id}"}}'"""
                ' hx-swap="none" autocomplete="off" {CLOSE_DROPDOWN}{key}></label>'
            ).format(
                attributes=attributes,
                label=label,
                accept=accept,
                widget_id=self.widget_id,
                CLOSE_DROPDOWN=_CLOSE_DROPDOWN,
                key=key,
            )
        if isinstance(view, PickFileAction):
            types = ",".join(self.file_types)
            accept = Markup(' accept="{}"').format(types) if types else ""
            # emptied once sent: picking the same file again is a change too
            return Markup(
                '<label {attributes}>{label}<input type="file" name="file"{accept}'
                ' class="hidden" hx-post="/widget/{widget_id}/file"'
                ' hx-encoding="multipart/form-data" hx-trigger="change" hx-swap="none"'
                ' data-clear-after-post autocomplete="off"'
                " {CLOSE_DROPDOWN}{key}></label>"
            ).format(
                attributes=attributes,
                label=label,
                accept=accept,
                widget_id=self.widget_id,
                CLOSE_DROPDOWN=_CLOSE_DROPDOWN,
                key=key,
            )
        return Markup(
            '<button {attributes} type="button"'
            """ hx-post="/widget/{widget_id}" hx-vals='{{"event": "triggered"}}'"""
            ' hx-swap="none" {CLOSE_DROPDOWN}{key}>{label}</button>'
        ).format(
            attributes=attributes,
            widget_id=self.widget_id,
            CLOSE_DROPDOWN=_CLOSE_DROPDOWN,
            key=key,
            label=label,
        )

    def dispatch(self, event: str, form: Mapping[str, str]) -> None:
        # `is_enabled`: an action of a disabled toolbar is disabled with it
        if event != "triggered" or not self.is_enabled:
            super().dispatch(event, form)
        self._view.triggered.emit()

    @property
    def file_types(self) -> list[str]:
        """Get the file types a `PickFileAction` offers, e.g. [".md"]; empty for any."""
        view = self._view
        if not isinstance(view, PickFileAction):
            return []
        return _file_types(view.extensions)

    def pick_file(self, path: Path) -> None:
        """Hand the file a `PickFileAction`'s picker uploaded to its `file_picked`.

        Its `triggered` first, as on the other backends (its own picker answers nothing
        on the web). Raises `UnsupportedEventError` for any other action.
        """
        view = self._view
        if not isinstance(view, PickFileAction) or not self.is_enabled:
            raise UnsupportedEventError(self, "file")
        view.triggered.emit()
        view.file_picked.emit(path)


class WebSeparatorRenderer(WebRenderer[SeparatorAction]):
    _role = "separator"

    def __init__(self, view: SeparatorAction) -> None:
        super().__init__(view)
        #: set by its toolbar: a bar between buttons rather than a menu's line
        self.is_in_toolbar = False

    def to_html(self, *, oob: bool = False) -> Markup:
        if self.is_in_toolbar:
            return Markup(
                '<div {} role="separator"'
                ' aria-orientation="vertical" class="mx-1 h-5 w-px bg-base-300"></div>'
            ).format(self._root_attributes(oob=oob))
        return Markup('<li {} role="separator"><hr class="my-1 border-base-300 p-0"></li>').format(
            self._root_attributes(oob=oob)
        )


class WebToolBarRenderer(WebRenderer[ToolBar]):
    """A row of buttons in the header, one per action, posting `triggered`."""

    _role = "toolbar"

    def __init__(self, view: ToolBar) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update({"title": self._mark_dirty})

    def render(self) -> None:
        super().render()
        self._adopt(self._view.children_views)
        # the children are rendered first: make them a toolbar's
        for child in self._view.children_views:
            if isinstance(child.renderer, WebActionRenderer):
                child.renderer.placement = Placement.TOOL
            elif isinstance(child.renderer, WebSeparatorRenderer):
                child.renderer.is_in_toolbar = True

    def to_html(self, *, oob: bool = False) -> Markup:
        items = _between_items(
            [
                (isinstance(child, SeparatorAction), child.renderer.to_html())
                for child in self._view.children_views
                if isinstance(child.renderer, WebRenderer)
            ]
        )
        title = self._view.title
        label = Markup(' aria-label="{}"').format(title) if title else ""
        return Markup(
            '<div {root_attributes} role="toolbar"{label} class="flex items-center'
            ' gap-1">{join}</div>'
        ).format(
            root_attributes=self._root_attributes(oob=oob),
            label=label,
            join=Markup("").join(item for (_, item) in items),
        )


class WebDialogRenderer(WebRenderer[DialogView]):
    """A modal `<dialog>`, opened by the page's script once swapped in shown.

    The main renderer puts every dialog at the end of the page, outside any page's
    slot, which hides its content. A button closes the dialog in the browser, so focus
    goes back where it was, then posts its answer; Escape posts a dismissal. The
    server then swaps the dialog closed: it isn't the button's own fragment, and is
    closed already.
    """

    #: its `dispatch` decides by event: a second click on a dialog just closed does nothing
    @property
    def takes_events(self) -> bool:
        return True

    _role = "dialog"
    is_drawn_apart = True

    def __init__(self, view: DialogView) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            dict.fromkeys(("title", "text", "kind", "accept_text", "reject_text"), self._mark_dirty)
        )

    def to_html(self, *, oob: bool = False) -> Markup:
        view = self._view
        title_id = f"{self.widget_id}-title"
        text_id = f"{self.widget_id}-text"
        disabled = "" if self.is_enabled else " disabled"
        reject = (
            self._button_html("reject", view.reject_text, "btn", disabled)
            if view.kind is DialogKind.CONFIRM
            else ""
        )
        accept = self._button_html("accept", view.accept_text, "btn btn-primary", disabled)
        # a disabled dialog can't be closed: its answer would be ignored
        cancel = (
            Markup(
                ' hx-post="/widget/{}" hx-trigger="cancel"'
                """ hx-vals='{{"event": "dismiss"}}'"""
            ).format(self.widget_id)
            if self.is_enabled
            else " data-keep-open"
        )
        title = (
            Markup('<h2 id="{}" class="text-lg font-bold">{}</h2>').format(title_id, view.title)
            if view.title
            else ""
        )
        labelledby = Markup(' aria-labelledby="{}"').format(title_id) if view.title else ""
        return Markup(
            '<dialog {root_attributes} class="modal" data-dialog'
            '{labelledby} aria-describedby="{text_id}"{cancel} hx-swap="none">'
            '<div class="modal-box">{title}'
            '<p id="{text_id}" class="py-4 whitespace-pre-line">{text}</p>'
            '<div class="modal-action">{reject}{accept}</div></div></dialog>'
        ).format(
            root_attributes=self._root_attributes(oob=oob),
            labelledby=labelledby,
            text_id=text_id,
            cancel=cancel,
            title=title,
            text=view.text,
            reject=reject,
            accept=accept,
        )

    def _button_html(self, event: str, text: str, classes: str, disabled: str) -> Markup:
        # the dialog's own `close`, not `cancel`: no dismissal posted on top of the answer
        autofocus = " autofocus" if event == "accept" else ""
        return Markup(
            '<button type="button" class="{classes}" hx-post="/widget/{widget_id}"'
            """ hx-vals='{{"event": "{event}"}}'"""
            " data-close-dialog{autofocus}{disabled}>"
            "{text}</button>"
        ).format(
            classes=classes,
            widget_id=self.widget_id,
            event=event,
            autofocus=autofocus,
            disabled=disabled,
            text=text,
        )

    def dispatch(self, event: str, form: Mapping[str, str]) -> None:
        answers = {
            "accept": self._view.accept,
            "reject": self._view.reject,
            "dismiss": self._view.dismiss,
        }
        answer = answers.get(event)
        if answer is None:
            super().dispatch(event, form)  # raises: no answer of a dialog's
        elif self.is_enabled:
            answer()


class WebFormDialogRenderer(WebDialogRenderer):
    """A modal `<dialog>` holding its form or other view, then Cancel and OK.

    OK is disabled while the view says so, e.g. while a check of the form fails, and only
    it swaps when that changes.
    The dialog itself, swapped while open, would take back what the user is typing.
    Unlike a message's, OK doesn't close the dialog in the browser: the form may refuse
    it, the dialog then staying open with its checks shown. The server swaps it closed
    once accepted. Cancel and Escape close it first, as for any dialog.
    """

    _role = "form_dialog"

    def __init__(self, view: OkCancelDialogView) -> None:
        super().__init__(view)
        self._form_view = view
        #: whether more than OK changed since the dialog was last sent: then it swaps whole
        self._is_whole = False
        self._refresh_dispatcher["is_accept_enabled"] = self._refresh_accept
        self._refresh_dispatcher["has_failing_check"] = self._refresh_accept

    def render(self) -> None:
        super().render()
        view = self._form_view
        self._adopt([view.content, view.log_view, *view.buttons])

    @property
    def accept_id(self) -> str:
        return f"{self.widget_id}-accept"

    def to_html(self, *, oob: bool = False) -> Markup:
        is_whole, self._is_whole = self._is_whole, False
        if oob and not is_whole:
            return self._accept_html(oob=True)
        view = self._form_view
        title_id = f"{self.widget_id}-title"
        text_id = f"{self.widget_id}-text"
        disabled = "" if self.is_enabled else " disabled"
        reject = self._button_html("reject", view.reject_text, "btn", disabled)
        cancel = (
            Markup(
                ' hx-post="/widget/{}" hx-trigger="cancel"'
                """ hx-vals='{{"event": "dismiss"}}'"""
            ).format(self.widget_id)
            if self.is_enabled
            else " data-keep-open"
        )
        title = (
            Markup('<h2 id="{}" class="text-lg font-bold">{}</h2>').format(title_id, view.title)
            if view.title
            else ""
        )
        text = (
            Markup('<p id="{}" class="whitespace-pre-line">{}</p>').format(text_id, view.text)
            if view.text
            else ""
        )
        labelledby = Markup(' aria-labelledby="{}"').format(title_id) if view.title else ""
        describedby = Markup(' aria-describedby="{}"').format(text_id) if view.text else ""
        form_html = _view_html(view.content)
        log_html = _view_html(view.log_view)
        buttons = Markup("").join(_view_html(button) for button in view.buttons)
        return Markup(
            '<dialog {root_attributes} class="modal" data-dialog'
            '{labelledby}{describedby}{cancel} hx-swap="none">'
            '<div class="modal-box flex flex-col gap-4">{title}{text}{form_html}{log_html}'
            '<div class="modal-action">{reject}{buttons}{accept_html}</div>'
            "</div></dialog>"
        ).format(
            root_attributes=self._root_attributes(oob=oob),
            labelledby=labelledby,
            describedby=describedby,
            cancel=cancel,
            title=title,
            text=text,
            form_html=form_html,
            log_html=log_html,
            reject=reject,
            buttons=buttons,
            accept_html=self._accept_html(oob=False),
        )

    def _accept_html(self, *, oob: bool) -> Markup:
        swap = Markup(' hx-swap-oob="true"') if oob else ""
        disabled = "" if self.is_enabled and self._form_view.can_accept else " disabled"
        return Markup(
            '<button id="{accept_id}" type="button" class="btn btn-primary"{swap}'
            ' hx-post="/widget/{widget_id}"'
            """ hx-vals='{{"event": "accept"}}'{disabled}>"""
            "{accept_text}</button>"
        ).format(
            accept_id=self.accept_id,
            swap=swap,
            widget_id=self.widget_id,
            disabled=disabled,
            accept_text=self._form_view.accept_text,
        )

    def _refresh_accept(self, view: DialogView, rendered_object: str, value: Any) -> None:
        super()._mark_dirty(view, rendered_object, value)

    def _mark_dirty(self, view: DialogView, rendered_object: str, value: Any) -> None:
        self._is_whole = True
        super()._mark_dirty(view, rendered_object, value)


TBuilt = TypeVar("TBuilt", bound=View)


class _BuiltWhenShown(WebRenderer[TBuilt]):
    """A page or a tab whose views are built the first time it's shown, as Qt's are.

    So an app's many pages and tabs don't weigh on each session, in memory and in the time
    of its first page. Its views exist from the start: the app reads and sets any of them,
    and a view built later shows its state then. Until built, the dialogs inside its views,
    which the app opens whatever is shown, follow its enabled state: it adopts them.
    """

    def __init__(self, view: TBuilt) -> None:
        super().__init__(view)
        #: whether its views are built; `defer` leaves them until `build`
        self.is_built = True
        #: the dialogs it adopted until the views around them are built
        self._waiting: list[WebRenderer[Any]] = []

    @abstractmethod
    def _content_views(self) -> list[View]:
        """Get the views it shows, in order."""

    def render(self) -> None:
        super().render()
        self._adopt(self._content_views())

    def defer(self) -> None:
        """Leave its views unbuilt until `build`, adopting the dialogs inside them meanwhile."""
        self.is_built = False
        for dialog in dialogs_in(self._view):
            renderer = dialog.renderer
            if isinstance(renderer, WebRenderer) and renderer.parent is None:
                renderer.parent = self
                self.children.append(renderer)
                self._waiting.append(renderer)

    def build(self) -> None:
        """Build its views into its session, once: the router or the tabs show it."""
        if self.is_built:
            return
        self.is_built = True
        # the views around them adopt them now, or a tab not built yet, as `defer` does
        for renderer in self._waiting:
            self.children.remove(renderer)
            if renderer.parent is self:  # not adopted since, by a render again of its views
                renderer.parent = None
        self._waiting = []
        with self._in_session():
            for view in self._content_views():
                view.render(RendererType.WEB)
        self._adopt(self._content_views())


class WebPageRenderer(_BuiltWhenShown[PageView]):
    """A page's views in a column, like the main view's own."""

    _role = "page"

    def _content_views(self) -> list[View]:
        return self._view.content_views

    def to_html(self, *, oob: bool = False) -> Markup:
        content = Markup("").join(
            _view_html(view)
            for view in self._view.content_views
            # at the end of the page instead (see `WebDialogRenderer`)
            if _is_shown(view) and not isinstance(view, DialogView)
        )
        return Markup(
            '<section {root_attributes} data-width="{lower}" class="flex flex-col'
            ' gap-6">{content}</section>'
        ).format(
            root_attributes=self._root_attributes(oob=oob),
            lower=self._view.width.name.lower(),
            content=content,
        )


class WebHorizontalRenderer(WebRenderer[HorizontalView]):
    """Views side by side, each as wide as its share of the row.

    Each view sits in a cell carrying its share, an inline style rather than a class
    per share; the cell hides with its view, which swaps on its own. A row narrower than
    42rem stacks its views instead, as a column, unless none has a share (e.g. buttons):
    the share is a variable only the wide row's cells use.
    """

    _role = "horizontal"

    def render(self) -> None:
        super().render()
        self._adopt(self._view.children_views)

    def to_html(self, *, oob: bool = False) -> Markup:
        stretched_views = self._view.stretched_views
        if not any(stretch > 0 for _, stretch in stretched_views):
            # as wide as their content: a container query would measure them as 0 wide
            cells = Markup("").join(
                Markup(
                    '<div class="min-w-0 has-[>[hidden]]:hidden" style="flex: none">{}</div>'
                ).format(_view_html(view))
                for view, _ in stretched_views
                if _is_shown(view)
            )
            align = " justify-end" if self._view.align is Align.END else ""
            return Markup('<div {root_attributes} class="flex gap-6{align}">{cells}</div>').format(
                root_attributes=self._root_attributes(oob=oob), align=align, cells=cells
            )
        cells = Markup("").join(
            Markup(
                '<div class="min-w-0 has-[>[hidden]]:hidden @2xl:flex-(--share)"'
                # no share: as wide as its content
                ' style="--share: {}">'
                "{}</div>"
            ).format(f"{stretch} 1 0%" if stretch > 0 else "none", _view_html(view))
            for view, stretch in stretched_views
            if _is_shown(view)
        )
        # the row's own width is queried from its root, the views laid out inside it
        return Markup(
            '<div {} class="@container">'
            '<div class="flex flex-col gap-6 @2xl:flex-row">{}</div></div>'
        ).format(self._root_attributes(oob=oob), cells)


class WebVerticalRenderer(WebRenderer[VerticalView]):
    """Views one above the other, at the top of the column, like a page's."""

    _role = "vertical"

    def render(self) -> None:
        super().render()
        self._adopt(self._view.children_views)

    def to_html(self, *, oob: bool = False) -> Markup:
        content = Markup("").join(
            _view_html(view) for view in self._view.children_views if _is_shown(view)
        )
        return Markup('<div {} class="flex flex-col gap-6">{}</div>').format(
            self._root_attributes(oob=oob), content
        )


class WebSplitterRenderer(WebRenderer[SplitterView]):
    """Panes side by side, each in a cell as wide as its share, a border between two.

    A border is an ARIA window splitter (a focusable separator) the user drags, or moves
    with the arrow keys. The browser shares the width between the panes beside it at
    once (see `page.js`), then posts every pane's width (`resize`). Like every control,
    the splitter is never swapped back after one. A splitter narrower than 42rem stacks
    its panes, as a row does, without borders; side by side, a pane is at least 12rem
    wide, for its text to be read. A border shows only between panes shown (see
    `app.css`), as a pane hides and swaps on its own. Vertical, the panes share its
    height, 32rem, one above the other, each scrolling within its share.
    """

    _role = "splitter"

    def __init__(self, view: SplitterView) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {"sizes": self._mark_dirty, "border_text": self._mark_dirty}
        )

    def render(self) -> None:
        super().render()
        self._adopt(self._view.panes)

    def to_html(self, *, oob: bool = False) -> Markup:
        view = self._view
        is_vertical = view.orientation is Orientation.VERTICAL
        shown = sum(size for pane, size in zip(view.panes, view.sizes) if pane.is_visible) or 1
        disabled = "" if self.is_enabled else Markup(' aria-disabled="true"')
        # a separator's orientation is its line's: across the splitter
        border_orientation = "horizontal" if is_vertical else "vertical"
        pane_class = (
            "min-h-0 overflow-auto has-[>[hidden]]:hidden flex-(--share)"
            if is_vertical
            # side by side, each wide enough to read its text (`page.js` reads it too)
            else "min-w-0 has-[>[hidden]]:hidden @2xl:min-w-48 @2xl:flex-(--share)"
        )
        cells: list[str] = []
        before = 0  # the length of the panes shown before the border, in percent
        for index, (pane, size) in enumerate(zip(view.panes, view.sizes)):
            if not _is_shown(pane):
                continue
            pane_id = f"{self.widget_id}-pane-{index}"
            if index > 0:
                cells.append(
                    Markup(
                        '<div class="cui-splitter-border" role="separator"'
                        ' aria-orientation="{border_orientation}" aria-controls="{pane_id}"'
                        ' aria-label="{border_text}" aria-valuemin="0"'
                        ' aria-valuemax="100" aria-valuenow="{round}"'
                        ' tabindex="{value}"{disabled}></div>'
                    ).format(
                        border_orientation=border_orientation,
                        pane_id=pane_id,
                        border_text=view.border_text,
                        round=round(100 * before / shown),
                        value=0 if self.is_enabled else -1,
                        disabled=disabled,
                    )
                )
            if pane.is_visible:
                before += size
            cells.append(
                Markup(
                    '<div id="{pane_id}" data-pane class="{pane_class}" style="--share: {size} 1'
                    ' 0%">{to_html}</div>'
                ).format(
                    pane_id=pane_id,
                    pane_class=pane_class,
                    size=size,
                    to_html=_view_html(pane),
                )
            )
        if is_vertical:
            return Markup(
                '<div {} data-splitter><div class="flex h-128 flex-col">{}</div></div>'
            ).format(self._root_attributes(oob=oob), Markup("").join(cells))
        # the splitter's own width is queried from its root, the panes laid out inside it
        return Markup(
            '<div {} class="@container" data-splitter>'
            '<div class="flex flex-col gap-6 @2xl:flex-row @2xl:gap-0">'
            "{}</div></div>"
        ).format(self._root_attributes(oob=oob), Markup("").join(cells))

    def dispatch(self, event: str, form: Mapping[str, str]) -> None:
        if event != "resize":
            super().dispatch(event, form)
        try:
            lengths = [float(length) for length in form.get("lengths", "").split(",")]
        except ValueError:
            return
        if len(lengths) != len(self._view.panes) or not all(
            math.isfinite(length) and length >= 0 for length in lengths
        ):
            return
        sizes = self._view.shares_of(lengths)
        if sizes == self._view.sizes:  # a click, or a move against a pane's minimum
            return
        with self.stop_refresh():
            self._view.sizes = sizes
        self._view.resized.emit(sizes)


class WebExpanderRenderer(WebRenderer[ExpanderView]):
    """A `<details>` (daisyUI's collapse): its title, then the views one above the other.

    The browser opens and closes it on a click or a key on the title, then posts its
    `toggle`. Like every control, it is never swapped back after one, only when the
    server changes it. Its views swap on their own, shown or not. Disabled, its title
    can't be clicked or focused, as a disabled Qt button can't be pressed.
    """

    _role = "expander"

    def __init__(self, view: ExpanderView) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {"title": self._mark_dirty, "is_expanded": self._mark_dirty}
        )

    def render(self) -> None:
        super().render()
        self._adopt(self._view.children_views)

    def to_html(self, *, oob: bool = False) -> Markup:
        is_open = " open" if self._view.is_expanded else ""
        summary_attributes = (
            "" if self.is_enabled else Markup(' tabindex="-1" aria-disabled="true"')
        )
        summary_classes = "" if self.is_enabled else " pointer-events-none opacity-50"
        content = Markup("").join(
            _view_html(view) for view in self._view.children_views if _is_shown(view)
        )
        # `toggle` also fires when the server swaps it in open: posting the state the
        # server already has, which `dispatch` ignores
        return Markup(
            "<details {root_attributes}{is_open}"
            ' class="collapse collapse-arrow rounded-box border border-base-300 bg-base-100"'
            ' hx-post="/widget/{widget_id}" hx-trigger="toggle"'
            ' data-post-event data-post-open hx-swap="none">'
            '<summary class="collapse-title font-semibold{summary_classes}"{summary_attributes}>'
            "{title}</summary>"
            '<div class="collapse-content flex flex-col gap-6">{content}</div></details>'
        ).format(
            root_attributes=self._root_attributes(oob=oob),
            is_open=is_open,
            widget_id=self.widget_id,
            summary_classes=summary_classes,
            summary_attributes=summary_attributes,
            title=self._view.title,
            content=content,
        )

    def dispatch(self, event: str, form: Mapping[str, str]) -> None:
        if event != "toggle":
            super().dispatch(event, form)
        is_expanded = form.get("open") == "true"
        if is_expanded == self._view.is_expanded:
            return
        with self.stop_refresh():
            self._view.is_expanded = is_expanded
        self._view.toggled.emit(is_expanded)


class WebTreeRenderer(WebRenderer[TreeView]):
    """Nested lists of the nodes, each a button selecting it after an arrow toggling it.

    A click or Enter on a node selects it (`aria-current`), on its arrow expands or
    collapses it (`aria-expanded`); a collapsed node's children are left out. Either way
    the tree is swapped back, each button keeping its own id, its node's position depth
    first. So htmx gives the focus back to the button that had it, as a table's rows do.
    A button posts its node's path: a node a stale page still shows swaps the tree back.
    """

    _role = "tree"

    def __init__(self, view: TreeView) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "nodes": self._mark_dirty,
                "expanded": self._mark_dirty,
                "selected": self._mark_dirty,
                "done_text": self._mark_dirty,
                "warning_text": self._mark_dirty,
                "error_text": self._mark_dirty,
            }
        )

    def to_html(self, *, oob: bool = False) -> Markup:
        positions = {
            path: position for position, (path, _node) in enumerate(walk_tree(self._view.nodes))
        }
        # clipped to a pane too narrow for it, the focus rings at its edges left whole
        return Markup(
            '<ul {} class="flex flex-col gap-0.5 overflow-clip [overflow-clip-margin:4px]">{}</ul>'
        ).format(self._root_attributes(oob=oob), self._nodes_html(self._view.nodes, (), positions))

    def _nodes_html(
        self, nodes: Iterable[TreeNode], parent: TreePath, positions: Mapping[TreePath, int]
    ) -> Markup:
        disabled = "" if self.is_enabled else " disabled"
        items: list[str] = []
        for node in nodes:
            path = (*parent, node.key)
            position, label = positions[path], node.label
            children = ""
            if len(node.children) == 0:
                toggle = Markup('<span class="size-6 shrink-0" aria-hidden="true"></span>')
            else:
                is_expanded = path in self._view.expanded
                turn = "" if is_expanded else " -rotate-90"
                # named by its node, which `aria-expanded` says it expands or collapses
                toggle = Markup(
                    '<button id="{widget_id}-toggle-{position}" type="button"'
                    ' class="btn btn-ghost btn-xs btn-square"'
                    ' aria-expanded="{lower}" aria-label="{label}"'
                    "{post}{disabled}>"
                    "{chevron_icon}</button>"
                ).format(
                    widget_id=self.widget_id,
                    position=position,
                    lower=str(is_expanded).lower(),
                    label=label,
                    post=self._post("toggle", path, expanded=not is_expanded),
                    disabled=disabled,
                    chevron_icon=_icon("chevron", "size-3" + turn),
                )
                if is_expanded:
                    children = Markup(
                        '<ul class="ms-3 flex flex-col gap-0.5 border-s border-base-300 ps-1">'
                        "{}</ul>"
                    ).format(self._nodes_html(node.children, path, positions))
            is_selected = path == self._view.selected
            selected = Markup(' aria-current="true"') if is_selected else ""
            variant = "btn-soft btn-primary" if is_selected else "btn-ghost"
            mark_id = f"{self.widget_id}-mark-{position}"
            described = (
                "" if node.mark is None else Markup(' aria-describedby="{}"').format(mark_id)
            )
            items.append(
                Markup(
                    '<li><div class="flex items-center gap-1">{toggle}'
                    '<button id="{widget_id}-node-{position}" type="button"'
                    ' class="btn btn-sm {variant} min-w-0 shrink justify-start font-normal"'
                    "{selected}{described}"
                    "{post}{disabled}>{node_content}"
                    "</button></div>{children}</li>"
                ).format(
                    toggle=toggle,
                    widget_id=self.widget_id,
                    position=position,
                    variant=variant,
                    selected=selected,
                    described=described,
                    post=self._post("select", path),
                    disabled=disabled,
                    node_content=self._node_content(node, mark_id),
                    children=children,
                )
            )
        return Markup("").join(items)

    def _node_content(self, node: TreeNode, mark_id: str) -> Markup:
        """Show a node's icon, its label as bold or underlined as it says, then its mark.

        The mark's icon is hidden from screen readers, which read its name (at `mark_id`)
        as the button's description, after the label naming it.
        """
        # a label too long for the pane cut short, the icon and the mark kept whole
        styles = [
            style
            for style, is_on in (("font-bold", node.is_bold), ("underline", node.is_underlined))
            if is_on
        ]
        label = Markup('<span class="{}">{}</span>').format(
            " ".join(["truncate", *styles]), node.label
        )
        mark = ""
        if node.mark is not None:
            icon, color = _MARK_ICONS[node.mark]
            text = self._view.mark_text(node.mark)
            mark = Markup(
                '<span class="shrink-0 {color}">{icon}</span><span id="{mark_id}"'
                " hidden>{text}</span>"
            ).format(color=color, icon=_icon(icon), mark_id=mark_id, text=text)
        return Markup("{file_icon}{label}{mark}").format(
            file_icon=_file_icon(node.icon), label=label, mark=mark
        )

    def _post(self, event: str, path: TreePath, *, expanded: bool = False) -> Markup:
        """Get the attributes posting an event of the node at `path`, without swapping it back."""
        values = {"event": event, "path": json.dumps(list(path))}
        if event == "toggle":
            values["expanded"] = str(expanded).lower()
        return Markup(
            """ hx-post="/widget/{}" hx-vals='{}'"""
            ' hx-swap="none"'
        ).format(self.widget_id, json.dumps(values))

    def dispatch(self, event: str, form: Mapping[str, str]) -> None:
        # a disabled tree can't be clicked: a post saying otherwise is refused
        if not self.is_enabled or event not in ("select", "toggle"):
            super().dispatch(event, form)
        path = self._posted_path(form.get("path", ""))
        if path is None or (event == "toggle" and len(self._view.node(path).children) == 0):
            # a node a stale page still shows: swap the tree back as it now is
            self._mark_dirty(self._view, self.widget_id, self._view.nodes)
            return
        if event == "select":
            if path != self._view.selected:
                self._view.selected = path
                self._view.selection_changed.emit(path)
            return
        is_expanded = form.get("expanded") == "true"
        if is_expanded != (path in self._view.expanded):
            self._view.expanded = self._view.expanded_with(path, is_expanded=is_expanded)
            self._view.toggled.emit(path, is_expanded)

    def _posted_path(self, posted: str) -> TreePath | None:
        """Get the path a button posted, if a node of the tree is there."""
        try:
            keys = json.loads(posted)
        except ValueError:
            return None
        if not isinstance(keys, list) or not all(isinstance(key, str) for key in keys):
            return None
        path = tuple(keys)
        return path if path in {path for path, _node in walk_tree(self._view.nodes)} else None


class WebSidebarRenderer(WebRenderer[SidebarView]):
    """An `<aside>`: its title, then its views in a column, left of the pages.

    The main renderer wraps it in a daisyUI drawer (`drawer_html`): a column beside the
    pages on a wide screen, and on a phone a drawer over them, closed by a click beside
    it. A button in the header (`toggle_html`; see `page.js`) retracts and expands the
    column, which the browser does before posting it (`toggle`), like every control
    never swapped back after one. On a phone, it shows and hides the drawer instead.
    The button isn't in the aside's fragment: a swap of the aside brings it along.
    """

    _role = "sidebar"

    def __init__(self, view: SidebarView) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            dict.fromkeys(("title", "toggle_text", "is_expanded"), self._mark_dirty)
        )

    def render(self) -> None:
        super().render()
        self._adopt(self._view.children_views)

    @property
    def drawer_id(self) -> str:
        """The id of the drawer's checkbox, checked while the drawer shows on a phone."""
        return f"{self.widget_id}-drawer"

    def to_html(self, *, oob: bool = False) -> Markup:
        title = self._view.title
        heading = (
            Markup('<h2 class="font-semibold text-primary">{}</h2>').format(title) if title else ""
        )
        content = Markup("").join(
            _view_html(view) for view in self._view.children_views if _is_shown(view)
        )
        name = title or self._view.toggle_text
        retracted = "" if self._view.is_expanded else " data-retracted"
        # bottom padding keeps the last view clear of the fixed status bar
        aside = Markup(
            '<aside {root_attributes}{retracted} aria-label="{name}"'
            ' class="cui-sidebar flex min-h-full w-80 max-w-[85vw] flex-col gap-6 border-r'
            ' border-base-300 bg-base-100 p-4 pb-20">{heading}{content}</aside>'
        ).format(
            root_attributes=self._root_attributes(oob=oob),
            retracted=retracted,
            name=name,
            heading=heading,
            content=content,
        )
        return aside + self.toggle_html(oob=True) if oob else aside

    def toggle_html(self, *, oob: bool = False) -> Markup:
        """Get the header's button retracting and expanding the sidebar.

        `aria-expanded` tells whether the column shows; the page's script keeps it
        telling whether the drawer shows on a phone.
        """
        swap = Markup(' hx-swap-oob="true"') if oob else ""
        expanded = "true" if self._view.is_expanded else "false"
        text = self._view.toggle_text
        # posted by the page's script on a wide screen only, once the column has changed,
        # with whether it is now expanded
        return Markup(
            '<button id="{widget_id}-toggle" type="button"{swap}'
            ' class="btn btn-ghost btn-square btn-sm"'
            ' data-sidebar-toggle="{drawer_id}" aria-controls="{widget_id}"'
            ' aria-expanded="{expanded}" aria-label="{text}" title="{text}"'
            ' hx-post="/widget/{widget_id}" hx-trigger="sidebar-toggle"'
            """ hx-vals='{{"event": "toggle"}}' hx-swap="none">"""
            "{sidebar_icon}</button>"
        ).format(
            widget_id=self.widget_id,
            swap=swap,
            drawer_id=self.drawer_id,
            expanded=expanded,
            text=text,
            sidebar_icon=_icon("sidebar", "size-5"),
        )

    def dispatch(self, event: str, form: Mapping[str, str]) -> None:
        if event != "toggle":
            super().dispatch(event, form)
        is_expanded = form.get("expanded") == "true"
        if is_expanded == self._view.is_expanded:
            return
        with self.stop_refresh():
            self._view.is_expanded = is_expanded
        self._view.toggled.emit(is_expanded)

    def drawer_html(self, content: str) -> Markup:
        """Lay out `content`, the pages' column, beside the sidebar, in a drawer on a phone."""
        return Markup(
            '<div class="cui-drawer drawer lg:drawer-open">'
            '<input id="{drawer_id}" type="checkbox" class="drawer-toggle"'
            ' tabindex="-1" aria-hidden="true">'
            '<div class="drawer-content">{content}</div>'
            '<div class="drawer-side z-30">'
            '<label for="{drawer_id}" class="drawer-overlay"'
            ' aria-label="{toggle_text}"></label>'
            "{to_html}</div></div>"
        ).format(
            drawer_id=self.drawer_id,
            content=content,
            toggle_text=self._view.toggle_text,
            to_html=self.to_html(),
        )


class WebListRenderer(WebRenderer["ListView[Any]"]):
    """The records' views one above the other, each in an item of its own.

    As the records change, the response swaps only the items that changed: an item gone
    is deleted and a new one goes in after its neighbour. So the items kept, the one the
    user is busy in among them, are never swapped back. A change reordering the items
    kept, or anything else changing on the list, swaps the whole list instead. A record's
    view built since is rendered into the session; one gone is dropped from it.
    """

    _role = "list"

    def __init__(self, view: ListView[Any]) -> None:
        super().__init__(view)
        #: the records' views the page shows, as last sent; None until sent
        self._sent: list[View] | None = None
        #: whether more than the records changed since, for which the whole list swaps
        self._is_whole = False
        self._refresh_dispatcher["item_views"] = self._refresh_item_views

    def render(self) -> None:
        super().render()
        self._render_items(self._view.item_views)

    def _render_items(self, views: list[View]) -> None:
        """Render the views built since the list was, into the session, and adopt them all."""
        built_since = [view for view in views if view.renderer is None]
        with self._in_session():
            for view in built_since:
                view.render(RendererType.WEB)
        self._adopt(views)

    def _item_id(self, view: View) -> str:
        return f"{self.widget_id}-item-{id(view)}"

    def _item_html(self, view: View) -> Markup:
        content = _view_html(view)
        return Markup('<div id="{}">{}</div>').format(self._item_id(view), content)

    def to_html(self, *, oob: bool = False) -> Markup:
        views = self._view.item_views
        sent, self._sent = self._sent, list(views)
        is_whole, self._is_whole = self._is_whole, False
        if oob and not is_whole and sent is not None:
            kept = [view for view in sent if view in views]
            if kept == [view for view in views if view in sent]:
                return self._changes_html(sent, views)
        items = Markup("").join(self._item_html(view) for view in views)
        # `cui-list`: its expanders join in one box (see `css/app.css`)
        return Markup('<div {} class="cui-list flex flex-col gap-3">{}</div>').format(
            self._root_attributes(oob=oob), items
        )

    def _changes_html(self, sent: list[View], views: list[View]) -> Markup:
        """Delete the items gone and put each new one after its neighbour, in order."""
        fragments = [
            Markup('<div id="{}" hx-swap-oob="delete"></div>').format(self._item_id(view))
            for view in sent
            if view not in views
        ]
        for index, view in enumerate(views):
            if view in sent:
                continue
            place = (
                f"afterend:#{self._item_id(views[index - 1])}"
                if index > 0
                else f"afterbegin:#{self.widget_id}"
            )
            fragments.append(
                Markup('<div hx-swap-oob="{}">{}</div>').format(place, self._item_html(view))
            )
        return Markup("").join(fragments)

    def _refresh_item_views(
        self, view: ListView[Any], _rendered_object: str, value: list[View]
    ) -> None:
        self._render_items(value)
        # still the views before: the change lands in the view after its renderers hear it
        self._forget([item_view for item_view in view.item_views if item_view not in value])
        dirty = _DIRTY.get()
        if dirty is not None:
            dirty[self.widget_id] = self

    def _forget(self, views: list[View]) -> None:
        """Drop the renderers of `views`, whose records are gone, from the list and the session."""
        gone: deque[View] = deque(views)
        while len(gone) > 0:
            view = gone.popleft()
            gone.extend(view.children_views)
            renderer: Any = view.renderer
            renderers = (
                renderer.renderers if isinstance(renderer, RendererContainer) else [renderer]
            )
            # not a view this backend doesn't render, nor one never rendered
            shown = [
                child
                for child in renderers
                if isinstance(child, WebRenderer) and child._rendered_object is not None  # noqa: SLF001
            ]
            for child in shown:
                if child in self.children:
                    self.children.remove(child)
                if self._target is not None:
                    self._target.renderers.pop(child.widget_id, None)
                    self._target.pending.pop(child.widget_id, None)

    def _mark_dirty(self, view: ListView[Any], rendered_object: str, value: Any) -> None:
        self._is_whole = True
        super()._mark_dirty(view, rendered_object, value)


class WebTabPageRenderer(_BuiltWhenShown[TabPage]):
    """A tab's views in a column, which its tabs put in a panel under its tab.

    Its title, visibility and enabled state are its tab's too: a change swaps its tabs.
    Only the current tab's views are sent: another tab's column is empty until picked.
    """

    _role = "tab_page"

    def __init__(self, view: TabPage) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "title": self._refresh_tab,
                "is_visible": self._refresh_tab,
                "is_enabled": self._refresh_tab,
            }
        )

    def _content_views(self) -> list[View]:
        return self._view.children_views

    @property
    def is_current(self) -> bool:
        """Whether this is the page of the tab shown, whose views are sent."""
        return not isinstance(self.parent, WebTabsRenderer) or self.parent.is_current(self)

    def shows(self, _child: WebRenderer[Any]) -> bool:
        return self.is_current

    def to_html(self, *, oob: bool = False) -> Markup:
        content = Markup("").join(
            _view_html(view)
            for view in self._view.children_views
            if self.is_current and _is_shown(view)
        )
        return Markup('<div {} class="flex flex-col gap-6">{}</div>').format(
            self._root_attributes(oob=oob), content
        )

    def _refresh_tab(self, view: TabPage, rendered_object: str, value: Any) -> None:
        self._refresh_enabled(view, rendered_object, value)
        dirty = _DIRTY.get()
        if dirty is not None and self.parent is not None:
            dirty[self.parent.widget_id] = self.parent


class WebTabsRenderer(WebRenderer[TabView]):
    """A row of tabs (an ARIA tab list), then a panel per tab, only the current one shown.

    Only the current tab's page is sent, the others' left empty: an app's many tabs
    don't weigh on each response, nor the browser's page. The browser shows the tab
    picked, by a click or the arrow keys (see `page.js`), before posting it (`select`):
    its answer fills the panel picked and empties the one left. Like every control, the
    tabs are never swapped back after a pick, only when the server changes them.
    """

    _role = "tabs"
    #: read by `TabView`: it renders only the tabs, and this renderer their views, once shown
    renders_on_demand = True

    def __init__(self, view: TabView) -> None:
        super().__init__(view)
        self._refresh_dispatcher["current_index"] = self._refresh_current_index

    def render(self) -> None:
        super().render()
        for tab in self._view.tabs:
            assert isinstance(tab.renderer, WebTabPageRenderer)  # a tab page's, which the web has
            tab.renderer.defer()
        self._build(self._view.current_index)
        self._adopt(self._view.tabs)

    def _build(self, index: int) -> None:
        """Build the views of the tab at `index`, as it shows: none in a tab view without tabs."""
        for tab in self._view.tabs[index : index + 1]:
            assert isinstance(tab.renderer, WebTabPageRenderer)
            tab.renderer.build()

    def _refresh_current_index(self, view: TabView, rendered_object: str, value: int) -> None:
        self._build(value)  # the view holds it once this returns
        self._mark_dirty(view, rendered_object, value)

    def to_html(self, *, oob: bool = False) -> Markup:
        current = self._view.current_index
        tabs: list[str] = []
        panels: list[str] = []
        for index, tab in enumerate(self._view.tabs):
            assert isinstance(tab.renderer, WebRenderer)  # a tab page's, which the web has
            tab_id, panel_id = f"{self.widget_id}-tab-{index}", f"{self.widget_id}-panel-{index}"
            is_current = index == current
            active = " tab-active" if is_current else ""
            hidden = "" if tab.is_visible else " hidden"
            disabled = "" if tab.is_enabled and self.is_enabled else " disabled"
            # only the current tab in the tab order: the arrow keys move between them
            tabs.append(
                Markup(
                    '<button type="button" role="tab" id="{tab_id}" aria-controls="{panel_id}"'
                    ' aria-selected="{lower}" tabindex="{value}"'
                    ' class="tab{active}" data-tab hx-post="/widget/{widget_id}"'
                    """ hx-vals='{{"event": "select", "index": "{index}"}}' hx-swap='none'"""
                    "{hidden}{disabled}>{title}</button>"
                ).format(
                    tab_id=tab_id,
                    panel_id=panel_id,
                    lower=str(is_current).lower(),
                    value=0 if is_current else -1,
                    active=active,
                    widget_id=self.widget_id,
                    index=index,
                    hidden=hidden,
                    disabled=disabled,
                    title=tab.title,
                )
            )
            panels.append(
                Markup(
                    '<div role="tabpanel" id="{panel_id}"'
                    ' aria-labelledby="{tab_id}"{value}>{to_html}</div>'
                ).format(
                    panel_id=panel_id,
                    tab_id=tab_id,
                    value="" if is_current else " hidden",
                    to_html=tab.renderer.to_html(),
                )
            )
        return Markup(
            '<div {root_attributes} class="flex flex-col gap-4">'
            '<div role="tablist" class="tabs tabs-border">{join}</div>'
            "{join2}</div>"
        ).format(
            root_attributes=self._root_attributes(oob=oob),
            join=Markup("").join(tabs),
            join2=Markup("").join(panels),
        )

    def dispatch(self, event: str, form: Mapping[str, str]) -> None:
        if event != "select":
            super().dispatch(event, form)
        try:
            index = int(form.get("index", ""))
        except ValueError:
            return
        if not 0 <= index < len(self._view.tabs) or index == self._view.current_index:
            return
        if not self._view.tabs[index].is_enabled:
            raise UnsupportedEventError(self, event)
        left = self._view.tabs[self._view.current_index]
        with self.stop_refresh():
            self._view.current_index = index
        self._build(index)
        dirty = _DIRTY.get()
        assert dirty is not None  # a browser event's, collected by `handle_event`
        for tab in (left, self._view.tabs[index]):
            assert isinstance(tab.renderer, WebRenderer)  # a tab page's, which the web has
            dirty[tab.renderer.widget_id] = tab.renderer
        self._view.current_changed.emit(index)

    def is_current(self, page: WebRenderer[Any]) -> bool:
        """Whether `page` is the renderer of the current tab's page."""
        current = self._view.current_tab
        return current is not None and current.renderer is page


class WebGridRenderer(WebRenderer[GridView]):
    """Views in a grid's cells: equally wide columns, rows as tall as their views.

    The columns and each view's cell are variables rather than a class per count; a cell
    placed rather than flowed stays where it is when an earlier one hides. A grid
    narrower than 42rem stacks its views instead, in one column, row by row: only the
    wide grid uses the variables.
    """

    _role = "grid"

    def render(self) -> None:
        super().render()
        self._adopt(self._view.children_views)

    def to_html(self, *, oob: bool = False) -> Markup:
        cells = Markup("").join(
            Markup(
                '<div class="min-w-0 has-[>[hidden]]:hidden @2xl:[grid-area:var(--area)]"'
                ' style="--area: {value} / {value2} / span {row_span} / span {column_span}">'
                "{to_html}</div>"
            ).format(
                value=row + 1,
                value2=column + 1,
                row_span=row_span,
                column_span=column_span,
                to_html=_view_html(view),
            )
            for view, (row, column, row_span, column_span) in self._view.positioned_views
            if _is_shown(view)
        )
        columns = f"repeat({self._view.column_count}, minmax(0, 1fr))"
        # the grid's own width is queried from its root, the views laid out inside it
        return Markup(
            '<div {root_attributes} class="@container">'
            '<div class="grid grid-cols-1 items-start gap-6 @2xl:grid-cols-(--columns)"'
            ' style="--columns: {columns}">{cells}</div></div>'
        ).format(root_attributes=self._root_attributes(oob=oob), columns=columns, cells=cells)


#: the main column's width, following the shown page's `PageView.width`: switching pages
#: only swaps the router, so CSS picks the width from the page neither hidden nor in a
#: hidden element
_MAIN_WIDTHS = (
    " has-[[data-width=wide]:not([hidden],[hidden]_*)]:max-w-6xl"
    " has-[[data-width=full]:not([hidden],[hidden]_*)]:max-w-none"
)


def page_path(route: str) -> str:
    """Get the address of the page on `route` (routes are made to fit in one)."""
    return f"/{route}"


class WebRouterRenderer(WebRenderer[Router]):
    """The current page, and the toolbar of the pages' links.

    Only the current page is sent, in a slot of its own, which leaves the page's own
    `is_visible` to the page. An app's many pages don't weigh on each response, nor the
    browser's page. Navigating swaps the router, so the page left goes, and the page
    shown comes as it stands now. The toolbar has no fragment of its own: the main
    renderer puts it in the header, and each link swaps on its own.
    """

    _role = "router"
    #: read by `Router`: it renders only the page shown, and this renderer the others once shown
    renders_on_demand = True

    def __init__(self, view: Router) -> None:
        super().__init__(view)
        self._refresh_dispatcher["current_route"] = self._refresh_current_route

    def render(self) -> None:
        super().render()
        for page in self._view.pages:
            if page.renderer is None:  # not shown, so not built by the router's view
                renderer = WebPageRenderer(page)
                page.renderer = renderer
                renderer.render()
                renderer.defer()
        # not the toolbar: apart from the pages, like Qt's, it still switches them
        self._adopt(self._view.pages)
        # the children are rendered first: make each page's action a link to it
        for page in self._view.pages:
            assert isinstance(page.action.renderer, WebActionRenderer)
            page.action.renderer.placement = Placement.PAGE
            page.action.renderer.href = page_path(page.route)

    def _refresh_current_route(self, view: Router, rendered_object: str, value: str) -> None:
        page = self._view.page(value)
        if page is not None:
            assert isinstance(page.renderer, WebPageRenderer)  # rendered with the router
            page.renderer.build()
        self._mark_dirty(view, rendered_object, value)

    def shows(self, child: WebRenderer[Any]) -> bool:
        return self.is_current(child)

    def is_current(self, page: WebRenderer[Any]) -> bool:
        """Whether `page` is the renderer of the page shown."""
        return any(
            view.renderer is page and view.route == self._view.current_route
            for view in self._view.pages
        )

    def to_html(self, *, oob: bool = False) -> Markup:
        slots: list[str] = []
        for page in self._view.pages:
            assert isinstance(page.renderer, WebRenderer)  # a page's, which the web has
            if page.route == self._view.current_route:
                slots.append(
                    Markup('<div data-route="{route}">{to_html}</div>').format(
                        route=page.route, to_html=page.renderer.to_html()
                    )
                )
        return Markup("<div {}>{}</div>").format(
            self._root_attributes(oob=oob), Markup("").join(slots)
        )

    def toolbar_html(self) -> Markup:
        links = Markup("").join(
            page.action.renderer.to_html()
            for page in self._view.pages
            if isinstance(page.action.renderer, WebActionRenderer)
        )
        # a row of its own under the brand on a narrow screen, next to it on a wider one
        return Markup(
            '<nav aria-label="Pages" class="tabs tabs-box tabs-sm order-last w-full'
            ' flex-nowrap overflow-x-auto sm:order-none sm:w-auto">{}</nav>'
        ).format(links)


#: first segments of the backend's own addresses, which no page's address can take
RESERVED_ROUTES: Final = frozenset({"icon", "jobs", "reload", "state", "static", "widget"})


def check_routes(main_view: MainView) -> None:
    """Raise `ValueError` if a page of the main view's router has an address the backend uses."""
    router = next((view for view in main_view.children_views if isinstance(view, Router)), None)
    reserved = sorted(
        page.route for page in (router.pages if router else []) if page.route in RESERVED_ROUTES
    )
    if len(reserved) > 0:
        msg = f"The web backend uses the address of the routes {reserved}: rename them."
        raise ValueError(msg)


def _theme_option(choice: str, text: str) -> Markup:
    # picked by `page.js`, which also closes the dropdown
    return Markup(
        '<li><button type="button" class="theme-option" data-theme-option="{}">{}</button></li>'
    ).format(choice, text)


#: the header's Theme menu: Light, Dark, or System (the browser's preference). Its button
#: shows the theme in use, the sun or the moon, however it was chosen
_THEME_MENU: Final = Markup(
    '<div class="dropdown dropdown-end">'
    '<div tabindex="0" role="button" class="theme-toggle btn btn-ghost btn-sm btn-square"'
    ' aria-label="Theme" title="Theme">'
    '<svg class="icon-sun size-5" viewBox="0 0 24 24" fill="none" stroke="currentColor"'
    ' stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41'
    'M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/>'
    "</svg>"
    '<svg class="icon-moon size-5" viewBox="0 0 24 24" fill="none" stroke="currentColor"'
    ' stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/></svg></div>'
    '<ul tabindex="0" class="menu dropdown-content z-30 mt-2 w-40 rounded-box border'
    ' border-base-300 bg-base-100 p-2 shadow-lg">'
    "{theme_option}{theme_option2}"
    "{theme_option3}</ul></div>"
).format(
    theme_option=_theme_option("composeui", "Light"),
    theme_option2=_theme_option("composeui-dark", "Dark"),
    theme_option3=_theme_option("system", "System"),
)


class WebMainRenderer(MainRenderer[MainView, str]):
    """Renders the whole page; never swapped itself, so its attributes are no-ops."""

    draws_on_main_thread = False
    saves_in_place = False  # `state_filepath` is the name of the user's file, not a path here

    def __init__(self, view: MainView) -> None:
        super().__init__(view)
        #: set by `MainView.close()` (the Exit action); the route then ends the session
        self.is_closed = False
        #: the files `MainView.download` gave, until the page fetches them
        self.downloads = Downloads()
        self._target: RenderTarget | None = None
        self._refresh_dispatcher.update(
            dict.fromkeys(
                (
                    "is_visible",
                    "is_enabled",
                    "minimum_width",
                    "minimum_height",
                    "state_filepath",
                    # in the page's header and `<title>`: the session swaps them
                    "title",
                ),
                self._noop,
            )
        )

    @property
    def router(self) -> Router | None:
        """The main view's router, whose pages have addresses; None without one."""
        return next((view for view in self._view.children_views if isinstance(view, Router)), None)

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = f"cui-{id(self._view)}-main"
            self._target = _RENDER_TARGET.get()
        check_routes(self._view)
        # the children are rendered first: hand the Open actions the file type they load
        views: list[View] = list(self._view.children_views)
        while len(views) > 0:
            view = views.pop()
            views.extend(view.children_views)
            if isinstance(view, OpenFileAction) and isinstance(view.renderer, WebActionRenderer):
                view.renderer.accept = self._view.extension

    def call_on_main_thread(self, callback: Callable[[], None]) -> None:
        call_in_session(self._target, callback)

    def page_html(self, reload_instance: str | None = None, *, session_tag: str = "") -> str:
        """Get the whole page; with `reload_instance`, it reloads once its server restarts.

        Its requests carry `session_tag`, the `WebSession.page_tag` of its session, if any.
        """
        menus: list[str] = []
        toolbars: list[str] = []
        content: list[str] = []
        status_bar = ""
        toolbar = ""
        sidebar: WebSidebarRenderer | None = None
        for child_view in self._view.children_views:
            if isinstance(child_view, FormRowView):
                content.append(_view_html(child_view))  # its parts, as a form shows them
                continue
            if not isinstance(child_view.renderer, WebRenderer):
                continue
            if isinstance(child_view, DialogView):
                continue  # see `_dialogs_html`
            if isinstance(child_view, StatusBar):
                status_bar = child_view.renderer.to_html()
            elif isinstance(child_view, Menu):
                menus.append(child_view.renderer.to_html())
            elif isinstance(child_view, ToolBar):
                toolbars.append(child_view.renderer.to_html())
            elif isinstance(child_view.renderer, WebSidebarRenderer):
                sidebar = child_view.renderer
            else:
                if child_view is self.router and isinstance(child_view.renderer, WebRouterRenderer):
                    toolbar = child_view.renderer.toolbar_html()
                content.append(child_view.renderer.to_html())
        # the pages' toolbar wraps to a row of its own on a narrow screen
        wrap = " flex-wrap" if toolbar else ""
        # bottom padding keeps the last row clear of the fixed status bar
        main = Markup(
            '<main class="mx-auto {} px-4 pt-8 pb-20">'
            '<div class="card border border-base-300 bg-base-100 shadow-md">'
            '<div class="card-body gap-6 p-6">'
            "{}"
            "</div></div></main>"
        ).format(
            {
                PageWidth.NARROW: "max-w-3xl",
                PageWidth.WIDE: "max-w-6xl",
                PageWidth.FULL: "max-w-none",
            }[self._view.width]
            + _MAIN_WIDTHS,
            Markup("").join(content),
        )
        return get_page(
            self._view.title,
            # sticky: the menus stay at hand however long the form is
            Markup(
                '<header class="navbar sticky top-0 z-20 min-h-14{wrap} gap-3 border-b'
                " border-base-300"
                ' bg-base-100 px-4">'
                "{value}{brand_html}{toolbar}"
                '<nav class="ml-auto flex items-center gap-1">'
                "{join}{join2}</nav>"
                "{THEME_MENU}"
                "</header>"
                "{value2}"
                "{status_bar}{dialogs_html}"
            ).format(
                wrap=wrap,
                value=sidebar.toggle_html() if sidebar else "",
                brand_html=self.brand_html(),
                toolbar=toolbar,
                join=Markup("").join(toolbars),
                join2=Markup("").join(menus),
                THEME_MENU=_THEME_MENU,
                value2=sidebar.drawer_html(main) if sidebar else main,
                status_bar=status_bar,
                dialogs_html=self._dialogs_html(),
            ),
            self._view.language,
            pollers=jobs_poller(is_running=self._view.jobs.is_running)
            + reload_poller(reload_instance),
            max_upload_size=self._view.max_upload_size,
            session_tag=session_tag,
            icon=self._app_icon_url(),
            downloads=downloads_marker(self.downloads.tickets()),
        )

    def _app_icon_url(self) -> str | None:
        app_icon = self._view.app_icon
        return None if app_icon is None else icon_url(str(app_icon))

    def _dialogs_html(self) -> Markup:
        """Render every dialog of the tree, outside the pages hiding their content."""
        dialogs: list[str] = []
        views: list[View] = list(self._view.children_views)
        while len(views) > 0:
            view = views.pop(0)
            views.extend(view.children_views)
            if isinstance(view, DialogView) and isinstance(view.renderer, WebDialogRenderer):
                dialogs.append(view.renderer.to_html())
        return Markup("").join(dialogs)

    def brand_html(self, *, oob: bool = False) -> Markup:
        """Show the app's title after its icon, or a badge of its initial without one."""
        title = self._view.title
        url = self._app_icon_url()
        badge = (
            Markup(
                '<span aria-hidden="true" class="grid size-8 shrink-0 place-items-center'
                ' rounded-field bg-primary text-sm font-bold text-primary-content">{}</span>'
            ).format(title.strip()[:1].upper())
            if url is None
            else Markup(
                '<img src="{}" alt="" aria-hidden="true" class="size-8 shrink-0 object-contain">'
            ).format(url)
        )
        swap = Markup(' hx-swap-oob="true"') if oob else ""
        return (
            # on a narrow screen, the title gives way to the header's buttons rather than
            # pushing them to a row of their own
            Markup(
                '<div id="cui-brand"{swap} class="flex min-w-0 flex-1 basis-0 items-center gap-2'
                ' sm:flex-none sm:basis-auto">'
                "{badge}"
                '<h1 class="truncate text-lg font-semibold">{title}</h1></div>'
            ).format(swap=swap, badge=badge, title=title)
        )

    def close(self) -> None:
        self.is_closed = True

    def open_file(self) -> Path | None:
        # no browser-side path to return: the web backend uploads instead (M7), and
        # None is what `FileMenu`'s callbacks already treat as "cancelled"
        return None

    def save_file(self) -> Path | None:
        return None  # see `open_file`; saving is a browser download (M7)

    def download(self, file: DownloadedFile) -> None:
        # the session's next answer names it (`downloads_marker`)
        self.downloads.add(file)

    @staticmethod
    def _noop(_view: MainView, _rendered_object: str, _value: Any) -> None:
        pass

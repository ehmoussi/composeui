"""The web renderers of actions: menus, menu buttons, toolbars, and the actions in them."""

from __future__ import annotations

import enum
import re
from typing import TYPE_CHECKING, Any

from markupsafe import Markup
from typing_extensions import override

from composeui.core._views.actions import (
    ExitAppAction,
    NewAction,
    OpenFileAction,
    SaveAction,
    SaveAsAction,
)
from composeui.core.view import (
    ActionView,
    Menu,
    MenuButtonView,
    PickFileAction,
    SeparatorAction,
    ToolBar,
    View,
)
from composeui.webcore._renderers.controls import _BUTTON_CLASSES
from composeui.webcore.page import SAVE_FORM_ID

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

from composeui.webcore.webrenderer import (
    UnsupportedEventError,
    WebRenderer,
    _file_icon,
    _file_types,
    _icon,
)

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

    @override
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
            '<div id="{widget_id}"{oob_attribute} data-cui="{role}" class="flex items-center'
            ' gap-1">{join}{dropdown}</div>'
        ).format(
            widget_id=self.widget_id,
            oob_attribute=oob_attribute,
            role=self._role,
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

    @override
    def _mark_dirty(self, view: ActionView, rendered_object: str, value: Any) -> None:
        # e.g. the entry of a page outside a router: no element on the page to swap
        if self._is_shown:
            super()._mark_dirty(view, rendered_object, value)

    @override
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
        # `is_enabled`: an entry of a disabled menu button is disabled with it
        if not self.is_enabled:
            item = Markup(
                '<button type="button" class="justify-between" disabled>{}</button>'
            ).format(label)
        else:
            item = self._active_html(Markup('class="justify-between"'), label, key)
        menu_disabled = "" if self.is_enabled else Markup(' class="menu-disabled"')
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
            '{tooltip} hx-post="/_composeui/widget/{widget_id}"'
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
                ' class="hidden" hx-post="/_composeui/state" hx-encoding="multipart/form-data"'
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
                ' class="hidden" hx-post="/_composeui/widget/{widget_id}/file"'
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
            """ hx-post="/_composeui/widget/{widget_id}" hx-vals='{{"event": "triggered"}}'"""
            ' hx-swap="none" {CLOSE_DROPDOWN}{key}>{label}</button>'
        ).format(
            attributes=attributes,
            widget_id=self.widget_id,
            CLOSE_DROPDOWN=_CLOSE_DROPDOWN,
            key=key,
            label=label,
        )

    @override
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

    @override
    def to_html(self, *, oob: bool = False) -> Markup:
        if self.is_in_toolbar:
            return Markup(
                '<div {} role="separator"'
                ' aria-orientation="vertical" class="mx-1 h-5 w-px bg-base-300"></div>'
            ).format(self._root_attributes(oob=oob))
        return Markup('<li {} role="separator"><hr class="my-1 border-base-300 p-0"></li>').format(
            self._root_attributes(oob=oob)
        )


class WebMenuButtonRenderer(WebRenderer[MenuButtonView]):
    """A button of the page opening a dropdown of its actions, as the header's menus do."""

    _role = "menu_button"

    def __init__(self, view: MenuButtonView) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update({"text": self._mark_dirty, "variant": self._mark_dirty})

    @override
    def render(self) -> None:
        super().render()
        # disabled with the button, and swapped with it
        self._adopt(self._view.children_views)

    @override
    def to_html(self, *, oob: bool = False) -> Markup:
        view = self._view
        items = _between_items(
            [
                (isinstance(child, SeparatorAction), child.renderer.to_html())
                for child in view.children_views
                if isinstance(child.renderer, WebRenderer)
            ]
        )
        variant = _BUTTON_CLASSES[view.variant]
        # a focusable `div`, as daisyUI asks: Safari doesn't focus a clicked button, and
        # the dropdown opens while its trigger has the focus
        trigger = (
            Markup(
                '<div tabindex="0" role="button" class="btn {variant} gap-1 pr-3"'
                ' aria-haspopup="menu">{text}<span class="opacity-60">{chevron}</span></div>'
            )
            if self.is_enabled
            else Markup(
                '<div role="button" class="btn {variant} btn-disabled gap-1 pr-3"'
                ' aria-disabled="true">{text}<span class="opacity-60">{chevron}</span></div>'
            )
        ).format(variant=variant, text=view.text, chevron=_icon("chevron"))
        return Markup(
            # `data-fit-dropdown`: the page's script keeps the list within the window
            '<div {root_attributes} data-variant="{kind}" data-fit-dropdown'
            ' class="dropdown self-start">'
            "{trigger}"
            # as wide as its longest item, its text and shortcut on one line
            '<ul tabindex="-1" class="menu dropdown-content z-30 mt-1 w-max min-w-48'
            ' rounded-box border border-base-300 bg-base-100 p-2 shadow-lg">{items}</ul>'
            "</div>"
        ).format(
            root_attributes=self._root_attributes(oob=oob),
            kind=view.variant.name.lower(),
            trigger=trigger,
            items=Markup("").join(item for (_, item) in items),
        )


class WebToolBarRenderer(WebRenderer[ToolBar]):
    """A row of buttons in the header, one per action, posting `triggered`."""

    _role = "toolbar"

    def __init__(self, view: ToolBar) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update({"title": self._mark_dirty})

    @override
    def render(self) -> None:
        super().render()
        self._adopt(self._view.children_views)
        # the children are rendered first: make them a toolbar's
        for child in self._view.children_views:
            if isinstance(child.renderer, WebActionRenderer):
                child.renderer.placement = Placement.TOOL
            elif isinstance(child.renderer, WebSeparatorRenderer):
                child.renderer.is_in_toolbar = True

    @override
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

"""The web renderers of choices: radio groups, combo boxes and check lists."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Callable, TypeVar, cast

from markupsafe import Markup

from composeui.core._views.choices import walk_tree
from composeui.core.renderer import ViewLike
from composeui.core.view import TreeView
from composeui.webcore.changes import _DIRTY

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from composeui.core.view import TreeNode, TreePath
import hashlib
from typing import TYPE_CHECKING, Generic

from typing_extensions import Protocol

from composeui.core.view import SEARCH_DELAY_MS
from composeui.webcore.webrenderer import _MARK_ICONS, WebRenderer, _file_icon, _icon

if TYPE_CHECKING:
    from collections.abc import Mapping

    from composeui.core._views.choices import ChoicesShown
    from composeui.core.signal import Signal


TValue = TypeVar("TValue")


class ValuesViewLike(ViewLike, Protocol, Generic[TValue]):
    value: TValue | None
    values: dict[str, TValue]
    value_changed: Signal[TValue | None]

    @property
    def options(self) -> list[tuple[str, str]]: ...

    def serialize_value(self) -> str | None: ...

    def deserialize_value(self, key: str | None) -> TValue | None: ...


class _WebValuesRenderer(WebRenderer[ValuesViewLike[TValue]], Generic[TValue]):
    """A choice among `values`, identified on the wire by its key (see `options`).

    The same key as `serialize_value`/`deserialize_value`, which also turn a stale or
    bogus key into `None` with a warning instead of the `ValueError` `_check_value`
    would raise.
    """

    def __init__(self, view: ValuesViewLike[TValue]) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "value": self._mark_dirty,
                "values": self._mark_dirty,
            }
        )

    def dispatch(self, event: str, form: Mapping[str, str]) -> None:
        if event != "change":
            super().dispatch(event, form)
        # the field is named after the widget id, so two groups never share a radio set
        key = form.get(self.widget_id, "")
        value = None if key == "" else self._view.deserialize_value(key)
        if value == self._view.value:
            return
        with self.stop_refresh():
            self._view.value = value
        self._view.value_changed.emit(value)

    def _htmx_attributes(self) -> Markup:
        return Markup(
            ' name="{}" hx-post="/widget/{}" hx-trigger="change"'
            ' hx-vals=\'{{"event": "change"}}\' hx-swap="none"'
        ).format(self.widget_id, self.widget_id)


class WebRadioGroupRenderer(_WebValuesRenderer[TValue]):
    _role = "radio_group"
    is_labelable = False

    def to_html(self, *, oob: bool = False) -> Markup:
        selected = self._view.serialize_value()
        disabled = "" if self.is_enabled else " disabled"
        options = Markup("").join(
            Markup(
                '<label class="label cursor-pointer gap-2 text-base-content">'
                '<input type="radio" class="radio radio-sm radio-primary" value="{key}"'
                "{value}{htmx_attributes}"
                ' autocomplete="off"{disabled}>'
                "{label}</label>"
            ).format(
                key=key,
                value=" checked" if key == selected else "",
                htmx_attributes=self._htmx_attributes(),
                disabled=disabled,
                label=label,
            )
            for key, label in self._view.options
        )
        return Markup(
            '<div {root_attributes}{row_attributes} role="radiogroup" class="flex flex-wrap gap-x-6'
            ' gap-y-2">{options}</div>'
        ).format(
            root_attributes=self._root_attributes(oob=oob),
            row_attributes=self._row_attributes(),
            options=options,
        )


class WebComboBoxRenderer(_WebValuesRenderer[TValue]):
    _role = "combobox"

    def to_html(self, *, oob: bool = False) -> Markup:
        selected = self._view.serialize_value()
        disabled = "" if self.is_enabled else " disabled"
        # an empty choice only while nothing is selected, as Qt's combobox shows nothing
        empty = Markup('<option value="" selected></option>') if selected is None else ""
        options = Markup("").join(
            Markup('<option value="{key}"{value}>{label}</option>').format(
                key=key, value=" selected" if key == selected else "", label=label
            )
            for key, label in self._view.options
        )
        return Markup(
            '<select {root_attributes}{row_attributes} class="select w-full"{htmx_attributes}'
            ' autocomplete="off"{disabled}>{empty}{options}</select>'
        ).format(
            root_attributes=self._root_attributes(oob=oob),
            row_attributes=self._row_attributes(),
            htmx_attributes=self._htmx_attributes(),
            disabled=disabled,
            empty=empty,
            options=options,
        )


class MultiValuesViewLike(ViewLike, Protocol):
    selected: list[Any]
    has_search: bool
    search: str
    has_check_all: bool
    check_all_text: str
    search_text: str
    selected_changed: Signal[list[Any]]

    @property
    def shown(self) -> ChoicesShown: ...

    def select_keys(self, keys: Mapping[str, bool]) -> bool: ...

    def check_all(self, *, is_checked: bool) -> bool: ...


#: the attributes of a choice of several values that the web shows, each swapping it whole
_CHOICES_ATTRIBUTES = (
    "values",
    "selected",
    "search",
    "has_search",
    "has_check_all",
    "check_all_text",
    "search_text",
)


class WebCheckListRenderer(WebRenderer[MultiValuesViewLike]):
    """A list of check boxes, with a search field and a check-all box, each posting its change.

    A box posts its key and its state, not a flip, and so does the check-all box: a post
    twice leaves the same choice.
    What the user's change alters swaps apart (`_mark_parts`): the check-all box, the list,
    or a drop-down list's summary, never the element the user is on, which keeps its focus.
    A change of the app's swaps the whole.
    """

    _role = "check_list"
    is_labelable = False

    def __init__(self, view: MultiValuesViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(dict.fromkeys(_CHOICES_ATTRIBUTES, self._mark_dirty))
        #: the parts to swap, unless the whole is
        self._dirty_parts: set[str] = set()
        self._is_whole_dirty = False

    def _mark_dirty(self, view: MultiValuesViewLike, rendered_object: str, value: Any) -> None:
        self._is_whole_dirty = True
        super()._mark_dirty(view, rendered_object, value)

    def _mark_parts(self, *parts: str) -> None:
        """Swap these parts: "all", "list", or "summary"."""
        # only an event marks parts, inside its request
        self._dirty_parts.update(parts)
        cast("dict[str, WebRenderer[Any]]", _DIRTY.get())[self.widget_id] = self

    def to_html(self, *, oob: bool = False) -> Markup:
        parts, self._dirty_parts = self._dirty_parts, set()
        is_whole, self._is_whole_dirty = self._is_whole_dirty or not oob or not parts, False
        if is_whole:
            return self._whole_html(oob=oob)
        shown = self._view.shown
        renders: dict[str, Callable[..., Markup]] = {
            "all": self._all_html,
            "list": self._list_html,
            "summary": self._summary_html,
        }
        return Markup("").join(
            render(shown, oob=True) for part, render in renders.items() if part in parts
        )

    def _whole_html(self, *, oob: bool) -> Markup:
        return Markup('<div {root_attributes}{row_attributes} role="group">{content}</div>').format(
            root_attributes=self._root_attributes(oob=oob),
            row_attributes=self._row_attributes(),
            content=self._content_html(self._view.shown),
        )

    def _content_html(self, shown: ChoicesShown) -> Markup:
        """Render the search field, the check-all box and the list."""
        return Markup('<div class="flex flex-col gap-2">{search}{all}{list}</div>').format(
            search=self._search_html(),
            all=self._all_html(shown, oob=False),
            list=self._list_html(shown, oob=False),
        )

    def _post(self, values: Mapping[str, str]) -> Markup:
        """Get the attributes posting an event of the view, without swapping its element back."""
        return Markup(' hx-post="/widget/{}" hx-vals=\'{}\' hx-swap="none"').format(
            self.widget_id, json.dumps(values)
        )

    def _oob(self, *, oob: bool) -> Markup:
        return Markup(' hx-swap-oob="true"') if oob else Markup()

    def _disabled(self) -> Markup:
        return Markup("") if self.is_enabled else Markup(" disabled")

    def _search_html(self) -> Markup:
        if not self._view.has_search:
            return Markup()
        return Markup(
            '<label class="input input-sm w-full">{search_icon}'
            '<input id="{widget_id}-search" type="search" name="search" value="{search}"'
            ' placeholder="{search_text}" aria-label="{search_text}"'
            ' hx-trigger="input changed delay:{delay}ms, search"{post}'
            ' hx-sync="this:queue last" autocomplete="off"{disabled}></label>'
        ).format(
            search_icon=_icon("search"),
            widget_id=self.widget_id,
            search=self._view.search,
            search_text=self._view.search_text,
            delay=SEARCH_DELAY_MS,
            post=self._post({"event": "search"}),
            disabled=self._disabled(),
        )

    def _all_html(self, shown: ChoicesShown, *, oob: bool) -> Markup:
        if not self._view.has_check_all:
            return Markup('<span id="{}-all" hidden{}></span>').format(
                self.widget_id, self._oob(oob=oob)
            )
        # partly checked only through the page's script, which reads `data-indeterminate`
        state = {True: " checked", False: "", None: " data-indeterminate"}[shown.all_checked]
        # its own id, so htmx gives it the focus back when it's swapped
        return Markup(
            '<label id="{widget_id}-all" class="label cursor-pointer gap-2 text-base-content'
            ' font-medium"{oob}>'
            '<input id="{widget_id}-all-box" type="checkbox"'
            ' class="checkbox checkbox-sm checkbox-primary"'
            ' name="checked" value="on"{state} hx-trigger="change"{post}'
            ' autocomplete="off"{disabled}>{text}</label>'
        ).format(
            widget_id=self.widget_id,
            oob=self._oob(oob=oob),
            state=state,
            post=self._post({"event": "all"}),
            disabled=self._disabled(),
            text=self._view.check_all_text,
        )

    def _box_id(self, key: str) -> str:
        """Get the id of a choice's box: the same as long as its key, for htmx to focus it again.

        After a swap, htmx gives the focus to the element with the id of the one that had it.
        A digest, as a key is any text, and an id holds no space. It keeps a drop-down list
        open, which is open while the focus is in it.
        """
        return f"{self.widget_id}-box-{hashlib.blake2s(key.encode(), digest_size=8).hexdigest()}"

    def _list_html(self, shown: ChoicesShown, *, oob: bool) -> Markup:
        boxes = Markup("").join(
            Markup(
                '<label class="label cursor-pointer gap-2 text-base-content">'
                '<input id="{box_id}" type="checkbox" class="checkbox checkbox-sm checkbox-primary"'
                ' name="checked" value="on"{checked} hx-trigger="change"{post}'
                ' autocomplete="off"{disabled}>{label}</label>'
            ).format(
                box_id=self._box_id(key),
                checked=Markup(" checked") if is_checked else Markup(),
                post=self._post({"event": "toggle", "key": key}),
                disabled=self._disabled(),
                label=label,
            )
            for key, label, is_checked in shown.options
        )
        return Markup(
            '<div id="{widget_id}-list" class="flex max-h-96 flex-col gap-1 overflow-y-auto"'
            "{oob}>{boxes}</div>"
        ).format(widget_id=self.widget_id, oob=self._oob(oob=oob), boxes=boxes)

    def _summary_html(self, _shown: ChoicesShown, *, oob: bool) -> Markup:
        """Render what a closed drop-down list shows: a check list has none."""
        return Markup()

    def dispatch(self, event: str, form: Mapping[str, str]) -> None:
        if event == "toggle":
            with self.stop_refresh():
                is_changed = self._view.select_keys({form.get("key", ""): "checked" in form})
            # unchanged: a stale page, shown again as the view is
            self._after_user_change(
                ("all", "summary") if is_changed else ("all", "list", "summary"),
                is_changed=is_changed,
            )
        elif event == "all":
            # the box's state as the page showed it change, partly checked to checked: not
            # the server's, which a stale page may not show
            with self.stop_refresh():
                is_changed = self._view.check_all(is_checked="checked" in form)
            # the box clicked stays, holding the focus, unless a stale page showed it wrong
            parts = ("list", "summary") if is_changed else ("all", "list", "summary")
            self._after_user_change(parts, is_changed=is_changed)
        elif event == "search":
            with self.stop_refresh():
                self._view.search = form.get("search", "")
            self._after_user_change(("all", "list"), is_changed=False)
        else:
            super().dispatch(event, form)

    def _after_user_change(self, parts: tuple[str, ...], *, is_changed: bool) -> None:
        self._mark_parts(*parts)
        if is_changed:
            self._view.selected_changed.emit(self._view.selected)


class WebMultiComboBoxRenderer(WebCheckListRenderer):
    """A drop-down list of check boxes: daisyUI's dropdown, open while the focus is in it."""

    _role = "multi_combobox"

    def __init__(self, view: MultiValuesViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {"empty_text": self._mark_dirty, "count_text": self._mark_dirty}
        )

    def _whole_html(self, *, oob: bool) -> Markup:
        shown = self._view.shown
        return Markup(
            '<div {root_attributes} class="dropdown w-full">'
            '{summary}<div tabindex="-1" class="dropdown-content card z-30 mt-2 w-full'
            ' bg-base-100 p-4 shadow-lg">{content}</div></div>'
        ).format(
            root_attributes=self._root_attributes(oob=oob),
            summary=self._summary_html(shown, oob=False),
            content=self._content_html(shown),
        )

    def _summary_html(self, shown: ChoicesShown, *, oob: bool) -> Markup:
        # a div, not a button: daisyUI's dropdown opens as it takes the focus, which a
        # button doesn't take on every browser's click
        return Markup(
            '<div id="{widget_id}-summary" tabindex="{tabindex}" role="button"'
            '{row_attributes} class="select w-full{disabled_class}"{oob}>{summary}</div>'
        ).format(
            widget_id=self.widget_id,
            tabindex=0 if self.is_enabled else -1,
            row_attributes=self._row_attributes(),
            disabled_class=Markup("")
            if self.is_enabled
            else Markup(" pointer-events-none opacity-50"),
            oob=self._oob(oob=oob),
            summary=shown.summary,
        )


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

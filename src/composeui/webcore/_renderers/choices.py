"""The web renderers of choices: radio groups, combo boxes and check lists."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any, Callable, Generic, TypeVar, cast

from markupsafe import Markup
from typing_extensions import Protocol

from composeui.core.renderer import ViewLike
from composeui.core.view import SEARCH_DELAY_MS
from composeui.webcore.changes import _DIRTY
from composeui.webcore.webrenderer import WebRenderer, _icon

if TYPE_CHECKING:
    from collections.abc import Mapping

    from composeui.core.signal import Signal
    from composeui.core.view import ChoicesShown


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

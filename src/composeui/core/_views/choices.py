"""The views that choose among values: radio groups, combo boxes, lists, trees."""

from __future__ import annotations

import enum
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Generic,
    Optional,
    TypeVar,
    cast,
)

import attrs
from typing_extensions import override

from composeui.core._views.base import (
    CONVERTER,
    LOGGER,
    OMIT,
    UI_TEXT,
    View,
    _fixed,
    define_view,
    notify_renderer,
)
from composeui.core.reactivity import (
    set_value,
)
from composeui.core.signal import Signal
from composeui.core.translation import (
    T,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping

    from attrs import AttrsInstance


TValue = TypeVar("TValue")


class ChoicesMixin(Generic[TValue]):
    """What a choice among `values` has, whether of one value or several: each value's key.

    A value is saved and sent by its key, not by its label, which changes with the app's
    language. Its subclasses hold `values`, and the choice in their `choice_field`.
    """

    #: the field of the choice made, which a study saves by its keys
    choice_field: ClassVar[str]

    if TYPE_CHECKING:
        values: dict[str, TValue]

    @staticmethod
    def _value_key(index: int, value: TValue) -> str:
        """Get the key `value`, at `index` in `values`, is saved and sent by.

        Not its label, which changes with the app's language: an enum member's name, a
        string itself, else its position.
        """
        if isinstance(value, enum.Enum):
            return value.name
        if isinstance(value, str):
            return value
        return str(index)

    @property
    def options(self) -> list[tuple[str, str]]:
        """Get each of `values` as its key (see `_value_key`) and its label, in order."""
        return [
            (self._value_key(index, value), label)
            for index, (label, value) in enumerate(self.values.items())
        ]

    def _key_of(self, value: TValue) -> Optional[str]:
        """Get the key of `value`, None if it isn't one of `values`."""
        return next(
            (
                self._value_key(index, candidate)
                for index, candidate in enumerate(self.values.values())
                if candidate == value
            ),
            None,
        )

    def _value_of(self, key: str) -> tuple[bool, Optional[TValue]]:
        """Get whether `key` is the key of one of `values`, and that value.

        A label is accepted too, as older state files saved it.
        """
        for index, candidate in enumerate(self.values.values()):
            if self._value_key(index, candidate) == key:
                return True, candidate
        if key in self.values:
            return True, self.values[key]
        return False, None

    def saved_choice(self) -> Any:
        """Get the choice made as a study saves it: by its keys."""
        raise NotImplementedError

    def load_choice(self, saved: Any) -> None:
        """Make the choice that `saved_choice` saved, among the current `values`."""
        raise NotImplementedError


@define_view
class ValuesGroupMixin(ChoicesMixin[TValue]):
    """The fields of one choice among `values`: the choices by label, and the `value` selected.

    `value` is None, or one of `values`; new `values` without it clear it. None selects
    nothing, unless None is one of `values`, such as a filter's "All": then it selects that
    choice, shown and saved as any other.
    """

    def _check_value(self, _attribute: attrs.Attribute[Any], value: Optional[TValue]) -> None:
        """Reject a `value` that isn't `None` or one of the current `values`."""
        if value is not None and value not in self.values.values():
            if len(self.values) == 0:
                msg = (
                    f"Cannot set {type(self).__name__}.value to {value!r}: `values` is "
                    "empty. Set `values` before setting `value`."
                )
            else:
                msg = (
                    f"Cannot set {type(self).__name__}.value to {value!r}: not one of "
                    f"the available values {list(self.values)}."
                )
            raise ValueError(msg)

    def _reconcile_values(
        self, attribute: attrs.Attribute[Any], values: dict[str, TValue]
    ) -> dict[str, TValue]:
        """Clear `value` if it won't be a member of the new `values`, then notify the renderer."""
        if self.value is not None and self.value not in values.values():
            LOGGER.warning(
                "%s.values no longer contains %r (the current value); clearing it.",
                type(self).__name__,
                self.value,
            )
            self.value = None
        notified: dict[str, TValue] = notify_renderer(cast("View", self), attribute, values)
        return notified

    value: Optional[TValue] = attrs.field(default=None, validator=[_check_value])
    values: dict[str, TValue] = attrs.field(
        factory=dict[str, TValue],
        on_setattr=_reconcile_values,
    )
    value_changed: Signal[Optional[TValue]] = attrs.Factory(Signal[Optional[TValue]])

    choice_field: ClassVar[str] = "value"

    def serialize_value(self) -> Optional[str]:
        """Serialize `value` as its key: its label could be in another language on load.

        None for nothing selected: a None `value` that isn't one of `values`.
        """
        # one of `values`, as its validator keeps it, unless it's None
        return self._key_of(cast("TValue", self.value))

    def deserialize_value(self, key: Optional[str]) -> Optional[TValue]:
        """Look up a key previously produced by `serialize_value` back into a TValue.

        A label is accepted too, as older state files saved it.
        """
        if key is None:
            return None
        is_found, value = self._value_of(key)
        if not is_found:
            LOGGER.warning(
                "Cannot restore %s.value from saved state: %r is not among the current options %r.",
                type(self).__name__,
                key,
                list(self.values),
            )
        return value

    @override
    def saved_choice(self) -> Optional[str]:
        return self.serialize_value()

    @override
    def load_choice(self, saved: Optional[str]) -> None:
        self.value = self.deserialize_value(saved)


@define_view
class RadioGroupView(ValuesGroupMixin[TValue], View):
    """A group of radio buttons, for one choice among a few `values`."""

    _renderer_key = "radio_group"


@define_view
class ComboBoxView(ValuesGroupMixin[TValue], View):
    """A drop-down list, for one choice among `values`."""

    _renderer_key = "combobox"


@attrs.frozen
class ChoicesShown:
    """What a choice of several values shows (`MultiValuesMixin.shown`)."""

    #: the key, the label and whether it's checked, of each choice that the search shows
    options: list[tuple[str, str, bool]]
    #: whether the choices shown are all checked: None while only some of them are, False
    #: without a choice shown
    all_checked: Optional[bool]
    #: what a closed drop-down list shows of the choice; "" for a check list
    summary: str


def _in_values_order(selected: Iterable[TValue], view: ChoicesMixin[TValue]) -> list[TValue]:
    """Get `selected` in the order of the view's `values`, each once: the same choice is no change.

    A value that isn't one of `values` comes last, for the view's validator to reject.
    """
    chosen = list(selected)
    known = list(view.values.values())
    return [
        *(value for value in known if value in chosen),
        *(value for value in chosen if value not in known),
    ]


def _selected_in_order(selected: Iterable[Any], view: AttrsInstance) -> list[Any]:
    """Convert a `MultiValuesMixin`'s `selected` at init: its `values` are set before it."""
    return _in_values_order(selected, cast("ChoicesMixin[Any]", view))


@define_view
class MultiValuesMixin(ChoicesMixin[TValue]):
    """The fields of a choice of several among `values`: the choices by label, and `selected`.

    `selected` holds some of `values`, in their order, each once; new `values` drop those
    no longer among them. With `has_search`, a search field shows only the choices whose
    label holds its text, in any case. The check-all box, with `has_check_all`, checks or
    unchecks the choices shown, and shows partly checked while only some of them are.
    """

    def _check_selected(self, _attribute: attrs.Attribute[Any], selected: list[TValue]) -> None:
        """Reject a `selected` with a value that isn't one of `values`."""
        for value in selected:
            if value not in self.values.values():
                msg = (
                    f"Cannot select {value!r} in {type(self).__name__}: not one of the "
                    f"available values {list(self.values)}."
                )
                raise ValueError(msg)

    def _order_selected(
        self, attribute: attrs.Attribute[Any], selected: list[TValue]
    ) -> list[TValue]:
        """Set `selected` in the order of `values`, as it is at init."""
        ordered = _fixed(
            _in_values_order(selected, self), f"{type(self).__name__}.{attribute.name}"
        )
        return cast("list[TValue]", notify_renderer(cast("View", self), attribute, ordered))

    def _reconcile_values(
        self, attribute: attrs.Attribute[Any], values: dict[str, TValue]
    ) -> dict[str, TValue]:
        """Drop the selected values that the new `values` don't hold, then notify the renderer."""
        kept = [value for value in self.selected if value in values.values()]
        if kept != self.selected:
            self.selected = kept
        return cast("dict[str, TValue]", notify_renderer(cast("View", self), attribute, values))

    values: dict[str, TValue] = attrs.field(factory=dict[str, TValue], on_setattr=_reconcile_values)
    #: the values the user chose, in the order of `values`
    selected: list[TValue] = attrs.field(
        factory=list,
        converter=attrs.Converter(_selected_in_order, takes_self=True),
        validator=[_check_selected],
        on_setattr=[attrs.setters.validate, _order_selected],
    )
    #: whether a search field filters the choices shown
    has_search: bool = attrs.field(default=False, metadata={OMIT: True})
    #: the text of the search field; never saved
    search: str = attrs.field(default="", metadata={OMIT: True})
    #: whether a box checks or unchecks all the choices shown at once
    has_check_all: bool = attrs.field(default=True, metadata={OMIT: True})
    #: the check-all box's text
    check_all_text: str = attrs.field(default=T("All"), metadata={UI_TEXT: True})
    #: the search field's placeholder, as a screen reader names it too
    search_text: str = attrs.field(default=T("Search"), metadata={UI_TEXT: True})
    #: the user changed `selected`, which it holds
    selected_changed: Signal[list[TValue]] = attrs.Factory(Signal[list[TValue]])

    choice_field: ClassVar[str] = "selected"

    @property
    def shown_options(self) -> list[tuple[str, str]]:
        """Get the key and the label of each choice that the search shows, in order."""
        return [(key, label) for key, label, _is_checked in self.shown.options]

    @property
    def selected_keys(self) -> list[str]:
        """Get the keys of `selected`, in order."""
        return [cast("str", self._key_of(value)) for value in self.selected]

    @property
    def shown(self) -> ChoicesShown:
        """Get what the view shows: the choices that the search shows, and what's checked."""
        return self.shown_once("selected", self.selected)

    def shown_once(self, name: str, value: Any) -> ChoicesShown:
        """Get `shown` once the attribute `name` is set to `value`.

        For renderers: they are notified of a change before it lands in the view (see
        `notify_renderer`), so `shown` itself still answers for the old value.
        """
        state = {
            "values": self.values,
            "selected": self.selected,
            "search": self.search,
            name: value,
        }
        values = cast("dict[str, TValue]", state["values"])
        selected = cast("list[TValue]", state["selected"])
        search = cast("str", state["search"]).strip().casefold()
        options = [
            (self._value_key(index, value), label, value in selected)
            for index, (label, value) in enumerate(values.items())
            if search in label.casefold()
        ]
        checked = [is_checked for _key, _label, is_checked in options]
        all_checked = True if len(checked) > 0 and all(checked) else None if any(checked) else False
        return ChoicesShown(options, all_checked, self._summary_once(name, value, selected))

    def _summary_once(self, _name: str, _value: Any, _selected: list[TValue]) -> str:
        """Get what a closed drop-down list shows, once `name` is `value`: none here."""
        return ""

    def select_keys(self, keys: Mapping[str, bool]) -> bool:
        """Check or uncheck each choice by its key, as the user did; get whether it changed.

        A key that isn't one of a choice is left out: a page can send one gone since.
        Doesn't emit `selected_changed`: the renderer that the user changed does.
        """
        chosen = set(self.selected_keys)
        for key, is_checked in keys.items():
            if is_checked:
                chosen.add(key)
            else:
                chosen.discard(key)
        selected = [
            value
            for index, value in enumerate(self.values.values())
            if self._value_key(index, value) in chosen
        ]
        if selected == self.selected:
            return False
        self.selected = selected
        return True

    def check_all(self, *, is_checked: bool) -> bool:
        """Check or uncheck every choice shown, as the check-all box does; get whether it changed.

        The choices that the search hides keep their state.
        """
        return self.select_keys({key: is_checked for key, _label in self.shown_options})

    @override
    def saved_choice(self) -> list[str]:
        return self.selected_keys

    @override
    def load_choice(self, saved: object) -> None:
        if not isinstance(saved, list) or not all(isinstance(key, str) for key in saved):
            msg = f"{type(self).__name__}.selected must be a list of keys, not {saved!r}"
            raise TypeError(msg)  # a damaged study: refused before anything changes
        found = []
        for key in saved:
            is_found, value = self._value_of(key)
            if is_found:
                found.append(cast("TValue", value))
            else:
                LOGGER.warning(
                    "Cannot restore %r in %s.selected from saved state: not among the current "
                    "options %r.",
                    key,
                    type(self).__name__,
                    list(self.values),
                )
        self.selected = found


@define_view
class CheckListView(MultiValuesMixin[TValue], View):
    """A list of check boxes, for a choice of several among `values`, e.g. a filter's."""

    _renderer_key = "check_list"


@define_view
class MultiComboBoxMixin(MultiValuesMixin[TValue]):
    """The fields of a drop-down list of check boxes: what it shows closed (`summary`)."""

    #: shown closed while nothing is chosen
    empty_text: str = attrs.field(default=T("None"), metadata={UI_TEXT: True})
    #: shown closed while several values are chosen, of their `{count}`
    count_text: str = attrs.field(default=T("{count} selected"), metadata={UI_TEXT: True})

    @property
    def summary(self) -> str:
        """Get what the closed list shows of `selected`: their label, or how many they are."""
        return self.shown.summary

    @override
    def _summary_once(self, name: str, value: Any, selected: list[TValue]) -> str:
        texts = {
            "empty_text": self.empty_text,
            "count_text": self.count_text,
            "check_all_text": self.check_all_text,
            "values": self.values,
            name: value,
        }
        values = cast("dict[str, TValue]", texts["values"])
        if len(selected) == 0:
            return cast("str", texts["empty_text"])
        if len(selected) == len(values):
            return cast("str", texts["check_all_text"])
        if len(selected) == 1:
            return next(label for label, value in values.items() if value == selected[0])
        return cast("str", texts["count_text"]).format(count=len(selected))


@define_view
class MultiComboBoxView(MultiComboBoxMixin[TValue], View):
    """A drop-down list of check boxes, for a choice of several among many `values`.

    Closed, it shows its `summary`: the choice's label, `check_all_text` while all are
    chosen, else how many are.
    """

    _renderer_key = "multi_combobox"


#: a node of a `TreeView`, by the keys from its top-level node down to it
TreePath = tuple[str, ...]


def _to_tree_nodes(nodes: Iterable[TreeNode]) -> tuple[TreeNode, ...]:
    return tuple(nodes)


class NodeMark(enum.Enum):
    """A mark of a tree node's state, shown after its label."""

    #: done, e.g. an analysis that ran: a green check
    DONE = enum.auto()
    #: to look at, e.g. an analysis whose results are out of date: an orange "!"
    WARNING = enum.auto()
    #: failed, e.g. an analysis that stopped on an error: a red cross
    ERROR = enum.auto()


@attrs.frozen
class TreeNode:
    """A node of a `TreeView`: its text, and the nodes under it.

    Its `key`, its label unless given, tells it apart from its siblings. The tree knows a
    node by its path (see `TreeView`). So nodes under different parents may share a key,
    e.g. a "Pipes" folder under each building.
    """

    label: str
    children: tuple[TreeNode, ...] = attrs.field(default=(), converter=_to_tree_nodes)
    key: str = attrs.field(default=attrs.Factory(lambda node: node.label, takes_self=True))
    #: an image file's path, before the label (not on Textual); set by the app, not
    #: study data: never saved or loaded, as `ActionView.icon`
    icon: Optional[str] = None
    mark: Optional[NodeMark] = None
    is_bold: bool = False
    is_underlined: bool = False


def _unstructure_tree_node(node: TreeNode) -> dict[str, Any]:
    # by hand: Python 3.9 doesn't resolve the class naming itself in `children`
    return {
        "label": node.label,
        "key": node.key,
        "children": [_unstructure_tree_node(child) for child in node.children],
        "mark": None if node.mark is None else node.mark.name,
        "is_bold": node.is_bold,
        "is_underlined": node.is_underlined,
    }


def _structure_tree_node(data: Mapping[str, Any], _type: type) -> TreeNode:
    children = [_structure_tree_node(child, TreeNode) for child in data.get("children", [])]
    mark = data.get("mark")
    return TreeNode(
        str(data["label"]),
        children,
        str(data.get("key", data["label"])),
        mark=None if mark is None else NodeMark[str(mark)],
        is_bold=bool(data.get("is_bold", False)),
        is_underlined=bool(data.get("is_underlined", False)),
    )


CONVERTER.register_unstructure_hook(TreeNode, _unstructure_tree_node)
CONVERTER.register_structure_hook(TreeNode, _structure_tree_node)


def walk_tree(
    nodes: Iterable[TreeNode], parent: TreePath = ()
) -> Iterator[tuple[TreePath, TreeNode]]:
    """Get each node of `nodes` and under them with its path, depth first, in order."""
    for node in nodes:
        path = (*parent, node.key)
        yield path, node
        yield from walk_tree(node.children, path)


@define_view
class TreeView(View):
    """Nodes in a tree, e.g. a site's buildings, their floors and their rooms.

    A node is known by its path, the keys from its top-level node down to it (see
    `TreeNode`). The user expands and collapses the nodes that have children. `expanded`
    holds the paths of the expanded nodes, and `toggled` emits a node's path and whether
    it is now expanded. The user selects one node: `selected` holds its path, and
    `selection_changed` emits it. Assign new `nodes` to update the tree: they keep the
    paths of `expanded` and `selected` still in them, and drop the others.
    """

    _renderer_key = "tree"

    def _check_nodes(self, _attribute: attrs.Attribute[Any], nodes: list[TreeNode]) -> None:
        paths: set[TreePath] = set()
        for path, _node in walk_tree(nodes):
            if path in paths:
                msg = (
                    f"Cannot set {type(self).__name__}.nodes: two nodes at {list(path)} share"
                    " the key; give them each a key of their own."
                )
                raise ValueError(msg)
            paths.add(path)

    def _check_expanded(self, _attribute: attrs.Attribute[Any], expanded: list[TreePath]) -> None:
        paths = {path for path, _node in walk_tree(self.nodes)}
        for path in expanded:
            if path not in paths:
                msg = (
                    f"Cannot expand the node {list(path)} of {type(self).__name__}: none is there."
                )
                raise ValueError(msg)

    def _check_selected(
        self, _attribute: attrs.Attribute[Any], selected: Optional[TreePath]
    ) -> None:
        if selected is not None and selected not in {path for path, _node in walk_tree(self.nodes)}:
            msg = (
                f"Cannot select the node {list(selected)} of {type(self).__name__}: none is there."
            )
            raise ValueError(msg)

    def _reconcile_nodes(
        self, attribute: attrs.Attribute[Any], nodes: list[TreeNode]
    ) -> list[TreeNode]:
        """Drop the paths of `expanded` and `selected` gone, then notify the renderer.

        Unnotified: the renderer shows them with the nodes.
        """
        paths = {path for path, _node in walk_tree(nodes)}
        set_value(self, "expanded", [path for path in self.expanded if path in paths])
        if self.selected not in paths:
            set_value(self, "selected", None)
        return cast("list[TreeNode]", notify_renderer(self, attribute, nodes))

    nodes: list[TreeNode] = attrs.field(
        factory=list[TreeNode],
        validator=[_check_nodes],
        on_setattr=[attrs.setters.validate, _reconcile_nodes],
    )
    # after `nodes`: loading saved state checks them against the nodes already loaded
    expanded: list[TreePath] = attrs.field(factory=list[TreePath], validator=[_check_expanded])
    selected: Optional[TreePath] = attrs.field(default=None, validator=[_check_selected])
    #: the user expanded (True) or collapsed a node; not emitted when `expanded` is set in code
    toggled: Signal[TreePath, bool] = attrs.Factory(Signal[TreePath, bool])
    #: the user selected a node; not emitted when `selected` is set in code
    selection_changed: Signal[TreePath] = attrs.Factory(Signal[TreePath])
    #: each `NodeMark`'s name, for screen readers (web) and as a tooltip (Qt)
    done_text: str = attrs.field(default=T("Done"), metadata={UI_TEXT: True})
    warning_text: str = attrs.field(default=T("Warning"), metadata={UI_TEXT: True})
    error_text: str = attrs.field(default=T("Error"), metadata={UI_TEXT: True})

    def mark_text(self, mark: NodeMark) -> str:
        """Get the name of `mark` in the main view's language."""
        if mark is NodeMark.DONE:
            return self.done_text
        return self.warning_text if mark is NodeMark.WARNING else self.error_text

    def node(self, path: TreePath) -> TreeNode:
        """Get the node at `path`, e.g. the selected one's label; KeyError if none is there."""
        for node_path, node in walk_tree(self.nodes):
            if node_path == path:
                return node
        raise KeyError(path)

    def expanded_with(self, path: TreePath, *, is_expanded: bool) -> list[TreePath]:
        """Get `expanded` with the node at `path` expanded or collapsed, the others kept."""
        kept = [expanded for expanded in self.expanded if expanded != path]
        return [*kept, path] if is_expanded else kept

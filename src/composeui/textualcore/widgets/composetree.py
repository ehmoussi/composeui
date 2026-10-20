from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Final

from rich.style import Style
from rich.text import Text
from textual.widgets import Tree

from composeui.core.signal import Signal
from composeui.core.view import NodeMark

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from textual.widgets.tree import TreeNode as TextualTreeNode

    from composeui.core.view import TreeNode, TreePath


#: a `NodeMark` after its node's label: its glyph and color, as a log's are colored
MARKS: Final = {
    NodeMark.DONE: ("✓", Style(color="green")),
    NodeMark.WARNING: ("!", Style(color="orange1", bold=True)),
    NodeMark.ERROR: ("✗", Style(color="red")),
}


class ComposeTree(Tree["TreePath"]):
    """A `Tree` of a `TreeView`'s nodes, its root hidden, each node's data its path.

    A node's label is bold or underlined as the node says, its mark after it; a terminal
    shows no icon.

    Enter or a click selects the node under the cursor, its label marked
    (`tree--selected`), as the cursor moves on its own; Space or a click on its arrow
    expands or collapses it. `selected` and `toggled` report the user's moves only:
    `set_nodes`, `set_expanded` and `set_selected` keep quiet, as Qt's renderers block
    their widget's signals while refreshing it.
    """

    COMPONENT_CLASSES: ClassVar[set[str]] = {*Tree.COMPONENT_CLASSES, "tree--selected"}

    DEFAULT_CSS = """
    ComposeTree {
        height: auto;
        max-height: 20;
        & > .tree--selected {
            color: $accent;
            text-style: bold;
        }
    }
    """

    def __init__(self) -> None:
        super().__init__("")
        self.show_root = False
        self.auto_expand = False
        self.selected_path: TreePath | None = None
        self._marks: dict[TreePath, NodeMark] = {}
        self.selected: Signal[TreePath] = Signal()
        self.toggled: Signal[TreePath, bool] = Signal()

    def set_nodes(
        self, nodes: Iterable[TreeNode], expanded: Iterable[TreePath], selected: TreePath | None
    ) -> None:
        self.clear()
        self.selected_path = selected
        self._marks = {}
        is_expanded = set(expanded)

        def add(
            parent: TextualTreeNode[TreePath], nodes: Iterable[TreeNode], path: TreePath
        ) -> None:
            for node in nodes:
                node_path = (*path, node.key)
                if node.mark is not None:
                    self._marks[node_path] = node.mark
                # a `Text`, not markup: the label is the app's data
                label = Text(
                    node.label,
                    Style(bold=node.is_bold or None, underline=node.is_underlined or None),
                )
                if len(node.children) == 0:
                    parent.add_leaf(label, node_path)
                else:
                    item = parent.add(label, node_path, expand=node_path in is_expanded)
                    add(item, node.children, node_path)

        add(self.root, nodes, ())

    def set_expanded(self, expanded: Iterable[TreePath]) -> None:
        is_expanded = set(expanded)
        with self.prevent(Tree.NodeExpanded, Tree.NodeCollapsed):
            for node in self._branch_nodes():
                if node.allow_expand and node.is_expanded != (node.data in is_expanded):
                    node.toggle()

    def set_selected(self, selected: TreePath | None) -> None:
        self.selected_path = selected
        for node in self._branch_nodes():
            node.refresh()  # its label, marked or not
            if node.data == selected:
                self.move_cursor(node)

    def render_label(
        self, node: TextualTreeNode[TreePath], base_style: Style, style: Style
    ) -> Text:
        if node.data is not None and node.data == self.selected_path:
            style += self.get_component_rich_style("tree--selected", partial=True)
        label = super().render_label(node, base_style, style)
        mark = None if node.data is None else self._marks.get(node.data)
        if mark is not None:  # in its own color, the selected label's left out
            glyph, color = MARKS[mark]
            label.append(f" {glyph}", base_style + color)
        return label

    def on_tree_node_selected(self, event: Tree.NodeSelected[TreePath]) -> None:
        path = event.node.data
        if path is None or path == self.selected_path:
            return
        self.set_selected(path)
        self.selected.emit(path)

    def on_tree_node_expanded(self, event: Tree.NodeExpanded[TreePath]) -> None:
        if event.node.data is not None:
            self.toggled.emit(event.node.data, True)  # noqa: FBT003

    def on_tree_node_collapsed(self, event: Tree.NodeCollapsed[TreePath]) -> None:
        if event.node.data is not None:
            self.toggled.emit(event.node.data, False)  # noqa: FBT003

    def _branch_nodes(self) -> Iterator[TextualTreeNode[TreePath]]:
        """Get the nodes under the root, depth first."""
        nodes = list(reversed(self.root.children))
        while len(nodes) > 0:
            node = nodes.pop()
            yield node
            nodes.extend(reversed(node.children))

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from rich.text import Text
from textual.widgets import Tree

from composeui.core.signal import Signal

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from rich.style import Style
    from textual.widgets.tree import TreeNode as TextualTreeNode

    from composeui.core.view import TreeNode, TreePath


class ComposeTree(Tree["TreePath"]):
    """A `Tree` of a `TreeView`'s nodes, its root hidden, each node's data its path.

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
        self.selected: Signal[TreePath] = Signal()
        self.toggled: Signal[TreePath, bool] = Signal()

    def set_nodes(
        self, nodes: Iterable[TreeNode], expanded: Iterable[TreePath], selected: TreePath | None
    ) -> None:
        self.clear()
        self.selected_path = selected
        is_expanded = set(expanded)

        def add(
            parent: TextualTreeNode[TreePath], nodes: Iterable[TreeNode], path: TreePath
        ) -> None:
            for node in nodes:
                node_path = (*path, node.key)
                # a `Text`, not markup: the label is the app's data
                if len(node.children) == 0:
                    parent.add_leaf(Text(node.label), node_path)
                else:
                    item = parent.add(Text(node.label), node_path, expand=node_path in is_expanded)
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
        return super().render_label(node, base_style, style)

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

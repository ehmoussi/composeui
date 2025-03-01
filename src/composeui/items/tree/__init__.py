"""Tree component.

Contains the tree component and its derivatives.

    - TreeView: A tree which needs a class inherited of AbstractTreeItems
"""

from composeui.commontypes import AnyTreeItems
from composeui.items.core import itemsslots
from composeui.items.core.connect import connect_pagination
from composeui.items.core.initialize import initialize_items_view
from composeui.items.tree import tree
from composeui.items.tree.itreeview import ExportTreeOptions, ITreeView

from typing import Any


def initialize_tree_view(view: ITreeView[AnyTreeItems]) -> bool:
    """Initialize the tree view."""
    view.is_expansion_animated = True
    view.export_options = ExportTreeOptions.EXPORT_ALL
    initialize_items_view(view)
    return False


def connect_tree(view: ITreeView[Any]) -> bool:
    """Connect the slots for the tree view."""
    view.shortcut_add = [tree.add_clicked]
    view.shortcut_delete = [tree.remove_clicked]
    view.shortcut_clear = [tree.clear_items]
    view.shortcut_paste = [itemsslots.paste_items]
    view.shortcut_copy = [itemsslots.copy_items]
    view.filter_changed = [itemsslots.update_filter_pattern]
    view.filter_view.filter_changed = [itemsslots.update_filter_pattern]
    view.check_all = [tree.check_all_items]
    view.import_clicked = [tree.import_clicked]
    view.export_clicked = [tree.export_clicked]
    view.add_clicked = [tree.add_clicked]
    view.remove_clicked = [tree.remove_clicked]
    connect_pagination(view=view.pagination_view, parent_view=view)
    return False

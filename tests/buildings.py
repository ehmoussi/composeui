"""A site's buildings, floors and rooms, shared by the backend tests of `TreeView`."""

from __future__ import annotations

from composeui.core.view import MainView, NodeMark, TreeNode, TreeView, child, define_view

SITE = [
    TreeNode(
        "Building A",
        [
            TreeNode("Floor 1", [TreeNode("Room 101"), TreeNode("Room 102")]),
            TreeNode("Floor 2", [TreeNode("Room 201")]),
        ],
    ),
    # a "Floor 1" too, under another parent
    TreeNode("Building B", [TreeNode("Floor 1", [TreeNode("Lobby")])]),
    TreeNode("Parking"),
]


def styled_site(icon: str) -> list[TreeNode]:
    """Get a site whose nodes show an icon, a style and a mark, `icon` the building's."""
    return [
        TreeNode(
            "Building A",
            [
                TreeNode("Room 101", mark=NodeMark.DONE),
                TreeNode("Room 102", mark=NodeMark.ERROR),
            ],
            icon=icon,
            is_bold=True,
        ),
        TreeNode("Parking", is_underlined=True, mark=NodeMark.WARNING),
    ]


@define_view
class SiteMainView(MainView):
    app_title = "Site"
    extension = ".site"

    site: TreeView = child(TreeView, nodes=SITE, expanded=[("Building A",)])

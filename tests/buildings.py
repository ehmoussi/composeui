"""A site's buildings, floors and rooms, shared by the backend tests of `TreeView`."""

from __future__ import annotations

from typing import Optional

import attrs

from composeui.core.view import (
    STRETCH,
    LabelView,
    MainView,
    NodeMark,
    SplitterView,
    TreeNode,
    TreeView,
    VerticalView,
    child,
    define_view,
)

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


def styled_site(icon: Optional[str] = None) -> list[TreeNode]:
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


@define_view
class PlanPane(VerticalView):
    plan: LabelView = child(LabelView, text="Plan")


@define_view
class SiteSplitter(SplitterView):
    site: TreeView = child(
        TreeView,
        # a label longer than the narrowest tree has room for
        nodes=[*styled_site(), TreeNode("Underground car park, level 2", mark=NodeMark.DONE)],
        expanded=[("Building A",)],
    )
    plan: PlanPane = attrs.field(factory=PlanPane, metadata={STRETCH: 2})


@define_view
class SitePlanMainView(MainView):
    """The site's styled and marked tree beside its plan, in a splitter."""

    app_title = "Site plan"
    extension = ".site"

    splitter: SiteSplitter = attrs.Factory(SiteSplitter)

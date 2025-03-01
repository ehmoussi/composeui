r"""Toolbar utilities."""

from composeui.core.views.actionview import ActionView
from composeui.mainview.views.mainview import MainView
from composeui.mainview.views.toolbar import CheckableToolBar

from typing import Iterator, Optional, Tuple


def find_checked_action_from_toolbar(
    view: CheckableToolBar,
) -> Tuple[str, Optional[ActionView]]:
    for name, child_view in view.children.items():
        if isinstance(child_view, ActionView) and child_view.is_checked:
            return name, child_view
    return "", None


def display(*, view: CheckableToolBar, main_view: MainView) -> None:
    r"""Display the view/toolbar associated with the checked action."""
    action_name, action_view = find_checked_action_from_toolbar(view)
    if action_view is not None and len(action_view.visible_views) > 0:
        show_only_view(main_view, action_name)


def show_only_view(main_view: MainView, action_name: str) -> None:
    r"""Show only the views of  the given action name."""
    for name, action_view in iter_toolbar_actions(main_view, action_name):
        is_visible = name == action_name
        for view in action_view.visible_views:
            view.is_visible = is_visible
            if isinstance(view, CheckableToolBar) and is_visible:
                show_checked_action_views(view)


def show_checked_action_views(toolbar: CheckableToolBar) -> None:
    """Show the views of the checked action of the given toolbar."""
    _, checked_action = find_checked_action_from_toolbar(toolbar)
    if checked_action is not None:
        for view in checked_action.visible_views:
            view.is_visible = True


# def show_only_toolbar(main_view: View, name: str):
#     r"""Show only the toolbar with the given name."""
#     main_toolbar = main_view["toolbar"]
#     for toolbar_name in iter_toolbars(main_toolbar):
#         toolbar = main_toolbar[toolbar_name]
#         if not toolbar["is_always_visible"]:
#             if toolbar_name == name:
#                 toolbar["is_visible"] = True
#                 if toolbar["checked_action"] == "":
#                     for action_name in iter_actions(toolbar):
#                         if toolbar[action_name]["has_view"]:
#                             toolbar["checked_action"] = action_name
#                             break
#                 else:
#                     show_only_view(main_view, toolbar["checked_action"])
#             else:
#                 toolbar["is_visible"] = False


def iter_toolbar_actions(
    main_view: MainView, last_action_name: str
) -> Iterator[Tuple[str, ActionView]]:
    r"""Iterate over the list of keys corresponding to an action view."""
    last_action = None
    for toolbar in main_view.toolbar.children.values():
        if isinstance(toolbar, CheckableToolBar):
            for name, action in toolbar.children.items():
                if isinstance(action, ActionView):
                    if name == last_action_name:
                        last_action = action
                        continue
                    yield name, action
    if last_action is None:
        msg = f"Can't find the action '{last_action_name}'"
        raise ValueError(msg)
    yield last_action_name, last_action

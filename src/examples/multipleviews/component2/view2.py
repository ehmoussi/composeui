from composeui.core.views.actionview import ActionView
from composeui.core.views.view import View

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from examples.multipleviews.example import ExampleMainView


@dataclass(eq=False)
class View2(View):
    text_2: str = field(init=False, default="")


@dataclass(eq=False)
class RightView2(View):
    right_text_2: str = field(init=False, default="")


def initialize_component2(
    toolbar_action: ActionView,
    view: View2,
    right_view: RightView2,
    main_view: "ExampleMainView",
) -> None:
    # toolbar action
    toolbar_action.text = "View 2"
    toolbar_action.visible_views = [
        main_view.view_2,
        main_view.right_dock,
        main_view.right_dock.view_2,
    ]
    # central view
    view.is_visible = False
    view.text_2 = "VIEW 2"
    # right view
    right_view.is_visible = False
    right_view.right_text_2 = "RIGHT VIEW 2"

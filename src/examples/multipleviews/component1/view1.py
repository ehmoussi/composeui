from composeui.core.views.iactionview import ActionView
from composeui.core.views.iview import View

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from examples.multipleviews.example import ExampleMainView


@dataclass(eq=False)
class View1(View):
    text_1: str = field(init=False, default="")


@dataclass(eq=False)
class LeftView1(View):
    left_text_1: str = field(init=False, default="")


def initialize_component1(
    toolbar_action: ActionView,
    view: View1,
    left_view: LeftView1,
    main_view: "ExampleMainView",
) -> None:
    # toolbar action
    toolbar_action.text = "View 1"
    toolbar_action.is_checked = True
    toolbar_action.visible_views = [
        main_view.view_1,
        main_view.left_dock,
        main_view.left_dock.view_1,
    ]
    # central view
    view.is_visible = True
    view.text_1 = "VIEW 1"
    # left view
    left_view.is_visible = True
    left_view.left_text_1 = "LEFT VIEW 1"

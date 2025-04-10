from composeui.core.views.actionview import ActionView
from composeui.core.views.view import View

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from examples.multipleviews.example import ExampleMainView


@dataclass(eq=False)
class View3(View):
    text_3: str = field(init=False, default="")


def initialize_component3(
    toolbar_action: ActionView,
    view: View3,
    main_view: "ExampleMainView",
) -> None:
    # toolbar action
    toolbar_action.text = "View 3"
    toolbar_action.visible_views = [main_view.view_3]
    # central view
    view.is_visible = False
    view.text_3 = "VIEW 3"

from composeui.core.interfaces.iactionview import IActionView
from composeui.core.interfaces.iview import IView

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from examples.multipleviews.example import IExampleMainView


@dataclass(eq=False)
class IView3(IView):
    text_3: str = field(init=False, default="")


def initialize_component3(
    toolbar_action: IActionView,
    view: IView3,
    main_view: "IExampleMainView",
) -> None:
    # toolbar action
    toolbar_action.text = "View 3"
    toolbar_action.visible_views = [main_view.view_3]
    # central view
    view.is_visible = False
    view.text_3 = "VIEW 3"

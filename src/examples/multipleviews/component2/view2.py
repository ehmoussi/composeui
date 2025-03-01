from composeui.core.views.iactionview import IActionView
from composeui.core.views.iview import IView

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from examples.multipleviews.example import IExampleMainView


@dataclass(eq=False)
class IView2(IView):
    text_2: str = field(init=False, default="")


@dataclass(eq=False)
class IRightView2(IView):
    right_text_2: str = field(init=False, default="")


def initialize_component2(
    toolbar_action: IActionView,
    view: IView2,
    right_view: IRightView2,
    main_view: "IExampleMainView",
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

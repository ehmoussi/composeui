from composeui.core.views.iactionview import IActionView
from composeui.mainview.interfaces.imaintoolbar import IMainToolBar
from composeui.mainview.interfaces.imainview import IMainView
from composeui.mainview.interfaces.itoolbar import ICheckableToolBar
from examples.formview import pipeapplyform, pipeform

import typing
from dataclasses import dataclass, field

if typing.TYPE_CHECKING:
    from examples.formview.app import Model


@dataclass(eq=False)
class INavigationToolBar(ICheckableToolBar):
    pipe: IActionView = field(init=False, default_factory=IActionView)
    apply_pipe: IActionView = field(init=False, default_factory=IActionView)


@dataclass(eq=False)
class IExampleMainToolBar(IMainToolBar):
    navigation: INavigationToolBar = field(init=False, default_factory=INavigationToolBar)


@dataclass(eq=False)
class IExampleMainView(IMainView):
    toolbar: IExampleMainToolBar = field(init=False, default_factory=IExampleMainToolBar)
    pipe_view: pipeform.IPipeFormView = field(
        init=False, default_factory=pipeform.IPipeFormView
    )
    apply_pipe_view: pipeapplyform.IPipeApplyFormView = field(
        init=False, default_factory=pipeapplyform.IPipeApplyFormView
    )


def initialize_navigation(
    view: INavigationToolBar, main_view: IExampleMainView, model: "Model"
) -> None:
    view.pipe.text = "Pipe"
    view.pipe.is_checked = True
    view.pipe.visible_views = [main_view.pipe_view]
    view.apply_pipe.text = "Apply Pipe"
    view.apply_pipe.visible_views = [main_view.apply_pipe_view]

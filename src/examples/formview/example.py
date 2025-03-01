from composeui.core.views.actionview import ActionView
from composeui.mainview.views.maintoolbar import MainToolBar
from composeui.mainview.views.mainview import MainView
from composeui.mainview.views.toolbar import CheckableToolBar
from examples.formview import pipeapplyform, pipeform

import typing
from dataclasses import dataclass, field

if typing.TYPE_CHECKING:
    from examples.formview.app import Model


@dataclass(eq=False)
class NavigationToolBar(CheckableToolBar):
    pipe: ActionView = field(init=False, default_factory=ActionView)
    apply_pipe: ActionView = field(init=False, default_factory=ActionView)


@dataclass(eq=False)
class ExampleMainToolBar(MainToolBar):
    navigation: NavigationToolBar = field(init=False, default_factory=NavigationToolBar)


@dataclass(eq=False)
class ExampleMainView(MainView):
    toolbar: ExampleMainToolBar = field(init=False, default_factory=ExampleMainToolBar)
    pipe_view: pipeform.PipeFormView = field(init=False, default_factory=pipeform.PipeFormView)
    apply_pipe_view: pipeapplyform.PipeApplyFormView = field(
        init=False, default_factory=pipeapplyform.PipeApplyFormView
    )


def initialize_navigation(
    view: NavigationToolBar, main_view: ExampleMainView, model: "Model"
) -> None:
    view.pipe.text = "Pipe"
    view.pipe.is_checked = True
    view.pipe.visible_views = [main_view.pipe_view]
    view.apply_pipe.text = "Apply Pipe"
    view.apply_pipe.visible_views = [main_view.apply_pipe_view]

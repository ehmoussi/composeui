from dataclasses import dataclass, field, fields
from typing import List

from django.http import HttpRequest
from composeui.core.views.actionview import ActionView
from composeui.items.table.tableview import TableView
from composeui.mainview.views.maintoolbar import MainToolBar
from composeui.mainview.views.mainview import MainView
from composeui.mainview.views.toolbar import CheckableToolBar
from examples.probamodelapp.probamodelapp.model import Model
from examples.probamodelapp.variables.variablesitems import VariablesItems

from django.template.loader import render_to_string


@dataclass(eq=False)
class ProbaModelNavigation(CheckableToolBar):
    definition: ActionView = field(init=False, default_factory=ActionView)

    def get_actions(self) -> List[ActionView]:
        actions = []
        for f in fields(self):
            if f.type is ActionView:
                action = getattr(self, f.name)
                assert isinstance(action, ActionView)
                actions.append(action)
        return actions


@dataclass(eq=False)
class ProbaModelMainToolBar(MainToolBar):
    navigation: ProbaModelNavigation = field(init=False, default_factory=ProbaModelNavigation)


class VariablesTableView(TableView[VariablesItems]):
    def render(self, request: HttpRequest) -> str:
        return render_to_string(
            "probamodelapp/content.html",
            context={"title": "Variables"},
            request=request,
        )


@dataclass(eq=False)
class ProbaModelMainView(MainView):
    title = "ProbaModelApp"
    toolbar: ProbaModelMainToolBar = field(init=False, default_factory=ProbaModelMainToolBar)
    variables: VariablesTableView = field(init=False, default_factory=VariablesTableView)

    def render(self, request: HttpRequest) -> str:
        return render_to_string(
            "mainview/index.html",
            context={
                "title": self.title,
                "navigation_actions": self.toolbar.navigation.get_actions(),
                "content": self.variables.render(request),
            },
            request=request,
        )


def initialize_mainview(main_view: ProbaModelMainView, model: Model) -> None:
    main_view.title = "ProbaModel"
    main_view.toolbar.navigation.definition.text = "Definition"
    main_view.toolbar.navigation.definition.data = "definition"
    main_view.variables.items = VariablesItems(model)

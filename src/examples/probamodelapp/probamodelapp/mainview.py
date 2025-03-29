from dataclasses import dataclass, field

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


@dataclass(eq=False)
class ProbaModelMainToolBar(MainToolBar):
    navigation: ProbaModelNavigation = field(init=False, default_factory=ProbaModelNavigation)


@dataclass(eq=False)
class ProbaModelMainView(MainView):
    title = "ProbaModelApp"
    toolbar: ProbaModelMainToolBar = field(init=False, default_factory=ProbaModelMainToolBar)
    variables: TableView[VariablesItems] = field(init=False, default_factory=TableView)

    def render(self, request: HttpRequest) -> str:
        return render_to_string(
            "probamodelapp/content.html",
            context={"title": "Variables"},
            request=request,
        )


def initialize_mainview(main_view: ProbaModelMainView, model: Model) -> None:
    main_view.title = "ProbaModelApp"
    main_view.toolbar.navigation.definition.text = "Definition"
    main_view.variables.items = VariablesItems(model)

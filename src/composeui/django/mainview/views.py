from dataclasses import fields
from typing import List, Optional
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views import View

from composeui.core.views.actionview import ActionView
from composeui.mainview.views.mainview import MainView


def get_main_view() -> MainView:
    from django.conf import settings

    return getattr(settings, "CUI_MAIN_VIEW", MainView())


def get_navigation_actions(main_view: MainView) -> List[ActionView]:
    return main_view.toolbar.navigation.get_actions()


class MainViewEndpoint(View):
    current_action: Optional[ActionView] = None
    main_view = get_main_view()

    def get(self, request: HttpRequest) -> HttpResponse:
        if self.current_action is not None:
            self.current_action.is_checked = True
        return HttpResponse(self.main_view.render(request))

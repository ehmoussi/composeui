from dataclasses import fields
from typing import List
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from composeui.core.views.actionview import ActionView
from composeui.mainview.views.mainview import MainView


def get_main_view() -> MainView:
    from django.conf import settings

    return getattr(settings, "CUI_MAIN_VIEW", MainView())


def get_navigation_actions(main_view: MainView) -> List[str]:
    actions = []
    for nav_field in fields(main_view.toolbar.navigation):
        if nav_field.type is ActionView:
            nav_action = getattr(main_view.toolbar.navigation, nav_field.name)
            assert isinstance(nav_action, ActionView)
            actions.append(nav_action.text)
    return actions


def index(request: HttpRequest) -> HttpResponse:
    main_view = get_main_view()
    navigation_actions = get_navigation_actions(main_view)
    return render(
        request,
        "mainview/index.html",
        context={
            "title": main_view.title,
            "navigation_actions": navigation_actions,
        },
    )

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from composeui.mainview.views.mainview import MainView


def get_main_view() -> MainView:
    from django.conf import settings

    return getattr(settings, "CUI_MAIN_VIEW", MainView())


def index(request: HttpRequest) -> HttpResponse:
    main_view = get_main_view()
    print(main_view)
    return render(request, "mainview/index.html", context={"title": main_view.title})

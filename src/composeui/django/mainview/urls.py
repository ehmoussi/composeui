from django.urls import path

from composeui.django.mainview.views import MainViewEndpoint, get_main_view

main_view = get_main_view()


urlpatterns = [
    path("", MainViewEndpoint.as_view(current_action=None), name="index"),
    *[
        path(action.data, MainViewEndpoint.as_view(current_action=action))
        for action in main_view.toolbar.navigation.get_actions()
    ],
]

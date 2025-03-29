from django.urls import path

from composeui.django.mainview import views


urlpatterns = [
    path("", views.index, name="index"),
]

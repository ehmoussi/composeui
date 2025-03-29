from django.urls import include, path
from composeui.django.mainview.views import get_main_view
from composeui.django.table import tableitemsendpoint
from examples.probamodelapp.probamodelapp.mainview import ProbaModelMainView

main_view = get_main_view()
assert isinstance(main_view, ProbaModelMainView)
assert main_view.variables.items is not None

urlpatterns = [
    path("/", include(tableitemsendpoint.get_urls(main_view.variables.items))),
]

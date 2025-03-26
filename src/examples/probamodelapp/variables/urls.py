from . import views

from composeui.web.django.table.tableurls import table_urls
from examples.probamodelapp.__main__ import app

urlpatterns = [*table_urls(views.VariablesItems(app.model))]

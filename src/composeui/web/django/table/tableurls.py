from django.urls import path
from composeui.items.core.views.itemsview import FormatExtension
from composeui.items.table.abstracttableitems import AbstractTableItems
from composeui.web.django.table.tableitemsendpoint import (
    FileTableItemsEndpoint,
    TableColumnsEndpoint,
    TableItemsEndPoint,
)

from typing import Any


def table_urls(items: AbstractTableItems[Any]) -> Any:
    return [
        path(
            "api/",
            TableItemsEndPoint.as_view(items=items),
            name="api",
        ),
        path(
            "api/<int:row>",
            TableItemsEndPoint.as_view(items=items),
        ),
        path(
            "api/<int:row>",
            TableItemsEndPoint.as_view(items=items),
        ),
        path(
            "api/columns",
            TableColumnsEndpoint.as_view(items=items),
        ),
        path(
            "csv",
            FileTableItemsEndpoint.as_view(items=items, format_extension=FormatExtension.CSV),
        ),
        path(
            "excel",
            FileTableItemsEndpoint.as_view(
                items=items, format_extension=FormatExtension.EXCEL
            ),
        ),
    ]

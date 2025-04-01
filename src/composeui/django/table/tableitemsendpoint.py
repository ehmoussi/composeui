from composeui.django.api import Status, StatusCode, StatusType, create_response_from_status
from composeui.items.core.itemsutils import ComboBoxDelegateProps, DelegateProps
from composeui.items.core.views.itemsview import FormatExtension
from composeui.items.table.abstracttableitems import AbstractTableItems
from composeui.items.table.exportfiletabletask import ExportFileTableTask

from django.http import FileResponse, HttpRequest, JsonResponse
from django.urls import URLPattern, path
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.generic import View

import io
import json
import tempfile
from pathlib import Path
from typing import Any, ClassVar, Dict, List, Mapping, Optional, Tuple

# # POST -> create resource(s)
# "add": ("/", self.add, ["POST"]),
# "insert": ("/{row:int}", self.insert, ["POST"]),
# # GET -> read resource(s)
# "get_data": ("/", self.get_data, ["GET"]),
# "get_row": ("/{row:int}", self.get_row, ["GET"]),
# # PUT -> update resource(s)
# "set_row": ("/{row:int}", self.set_row, ["PUT"]),
# # DELETE -> delete resource(s)
# "remove_all": ("/", self.remove_all, ["DELETE"]),
# "remove": ("/{row:int}", self.remove, ["DELETE"]),
# # csv
# "export_csv": (
#     "/csv",
#     FileTableEndpoint(
#         self.items, format_extension=FormatExtension.CSV, prefix=self._get_title()
#     ),
#     ["GET"],
# ),
# # excel
# "export_excel": (
#     "/excel",
#     FileTableEndpoint(
#         self.items,
#         format_extension=FormatExtension.EXCEL,
#         prefix=self._get_title(),
#     ),
#     ["GET"],
# ),
# }


def get_urls(items: AbstractTableItems[Any]) -> List[URLPattern]:
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


class TableItemsEndPoint(View):
    items: Optional[AbstractTableItems[Any]] = None

    def __init__(self, items: AbstractTableItems[Any]) -> None:
        super().__init__()
        self._items: AbstractTableItems[Any] = items

    @method_decorator(ensure_csrf_cookie)
    def get(self, _: HttpRequest, row: Optional[int] = None) -> JsonResponse:
        if row is None:
            return self.get_data()
        else:
            return self.get_row(row)

    def post(self, request: HttpRequest, row: Optional[int] = None) -> JsonResponse:
        if row is None:
            return self.add(request)
        else:
            return self.insert(request, row)

    def put(self, request: HttpRequest, row: Optional[int]) -> JsonResponse:
        if row is not None:
            return self.set_row(request, row)
        return create_response_from_status(
            Status(status=StatusType.FAILED, status_code=StatusCode.BAD_REQUEST, message="")
        )

    def delete(self, request: HttpRequest, row: Optional[int] = None) -> JsonResponse:
        if row is None:
            return self.remove_all()
        else:
            return self.remove(row)

    def add(self, request: HttpRequest) -> JsonResponse:
        row, current_row, status = self._insert()
        data = [
            self._items.get_data(row, column) for column in range(self._items.get_nb_columns())
        ]
        if status["status"] != StatusType.FAILED:
            body = request.body
            if len(body) > 0:
                set_row_status = self._set_row(row, body)
                status["message"] = set_row_status["message"]
                if set_row_status["status"] != StatusType.OK:
                    status["status"] = StatusType.PARTIAL
                if set_row_status["status"] != StatusType.FAILED:

                    return create_response_from_status(
                        status,
                        {"current_row": current_row, "data": data},
                    )
        return create_response_from_status(status, {"current_row": row, "data": data})

    def insert(self, request: HttpRequest, row: int) -> JsonResponse:
        """Insert an item"""
        row, current_row, status = self._insert(row)
        if status["status"] != StatusType.FAILED:
            body = request.body
            if len(body) > 0:
                status = self._set_row(row, body)
            data = [
                self._items.get_data(row, column)
                for column in range(self._items.get_nb_columns())
            ]
            return create_response_from_status(
                status,
                {"current_row": current_row, "data": data},
            )
        else:
            return create_response_from_status(status)

    def get_data(self) -> JsonResponse:
        nb_rows = self._items.get_nb_rows()
        return create_response_from_status(
            status=Status(status=StatusType.OK, status_code=StatusCode.OK, message=""),
            content=[
                {
                    "row": row,
                    "data": self._items.get_data_by_row(row),
                }
                for row in range(nb_rows)
            ],
        )

    def get_row(self, row: int) -> JsonResponse:
        nb_rows = self._items.get_nb_rows()
        data = self._get_data_by_row_with_check(row, nb_rows)
        content: Mapping[str, Any]
        if data is not None:
            content = {"data": data}
            status = Status(status=StatusType.OK, status_code=StatusCode.OK, message="")
        else:
            content = {"row": row, "nb_rows": nb_rows}
            status = Status(
                status=StatusType.FAILED,
                status_code=StatusCode.BAD_REQUEST,
                message="The given row is not valid",
            )
        return create_response_from_status(status, content)

    def set_row(self, request: HttpRequest, row: int) -> JsonResponse:
        nb_rows = self._items.get_nb_rows()
        if row < nb_rows:
            body = request.body
            status = self._set_row(row, body)
        else:
            status = Status(
                status=StatusType.FAILED,
                status_code=StatusCode.INTERNAL_SERVER_ERROR,
                message="",
            )
        return create_response_from_status(status)

    def remove(self, row: int) -> JsonResponse:
        nb_rows = self._items.get_nb_rows()
        content: Mapping[str, Any]
        if row >= nb_rows:
            status = Status(
                status=StatusType.FAILED,
                status_code=StatusCode.BAD_REQUEST,
                message="The given row is incorrect",
            )
            content = {"current_row": None}
        else:
            try:
                current_row = self._items.remove(row)
            except Exception:  # noqa: BLE001
                status = Status(
                    status=StatusType.FAILED,
                    status_code=StatusCode.INTERNAL_SERVER_ERROR,
                    message="Unexpected failure",
                )
                content = {"current_row": None}
            else:
                status = Status(
                    status=StatusType.OK,
                    status_code=StatusCode.OK,
                    message="",
                )
                content = {"current_row": current_row}
        return create_response_from_status(status, content)

    def remove_all(self) -> JsonResponse:
        try:
            self._items.remove_all()
        except Exception:  # noqa: BLE001
            status = Status(
                status=StatusType.FAILED,
                status_code=StatusCode.INTERNAL_SERVER_ERROR,
                message="Unexpected failure",
            )
        else:
            status = Status(
                status=StatusType.OK,
                status_code=StatusCode.OK,
                message="",
            )
        return create_response_from_status(status)

    def _insert(self, row: Optional[int] = None) -> Tuple[int, Optional[int], "Status"]:
        nb_rows = self._items.get_nb_rows()
        # the row can't be negative
        if row is None or row > nb_rows:
            row = nb_rows
        try:
            current_row = self._items.insert(row)
        except Exception as e:  # noqa: BLE001
            if self._items.is_debug():
                message = str(e)
            else:
                message = "An unexpected error occurred while processing the insertion."
            return (
                row,
                None,
                Status(
                    status=StatusType.FAILED,
                    status_code=StatusCode.INTERNAL_SERVER_ERROR,
                    message=message,
                ),
            )
        else:
            return (
                row,
                current_row,
                Status(
                    status=StatusType.OK,
                    status_code=StatusCode.OK,
                    message="",
                ),
            )

    def _set_row(self, row: int, body: bytes) -> "Status":
        content_row = None
        if len(body) > 0:
            content_row = json.loads(body)
        values = self._get_valid_row_content(content_row)
        if values is not None:
            failed_columns = []
            for column, value in values.items():
                is_success = self._items.set_data(row, column, value)
                if not is_success:
                    failed_columns.append(column)
            if len(failed_columns) == 0:
                return Status(status=StatusType.OK, status_code=StatusCode.OK, message="")
            else:
                return Status(
                    status=StatusType.PARTIAL,
                    status_code=StatusCode.OK,
                    message=(
                        f"The value of the column(s) {tuple(failed_columns)} are not valid. "
                        "They have not been processed"
                    ),
                )
        return Status(
            status=StatusType.FAILED,
            status_code=StatusCode.BAD_REQUEST,
            message="Bad content",
        )

    def _get_data_by_row_with_check(
        self, row: int, nb_rows: Optional[int] = None
    ) -> Optional[List[str]]:
        if nb_rows is None:
            nb_rows = self._items.get_nb_rows()
        if row >= nb_rows:
            return None
        return self._items.get_data_by_row(row)

    def _get_valid_row_content(self, row_content: Any) -> Optional[Mapping[int, str]]:
        if isinstance(row_content, Mapping):
            nb_columns = self._items.get_nb_columns()
            values = {}
            for column, value in row_content.items():
                column_int = self._items.to_int_value(
                    column, min_value=0, max_value=nb_columns
                )
                if column_int is not None:
                    values[column_int] = value
                else:
                    break
            return values
        return None


class FileTableItemsEndpoint(View):
    items: Optional[AbstractTableItems[Any]] = None
    format_extension: FormatExtension = FormatExtension.CSV

    EXTENSIONS: ClassVar[Dict[FormatExtension, str]] = {
        FormatExtension.CSV: "csv",
        FormatExtension.EXCEL: "xlsx",
    }

    def __init__(
        self, items: AbstractTableItems[Any], format_extension: FormatExtension
    ) -> None:
        self._items = items
        self.format_extension = format_extension
        self.extension = self.EXTENSIONS[self.format_extension]

    def get(self, _: HttpRequest) -> FileResponse:
        with tempfile.NamedTemporaryFile(
            prefix=self._items.get_slug_title(), delete=False
        ) as tmpfile:
            tmpfile.close()
            filepath = Path(tmpfile.name)
            task = ExportFileTableTask(self._items, filepath, extension=self.format_extension)
            task.run()
            with open(filepath, "rb") as f:
                content = io.BytesIO(f.read())
            return FileResponse(
                content,
                as_attachment=True,
                filename=f"{self._items.get_slug_title()}.{self.extension}",
            )


class TableColumnsEndpoint(View):
    items: Optional[AbstractTableItems[Any]] = None

    def __init__(self, items: AbstractTableItems[Any]) -> None:
        self._items = items

    def get(self, _: HttpRequest) -> JsonResponse:
        column_titles = self._items.get_column_titles()
        return create_response_from_status(
            status=Status(status=StatusType.OK, status_code=StatusCode.OK, message=""),
            content={
                "columns": [
                    {
                        "title": column_title,
                        "field": str(index_column),
                        **self._from_delegate_to_tabulator_editor(
                            self._items.get_delegate_props_by_id(index_column)
                        ),
                    }
                    for index_column, column_title in enumerate(column_titles)
                ]
            },
        )

    def _from_delegate_to_tabulator_editor(
        self, delegate: Optional[DelegateProps]
    ) -> Dict[str, Any]:
        if isinstance(delegate, ComboBoxDelegateProps):
            return {"editor": "list", "editorParams": {"values": delegate.values}}
        else:
            return {"editor": "input"}

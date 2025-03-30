# can't use StrEnum for python < 3.11
from django.http import JsonResponse
from typing_extensions import TypedDict

import enum
from typing import Any, Optional


class StatusType(enum.Enum):
    OK = "ok"
    PARTIAL = "partial"
    FAILED = "failed"


class StatusCode(enum.IntEnum):
    OK = 200
    CREATED = 201
    BAD_REQUEST = 400
    UNAUTHORIZED = 401
    INTERNAL_SERVER_ERROR = 500


class Status(TypedDict):
    status: StatusType
    status_code: StatusCode
    message: str


def create_response_from_status(status: Status, content: Optional[Any] = None) -> JsonResponse:
    if content is None:
        content = {}
    return JsonResponse(
        {
            "status": str(status["status"].value),
            "message": status["message"],
            "content": content,
        },
        status=status["status_code"].value,
    )

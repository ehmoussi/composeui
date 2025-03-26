# can't use StrEnum for python < 3.11
from typing_extensions import TypedDict

import enum


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

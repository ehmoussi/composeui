from composeui.web import Status

from django.http import JsonResponse

from typing import Any, Optional


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

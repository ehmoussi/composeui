from composeui.core.basesignal import BaseSignal
from composeui.core.views.view import View

import enum
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple


class HttpMethod(enum.Enum):
    GET = enum.auto()
    POST = enum.auto()
    PUT = enum.auto()
    HEAD = enum.auto()
    DELETE = enum.auto()


@dataclass(eq=False)
class NetworkView(View):
    # input
    url: str = field(init=False, default="")
    method: HttpMethod = field(init=False, default=HttpMethod.GET)
    body: Dict[str, Any] = field(init=False, default_factory=dict)
    # output
    status_code: int = field(init=False, default=0)
    received_data: Optional[Any] = field(init=False, default=None)
    # signals
    reply_finished: BaseSignal = field(init=False, repr=False, default=BaseSignal())

    def run(self) -> None: ...

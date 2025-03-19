from composeui.core.qt.qtview import QtView
from composeui.network.networkmanager import HttpMethod, NetworkManager

from qtpy.QtCore import QUrl
from qtpy.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

import asyncio
import json
from dataclasses import dataclass, field
from typing import (
    Any,
    AsyncGenerator,
    Callable,
    Dict,
    Optional,
)


@dataclass(eq=False)
class QtNetworkManager(QtView, NetworkManager):

    view = None

    _manager: QNetworkAccessManager = field(
        init=False, repr=False, default_factory=QNetworkAccessManager
    )
    _request: QNetworkRequest = field(init=False, repr=False, default_factory=QNetworkRequest)
    _reply: Optional[QNetworkReply] = field(init=False, repr=False, default=None)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.reply_finished.add_qt_signals((self._manager, self._manager.finished))
        self._run_method: Dict[HttpMethod, Callable[[QNetworkRequest], QNetworkReply]] = {
            HttpMethod.GET: self._manager.get,
            HttpMethod.DELETE: self._manager.deleteResource,
            HttpMethod.HEAD: self._manager.head,
        }
        self._run_with_payload: Dict[
            HttpMethod, Callable[[QNetworkRequest, bytes], QNetworkReply]
        ] = {
            HttpMethod.POST: self._manager.post,
            HttpMethod.PUT: self._manager.put,
        }
        self._queue: asyncio.Queue[Any | None] = asyncio.Queue()
        self._lock = asyncio.Lock()

    @property  # type: ignore[misc]
    def url(self) -> str:
        return self._request.url().url()

    @url.setter
    def url(self, url: str) -> None:
        self._request.setUrl(QUrl(url))

    def _run(self) -> None:
        if self.method in self._run_method:
            self._request.setRawHeader(b"accept", b"application/json")
            self._reply = self._run_method[self.method](self._request)
        else:
            self._request.setRawHeader(b"content-type", b"application/json")
            self._reply = self._run_with_payload[self.method](
                self._request, json.dumps(self.body).encode()
            )
        if self._reply is not None:
            self.received_data = None

    def run(self) -> None:
        self._run()
        if self._reply is not None:
            self._reply.readyRead.connect(self._read_reply)

    async def run_async(self) -> None:
        self._run()
        if self._reply is not None:
            self._reply.readyRead.connect(
                lambda: asyncio.ensure_future(self._read_reply_async())
            )
        while True:
            await self._queue.get()
            if self._reply is None:
                break

    async def stream(self) -> AsyncGenerator[Any | None, None]:
        self._run()
        if self._reply is not None:
            self._reply.readyRead.connect(
                lambda: asyncio.ensure_future(self._read_reply_async())
            )
        while True:
            response = await self._queue.get()
            yield response
            await asyncio.sleep(0.1)
            if self._reply is None:
                break

    def _read_reply(self) -> None:
        if self._reply is not None:
            received_bytes = self._reply.readAll().data()
            self.received_data = json.loads(received_bytes)
            self.status_code = self._reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
            if self._reply.isFinished():
                self._reply.deleteLater()
                self._reply = None

    async def _read_reply_async(self) -> None:
        async with self._lock:
            self._read_reply()
            await self._queue.put(self.received_data)

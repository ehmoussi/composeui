from composeui.core.qt.qtview import QtView
from composeui.network.networkmanager import HttpMethod, NetworkManager

from qtpy.QtCore import QUrl
from qtpy.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

import asyncio
from dataclasses import dataclass, field
from typing import AsyncGenerator, Callable, Dict, Optional


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
        self._event = asyncio.Event()

    @property  # type: ignore[misc]
    def url(self) -> str:
        return self._request.url().url()

    @url.setter
    def url(self, url: str) -> None:
        self._request.setUrl(QUrl(url))

    def _run(self) -> None:
        if self.method in self._run_method:
            if len(self.header) == 0:
                self._request.setRawHeader(b"accept", b"application/json")
            else:
                for name, value in self.header.items():
                    self._request.setRawHeader(name, value)
            self._reply = self._run_method[self.method](self._request)
        else:
            if len(self.header) == 0:
                self._request.setRawHeader(b"content-type", b"application/json")
            else:
                for name, value in self.header.items():
                    self._request.setRawHeader(name, value)
            self._reply = self._run_with_payload[self.method](self._request, self.body)
        if self._reply is not None:
            self.response = b""

    def run(self) -> None:
        self._run()
        if self._reply is not None:
            self._reply.readyRead.connect(self._read_reply)

    async def run_async(self) -> None:
        self._run()
        if self._reply is not None:
            self._event.clear()
            self._reply.readyRead.connect(self._event.set)
        while True:
            await self._event.wait()
            self._event.clear()
            self._read_reply()
            if self._reply is None:
                break

    async def stream(self, chunk_size: int) -> AsyncGenerator[bytes, None]:
        self._run()
        if self._reply is not None:
            self._event.clear()
            self._reply.readyRead.connect(self._event.set)
        while True:
            if self._reply is None or (
                self._reply.bytesAvailable() == 0 and self._reply.isFinished()
            ):
                if self._reply is not None:
                    self.status_code = self._reply.attribute(
                        QNetworkRequest.HttpStatusCodeAttribute
                    )
                break
            elif self._reply.bytesAvailable() > 0:
                # Pyside6 `read` returns a QByteArray not bytes but mypy doesn't know that :')
                response = self._reply.read(chunk_size).data()  # type: ignore[attr-defined]
                yield response
            else:
                await self._event.wait()
                self._event.clear()

    def _read_reply(self) -> bytes:
        if self._reply is not None:
            self.response += self._reply.readAll().data()
            if self._reply.isFinished():
                self.status_code = self._reply.attribute(
                    QNetworkRequest.HttpStatusCodeAttribute
                )
                self._reply.deleteLater()
                self._reply = None
        return self.response

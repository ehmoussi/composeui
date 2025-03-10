from composeui.core.qt.qtview import QtView
from composeui.network.networkview import HttpMethod, NetworkView

from qtpy.QtCore import QUrl
from qtpy.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

import json
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional


@dataclass(eq=False)
class QtNetworkView(QtView, NetworkView):

    view = None
    _manager: QNetworkAccessManager = field(
        init=False, repr=False, default_factory=QNetworkAccessManager
    )
    _request: QNetworkRequest = field(init=False, repr=False, default_factory=QNetworkRequest)
    _reply: Optional[QNetworkReply] = field(init=False, repr=False, default=None)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.reply_finished.add_qt_signals((self._manager, self._manager.finished))
        self._run: Dict[HttpMethod, Callable[[QNetworkRequest], QNetworkReply]] = {
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

    @property  # type: ignore[misc]
    def url(self) -> str:
        return self._request.url().url()

    @url.setter
    def url(self, url: str) -> None:
        self._request.setUrl(QUrl(url))

    def run(self) -> None:
        if self.method in self._run:
            self._request.setRawHeader(b"accept", b"application/json")
            self._reply = self._run[self.method](self._request)
        else:
            self._request.setRawHeader(b"content-type", b"application/json")
            self._reply = self._run_with_payload[self.method](
                self._request, json.dumps(self.body).encode()
            )
        if self._reply is not None:
            self.received_data = None
            self._reply.readyRead.connect(self._read_reply)

    def _read_reply(self) -> None:
        if self._reply is not None:
            received_bytes = self._reply.readAll().data()
            try:
                self.received_data = json.loads(received_bytes)
            except Exception:  # noqa: BLE001
                pass
            finally:
                self._reply.deleteLater()
                self._reply = None

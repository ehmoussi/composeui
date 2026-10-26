"""Reproduces the StatusBar cross-thread mutation bug (roadmap item 6).

``StatusBar.show_message`` starts a ``threading.Timer`` whose callback
(``clear_message``) sets ``self.message = ""``. Via ``notify_renderer`` that
assignment calls straight into the Qt renderer, touching a live Qt widget from
the timer's own background thread instead of the GUI thread. Qt objects have
thread affinity; mutating them off-thread is undefined behavior (Qt itself logs
warnings like ``QObject::setParent: Cannot set parent, new parent is in a
different thread`` for this class of bug, and it can crash under real widgets).

This test currently FAILS: it asserts ``clear_message`` runs on the same thread
that rendered the view (the GUI thread), which is not yet true.
"""

from __future__ import annotations

import threading
import time

import pytest

qtpy = pytest.importorskip("qtpy")
from qtpy.QtWidgets import QApplication  # noqa: E402

from composeui.core.view import RendererType, StatusBar  # noqa: E402


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    assert isinstance(app, QApplication)
    return app


def test_clear_message_runs_on_the_gui_thread(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    view = StatusBar()
    view.timeout = 0.05
    view.render(RendererType.QT)

    gui_thread = threading.current_thread()
    clear_message_threads: list[threading.Thread] = []
    original_clear_message = view.clear_message

    def traced_clear_message() -> None:
        clear_message_threads.append(threading.current_thread())
        original_clear_message()

    monkeypatch.setattr(view, "clear_message", traced_clear_message)

    view.show_message("hello")

    deadline = time.monotonic() + 2.0
    while not clear_message_threads and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)

    assert clear_message_threads, "clear_message was never called"
    assert clear_message_threads[0] is gui_thread, (
        f"clear_message ran on {clear_message_threads[0].name!r}, "
        f"not the GUI thread {gui_thread.name!r}"
    )

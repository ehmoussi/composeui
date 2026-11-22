"""Tests of the notification above the page, without a backend: its lifetime and closes."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from composeui.core.view import LogType, MainView, NotificationBar

if TYPE_CHECKING:
    from collections.abc import Callable

    import pytest


class _Timer:
    """A timer that the test fires itself: no clock decides the order."""

    def __init__(self, interval: float, function: Callable[[], object]) -> None:
        self.interval = interval
        self._function = function

    def start(self) -> None:
        pass

    def cancel(self) -> None:
        pass  # a timeout already on its way still comes: `fire` plays it

    def fire(self) -> None:
        self._function()


def test_an_information_goes_after_its_timeout_and_an_error_stays(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timers: list[_Timer] = []

    def make_timer(interval: float, function: Callable[[], object]) -> _Timer:
        timers.append(_Timer(interval, function))
        return timers[-1]

    monkeypatch.setattr(threading, "Timer", make_timer)
    bar = NotificationBar(timeout=5)

    bar.show("Can't save", LogType.ERROR)
    assert timers == []  # nothing to end it but the user or the app
    bar.show("Imported")
    bar.show("Exported")  # its own timeout, from now
    imported, exported = timers
    imported.fire()  # replaced while its timeout was on its way
    assert bar.message == "Exported"
    exported.fire()

    assert (exported.interval, bar.message) == (5, "")


def test_a_close_comes_too_late_once_the_message_shown_is_gone() -> None:
    bar = NotificationBar(timeout=0)
    closes: list[int] = []
    bar.closed.connect(lambda: closes.append(1))
    bar.show("Can't save", LogType.ERROR)
    shown = bar.number
    bar.show("Can't save", LogType.ERROR)  # the same again: still the one the user sees
    bar.dismiss(shown)
    assert (bar.message, closes) == ("", [1])

    bar.show("Can't save", LogType.ERROR)
    shown = bar.number
    bar.show("Can't open", LogType.ERROR)
    bar.dismiss(shown)
    assert (bar.message, closes) == ("Can't open", [1])
    bar.clear()  # the app's, not the user's
    bar.dismiss(bar.number)  # a close of what the app cleared meanwhile

    assert (bar.message, closes) == ("", [1])


def test_new_keeps_the_notification_shown() -> None:
    view = MainView()
    view.notify("Can't open a.study", LogType.ERROR)

    view.reset_state()

    assert view.notification.message == "Can't open a.study"

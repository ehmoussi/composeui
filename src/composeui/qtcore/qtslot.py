"""The slots that connect a widget's Qt signals to the renderers and the view's signals."""

from __future__ import annotations

import functools
import weakref
from typing import TYPE_CHECKING

from qtpy.QtCore import QObject

from composeui.core.signal import _call_reporting, _positional_count

if TYPE_CHECKING:
    from collections.abc import Callable

    from qtpy.QtCore import SignalInstance


class QtSlot(QObject):
    """A slot calling methods, in order, while their objects live, with the arguments they take.

    A Python method of a `QObject`, so PySide connects it as a Qt slot. A connection to any
    other callable goes into a table of PySide that it searches whole each time a sender is
    deleted, or a bound method's object is collected: freeing a page of many widgets took a
    time that grew with the square of their number. A child of the widget that emits, it
    goes with it. It holds each method's object weakly, as PySide holds a bound method's, and
    passes only the first arguments that the method takes, as PySide does.

    One slot takes all the methods of a signal, because each slot takes time to make. A
    method's error goes to `sys.excepthook`, and the next methods still run, as when each
    method was a slot of its own.
    """

    def __init__(self, parent: QObject, methods: tuple[Callable[..., object], ...]) -> None:
        super().__init__(parent)
        self._methods = [
            (weakref.WeakMethod(method), _method_positional_count(method.__func__))  # type: ignore[attr-defined]
            for method in methods
        ]

    def call(self, *args: object) -> None:
        for reference, count in self._methods:
            method = reference()
            if method is not None:
                _call_reporting(method, args[:count])


def connect_slot(signal: SignalInstance, parent: QObject, *methods: Callable[..., object]) -> None:
    """Call the bound `methods`, in order, on each emit of `signal`, while `parent` lives.

    `parent` holds the slot: without it, the slot would be collected, and its connection
    gone.
    """
    signal.connect(QtSlot(parent, methods).call)


@functools.cache
def _method_positional_count(function: Callable[..., object]) -> int | None:
    """Get how many positional arguments the method `function` takes; None for any number.

    Read once per function: a page connects the same methods of each of its widgets.
    """
    count = _positional_count(function)
    return None if count is None else count - 1  # not `self`

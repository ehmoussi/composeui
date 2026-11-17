"""The Qt renderer base and its shared main-thread invoker."""

from __future__ import annotations

import functools
import weakref
from typing import TYPE_CHECKING, Any, ClassVar, TypeVar

from qtpy.QtCore import QObject, Qt
from qtpy.QtCore import Signal as QtSignal
from qtpy.QtWidgets import QDialog, QMainWindow, QWidget
from typing_extensions import TypeVarTuple, Unpack

from composeui.core.renderer import NoRenderedObjectError, Renderer, ViewLike
from composeui.core.view import FormRowView
from composeui.qtcore.qtslot import connect_slot

if TYPE_CHECKING:
    from collections.abc import Callable

    from qtpy.QtCore import SignalInstance
    from qtpy.QtGui import QAction

    from composeui.core.signal import Signal


TView = TypeVar("TView", bound=ViewLike)
TWidget = TypeVar("TWidget", bound="QWidget | QAction")
_Ts = TypeVarTuple("_Ts")


class _MainThreadInvoker(QObject):
    """Bridges a call from any thread onto the thread that owns this `QObject`."""

    _invoke = QtSignal(object, object)

    def __init__(self) -> None:
        super().__init__()
        self._invoke.connect(self._run, Qt.ConnectionType.QueuedConnection)

    def call(self, owner: object, callback: Callable[[], None]) -> None:
        """Call `callback` on this object's thread, unless `owner` is collected by then."""
        self._invoke.emit(weakref.ref(owner), callback)

    @staticmethod
    def _run(owner: weakref.ref[object], callback: Callable[[], None]) -> None:
        # as when each renderer had an invoker of its own, deleted with it
        if owner() is not None:
            callback()


@functools.cache
def _main_thread_invoker() -> _MainThreadInvoker:
    """Get the invoker of the renderers, made on the main thread with the first of them.

    One for all: PySide searches all the connections to Python callables of the process each
    time a sender of one is deleted. The invoker is such a sender, so an invoker per renderer
    made freeing a page take a time that grew with the square of its size.
    """
    return _MainThreadInvoker()


class QtWidgetRenderer(Renderer[TView, TWidget]):
    #: a field renderer's style sheet while its form row is invalid (see
    #: `FormRowView.is_invalid`); None for a widget that is never a row's field
    _invalid_style: ClassVar[str | None] = None

    def __init__(self, view: TView) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "is_visible": self._refresh_visible,
                "is_enabled": self._refresh_enabled,
            }
        )
        if self._invalid_style is not None and isinstance(view, FormRowView):
            # only a row has these: the same renderer also draws a standalone field
            self._refresh_dispatcher.update(
                {
                    name: self._invalid_refresher(name)
                    for name in ("log_message", "log_type", "has_form_error")
                }
            )
        self._main_thread_invoker = _main_thread_invoker()  # made here, on the main thread

    def call_on_main_thread(self, callback: Callable[[], None]) -> None:
        self._main_thread_invoker.call(self, callback)

    def _connect(self, signal: SignalInstance, *methods: Callable[..., object]) -> None:
        """Call `methods`, in order, on each emit of `signal`, a signal of this renderer's widget.

        All the methods of a signal in one call: a slot each would take longer to make.
        """
        assert self._rendered_object is not None  # it holds the slot
        connect_slot(signal, self._rendered_object, *methods)

    def _relay(self, signal: Signal[Unpack[_Ts]], qt_signal: SignalInstance) -> None:
        """Call the callbacks of the view's `signal` on each emit of the widget's `qt_signal`."""
        self._connect(qt_signal, signal.call_callbacks)

    @property
    def qt_object(self) -> TWidget | None:
        return self._rendered_object

    def refresh(self) -> None:
        if self._rendered_object is None:
            raise NoRenderedObjectError
        was_blocked = self._rendered_object.blockSignals(True)  # noqa: FBT003
        try:
            super().refresh()
        finally:
            self._rendered_object.blockSignals(was_blocked)

    def refresh_attribute(self, attr_name: str, value: Any) -> None:
        """Show `value`, the new value of `attr_name`, without the widget emitting signals."""
        if self._rendered_object is None:
            raise NoRenderedObjectError
        was_blocked = self._rendered_object.blockSignals(True)  # noqa: FBT003
        try:
            super().refresh_attribute(attr_name, value)
        finally:
            self._rendered_object.blockSignals(was_blocked)

    @staticmethod
    def _refresh_visible(_view: TView, renderer_object: TWidget, value: bool) -> None:
        # a widget not in a layout yet, e.g. of a page built as it's shown, would show as a
        # window of its own: it shows with the parent it's given
        # one the app shows or hides itself, e.g. a view rendered alone, follows the view
        if (
            value
            and isinstance(renderer_object, QWidget)
            and renderer_object.parentWidget() is None
            and not isinstance(renderer_object, (QMainWindow, QDialog))
            and not renderer_object.testAttribute(Qt.WidgetAttribute.WA_WState_ExplicitShowHide)
        ):
            return
        renderer_object.setVisible(value)

    @staticmethod
    def _refresh_enabled(_view: TView, renderer_object: TWidget, value: bool) -> None:
        renderer_object.setEnabled(value)

    def _invalid_refresher(self, name: str) -> Callable[[TView, TWidget, Any], None]:
        """Restyle the field once the row's attribute `name` changes to the given value."""

        def refresh(view: TView, renderer_object: TWidget, value: Any) -> None:
            is_invalid = isinstance(view, FormRowView) and view.is_invalid_once(name, value)
            assert isinstance(renderer_object, QWidget)  # a field renderer's
            renderer_object.setStyleSheet((self._invalid_style if is_invalid else None) or "")

        return refresh


#: Qt's largest widget size, a widget's maximum when nothing limits it
_QWIDGETSIZE_MAX = 16777215

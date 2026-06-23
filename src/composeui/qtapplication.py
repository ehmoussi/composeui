from __future__ import annotations

import functools
import inspect
import signal
import sys
from typing import TYPE_CHECKING, Generic, Protocol, TypeVar, cast

from qtpy.QtWidgets import QApplication
from typing_extensions import TypeVarTuple, Unpack, overload

from composeui.view import RendererType

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Sequence

    from composeui.signal import Signal
    from composeui.view import MainView, View


# T = TypeVar("T", bound=MainView)
Ts = TypeVarTuple("Ts")

_ViewT_contra = TypeVar("_ViewT_contra", contravariant=True)
_MainViewT_contra = TypeVar("_MainViewT_contra", contravariant=True)
ViewT = TypeVar("ViewT", bound="View")
MainViewT = TypeVar("MainViewT", bound="MainView")


_ViewTD = TypeVar("_ViewTD")
_MainViewTD = TypeVar("_MainViewTD")
_TsD = TypeVarTuple("_TsD")


class _ViewOnlyCallback(Protocol[_ViewT_contra, Unpack[Ts]]):
    def __call__(self, *args: Unpack[Ts], view: _ViewT_contra) -> None: ...


class _ViewMainCallback(Protocol[_ViewT_contra, _MainViewT_contra, Unpack[Ts]]):
    def __call__(
        self, *args: Unpack[Ts], view: _ViewT_contra, main_view: _MainViewT_contra
    ) -> None: ...


class _ConnectDecorator(Protocol[_ViewTD, _MainViewTD, Unpack[_TsD]]):
    @overload
    def __call__(
        self, callback: _ViewOnlyCallback[_ViewTD, Unpack[_TsD]]
    ) -> _ViewOnlyCallback[_ViewTD, Unpack[_TsD]]: ...
    @overload
    def __call__(
        self, callback: _ViewMainCallback[_ViewTD, _MainViewTD, Unpack[_TsD]]
    ) -> _ViewMainCallback[_ViewTD, _MainViewTD, Unpack[_TsD]]: ...


def _accepts_main_view(callback: object) -> bool:
    try:
        return "main_view" in inspect.signature(callback).parameters  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False


class QtApplication(Generic[MainViewT]):
    def __init__(self, main_view: MainViewT) -> None:
        self._main_view = main_view

    @property
    def main_view(self) -> MainViewT:
        return self._main_view

    def connect(
        self, *, view: ViewT, signals: Sequence[Signal[Unpack[Ts]]]
    ) -> _ConnectDecorator[ViewT, MainViewT, Unpack[Ts]]:
        def wrapper(
            callback: _ViewOnlyCallback[ViewT, Unpack[Ts]]
            | _ViewMainCallback[ViewT, MainViewT, Unpack[Ts]],
        ) -> _ViewOnlyCallback[ViewT, Unpack[Ts]] | _ViewMainCallback[ViewT, MainViewT, Unpack[Ts]]:
            raw = cast("Callable[..., None]", callback)
            if _accepts_main_view(callback):
                bound = functools.partial(raw, view=view, main_view=self._main_view)
            else:
                bound = functools.partial(raw, view=view)

            new_callback = cast("Callable[[Unpack[Ts]], None]", bound)
            for s in signals:
                s.connect(new_callback)
            return callback

        return cast("_ConnectDecorator[ViewT, MainViewT, Unpack[Ts]]", wrapper)

    def render(self) -> None:
        self._main_view.is_visible = True
        self._main_view.render(RendererType.QT)

    def run(self) -> Generator[None]:
        app = QApplication(sys.argv)
        self.render()
        signal.signal(signal.SIGINT, signal.SIG_DFL)  # kill the program when Ctr+c
        sys.exit(app.exec())

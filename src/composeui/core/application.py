from __future__ import annotations

import functools
import inspect
from abc import ABC, abstractmethod
from collections import deque
from typing import TYPE_CHECKING, Generic, Protocol, TypeVar, cast

import attrs
from typing_extensions import TypedDict, TypeVarTuple, Unpack, overload, override

from composeui.core.signal import Signal
from composeui.core.view import View

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Sequence

    from composeui.core.model import Model
    from composeui.core.view import MainView, RendererType


# T = TypeVar("T", bound=MainView)
Ts = TypeVarTuple("Ts")

_ViewT_contra = TypeVar("_ViewT_contra", contravariant=True)
_MainViewT_contra = TypeVar("_MainViewT_contra", contravariant=True)
_ModelT_contra = TypeVar("_ModelT_contra", contravariant=True)
ViewT = TypeVar("ViewT", bound="View")
MainViewT = TypeVar("MainViewT", bound="MainView")
ModelT = TypeVar("ModelT", bound="Model")


_ViewTD = TypeVar("_ViewTD")
_MainViewTD = TypeVar("_MainViewTD")
_ModelTD = TypeVar("_ModelTD")
_TsD = TypeVarTuple("_TsD")


class AvailableBounds(TypedDict, Generic[_ViewT_contra, _MainViewT_contra]):
    view: _ViewT_contra
    main_view: _MainViewT_contra


class AvailableModelBounds(TypedDict, Generic[_ViewT_contra, _MainViewT_contra, _ModelT_contra]):
    view: _ViewT_contra
    main_view: _MainViewT_contra
    model: _ModelT_contra


class _ViewOnlyCallback(Protocol[_ViewT_contra, Unpack[Ts]]):
    def __call__(self, *args: Unpack[Ts], view: _ViewT_contra) -> None: ...


class _ViewMainCallback(Protocol[_ViewT_contra, _MainViewT_contra, Unpack[Ts]]):
    def __call__(
        self, *args: Unpack[Ts], view: _ViewT_contra, main_view: _MainViewT_contra
    ) -> None: ...


class _ViewModelCallback(Protocol[_ViewT_contra, _ModelT_contra, Unpack[Ts]]):
    def __call__(self, *args: Unpack[Ts], view: _ViewT_contra, model: _ModelT_contra) -> None: ...


class _ViewMainModelCallback(
    Protocol[_ViewT_contra, _MainViewT_contra, _ModelT_contra, Unpack[Ts]]
):
    def __call__(
        self,
        *args: Unpack[Ts],
        view: _ViewT_contra,
        main_view: _MainViewT_contra,
        model: _ModelT_contra,
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


class _ConnectModelDecorator(Protocol[_ViewTD, _MainViewTD, _ModelTD, Unpack[_TsD]]):
    @overload
    def __call__(
        self, callback: _ViewOnlyCallback[_ViewTD, Unpack[_TsD]]
    ) -> _ViewOnlyCallback[_ViewTD, Unpack[_TsD]]: ...
    @overload
    def __call__(
        self, callback: _ViewMainCallback[_ViewTD, _MainViewTD, Unpack[_TsD]]
    ) -> _ViewMainCallback[_ViewTD, _MainViewTD, Unpack[_TsD]]: ...
    @overload
    def __call__(
        self, callback: _ViewModelCallback[_ViewTD, _ModelTD, Unpack[_TsD]]
    ) -> _ViewModelCallback[_ViewTD, _ModelTD, Unpack[_TsD]]: ...
    @overload
    def __call__(
        self, callback: _ViewMainModelCallback[_ViewTD, _MainViewTD, _ModelTD, Unpack[_TsD]]
    ) -> _ViewMainModelCallback[_ViewTD, _MainViewTD, _ModelTD, Unpack[_TsD]]: ...


def _add_reference_to_signals(main_view: MainView, model: Model | None) -> None:
    views: deque[View] = deque([main_view])
    while len(views) > 0:
        current_view = views.popleft()
        for field_row_attr in attrs.fields(cast("type[attrs.AttrsInstance]", type(current_view))):
            child = getattr(current_view, field_row_attr.name)
            if isinstance(child, View):
                views.append(child)
            elif isinstance(child, Signal):
                child.set_main_view(main_view)
                if model is not None:
                    child.set_model(model)


class Application(ABC, Generic[MainViewT]):
    def __init__(self, *, main_view: MainViewT) -> None:
        self._main_view = main_view
        self._add_reference_to_signals()

    def _add_reference_to_signals(self) -> None:
        _add_reference_to_signals(self._main_view, None)

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
            available_bounds: AvailableBounds[ViewT, MainViewT] = {
                "view": view,
                "main_view": self._main_view,
            }
            requested_bounds = self._requested_kwargs(callback, tuple(available_bounds))
            raw = cast("Callable[..., None]", callback)
            bound = functools.partial(
                raw, **{k: v for k, v in available_bounds.items() if k in requested_bounds}
            )
            new_callback = cast("Callable[[Unpack[Ts]], None]", bound)
            for s in signals:
                s.connect(new_callback)
            return callback

        return cast("_ConnectDecorator[ViewT, MainViewT, Unpack[Ts]]", wrapper)

    def render(self, renderer_type: RendererType) -> None:
        self._main_view.is_visible = True
        self._main_view.render(renderer_type)

    @abstractmethod
    def run(self) -> Generator[None]: ...

    @staticmethod
    def _requested_kwargs(callback: object, names: tuple[str, ...]) -> set[str]:
        try:
            params = inspect.signature(callback).parameters  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return set()
        return {name for name in names if name in params}


class ModelApplication(Application[MainViewT], Generic[MainViewT, ModelT]):
    def __init__(self, *, main_view: MainViewT, model: ModelT) -> None:
        super().__init__(main_view=main_view)
        self._main_view = main_view
        self._model = model

    @override
    def _add_reference_to_signals(self) -> None:
        _add_reference_to_signals(self._main_view, self._model)

    @property
    def model(self) -> ModelT:
        return self._model

    def connect(
        self, *, view: ViewT, signals: Sequence[Signal[Unpack[Ts]]]
    ) -> _ConnectModelDecorator[ViewT, MainViewT, ModelT, Unpack[Ts]]:
        def wrapper(
            callback: _ViewOnlyCallback[ViewT, Unpack[Ts]]
            | _ViewMainCallback[ViewT, MainViewT, Unpack[Ts]],
        ) -> (
            _ViewOnlyCallback[ViewT, Unpack[Ts]]
            | _ViewMainCallback[ViewT, MainViewT, Unpack[Ts]]
            | _ViewMainCallback[ViewT, ModelT, Unpack[Ts]]
            | _ViewMainCallback[ViewT, MainViewT, ModelT, Unpack[Ts]]
        ):
            available_bounds: AvailableModelBounds[ViewT, MainViewT, ModelT] = {
                "view": view,
                "main_view": self._main_view,
                "model": self._model,
            }
            requested_bounds = self._requested_kwargs(callback, tuple(available_bounds))
            raw = cast("Callable[..., None]", callback)
            bound = functools.partial(
                raw, **{k: v for k, v in available_bounds.items() if k in requested_bounds}
            )
            new_callback = cast("Callable[[Unpack[Ts]], None]", bound)
            for s in signals:
                s.connect(new_callback)
            return callback

        return cast("_ConnectModelDecorator[ViewT, MainViewT, ModelT, Unpack[Ts]]", wrapper)

"""The signals, which carry events between the views, the model and the app's code."""

from __future__ import annotations

import functools
import inspect
import logging
import sys
import weakref
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Generic, TypeVar, Union, cast, overload

from typing_extensions import Protocol, TypeAliasType, TypeVarTuple, Unpack

if TYPE_CHECKING:
    from collections.abc import Sequence
    from weakref import ReferenceType

    from qtpy.QtCore import SignalInstance

    from composeui.core.model import Model
    from composeui.core.view import MainView

__all__ = ["Signal"]


LOGGER = logging.getLogger("COMPOSEUI_SIGNAL")
_STREAM_HANDLER = logging.StreamHandler(sys.stdout)
_STREAM_HANDLER.setFormatter(logging.Formatter("%(asctime)s: %(message)s", "%Y-%m-%d %H:%M:%S"))
LOGGER.addHandler(_STREAM_HANDLER)

Ts = TypeVarTuple("Ts")
_Rest = TypeVarTuple("_Rest")
_FirstT = TypeVar("_FirstT")

_MainViewT_contra = TypeVar("_MainViewT_contra", contravariant=True)
_ModelT_contra = TypeVar("_ModelT_contra", contravariant=True)
_MainViewT = TypeVar("_MainViewT", bound="MainView")


class _MainViewCallback(Protocol[_MainViewT_contra, Unpack[Ts]]):
    def __call__(self, *args: Unpack[Ts], main_view: _MainViewT_contra) -> None: ...


class _MainViewOnlyCallback(Protocol[_MainViewT_contra]):
    def __call__(self, *, main_view: _MainViewT_contra) -> None: ...


class _ModelCallback(Protocol[_ModelT_contra, Unpack[Ts]]):
    def __call__(self, *args: Unpack[Ts], model: _ModelT_contra) -> None: ...


class _BoundCallback(Protocol[_MainViewT_contra, _ModelT_contra, Unpack[Ts]]):
    def __call__(
        self, *args: Unpack[Ts], main_view: _MainViewT_contra, model: _ModelT_contra
    ) -> None: ...


# `main_view` and `model` are typed `Any`: a signal can't know its app's classes, and a
# callback asks for those, not `MainView` and `Model` (`connect` still checks a main view)
CallbackT = TypeAliasType(
    "CallbackT",
    (
        Union[
            Callable[[Unpack[Ts]], None],
            _MainViewCallback[Any, Unpack[Ts]],
            _ModelCallback[Any, Unpack[Ts]],
            _BoundCallback[Any, Any, Unpack[Ts]],
        ]
    ),
    type_params=(Ts,),
)


def _positional_count(callback: Callable[..., None]) -> int | None:
    """Get how many positional arguments `callback` takes; None for any number."""
    try:
        params = inspect.signature(callback).parameters.values()
    except (TypeError, ValueError):
        return None
    positional = (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    if any(param.kind is inspect.Parameter.VAR_POSITIONAL for param in params):
        return None
    return sum(
        param.kind in positional and param.name not in ("main_view", "model") for param in params
    )


class Signal(Generic[Unpack[Ts]]):
    """An event that a view, a model or the app emits, with the callbacks connected to it.

    `connect` adds a callback, and `emit` calls each callback with the signal's arguments. A
    callback with a ``main_view`` or ``model`` parameter gets it by name (see `connect`).
    """

    def __init__(self) -> None:
        self._name = ""
        self._qt_signal = _QtSignal()
        self._callbacks: list[Callable[[Unpack[Ts]], None]] = [self._log_signal]
        self._logger = LOGGER
        self._main_view: ReferenceType[MainView] | None = None
        self._model: ReferenceType[Model] | None = None

    def set_name(self, name: str) -> None:
        self._name = name

    def set_main_view(self, main_view: MainView) -> None:
        self._main_view = weakref.ref(main_view)
        for callback in self._callbacks:
            if isinstance(callback, InjectedCallback):
                callback.set_main_view(self._main_view)

    def set_model(self, model: Model) -> None:
        self._model = weakref.ref(model)
        for callback in self._callbacks:
            if isinstance(callback, InjectedCallback):
                callback.set_model(self._model)

    def add_qt_signal(self, signal: SignalInstance) -> None:
        """Call this signal's callbacks when the Qt signal `signal` emits too."""
        self._qt_signal.add_signal(signal, self._callbacks)

    @overload
    def connect(self, callback: Callable[[Unpack[Ts]], None], *, now: bool = False) -> None: ...
    @overload
    def connect(
        self, callback: _MainViewCallback[_MainViewT, Unpack[Ts]], *, now: bool = False
    ) -> None: ...
    @overload
    def connect(self, callback: _ModelCallback[Any, Unpack[Ts]], *, now: bool = False) -> None: ...
    @overload
    def connect(
        self, callback: _BoundCallback[_MainViewT, Any, Unpack[Ts]], *, now: bool = False
    ) -> None: ...
    # a callback taking none of the arguments
    @overload
    def connect(self, callback: Callable[[], None], *, now: bool = False) -> None: ...
    @overload
    def connect(
        self, callback: _MainViewOnlyCallback[_MainViewT], *, now: bool = False
    ) -> None: ...
    @overload
    def connect(self, callback: _ModelCallback[Any], *, now: bool = False) -> None: ...
    @overload
    def connect(self, callback: _BoundCallback[_MainViewT, Any], *, now: bool = False) -> None: ...
    @overload
    def connect(
        self: Signal[_FirstT, Unpack[_Rest]],
        callback: Callable[[_FirstT], None],
        *,
        now: bool = False,
    ) -> None: ...
    def connect(self, callback: Callable[..., None], *, now: bool = False) -> None:
        """Call `callback` on each emit, and once right away too if `now`.

        The callback gets the `main_view` and the `model` it asks for by name. It gets only as
        many of the signal's arguments as it takes, the first ones, and none when called `now`.
        """
        injected_callback = self._inject_callback(callback)
        self._callbacks.append(injected_callback)
        self._qt_signal.connect(injected_callback)
        if now:
            cast("Callable[[], None]", injected_callback)()

    def disconnect(self) -> None:
        self._qt_signal.disconnect(self._callbacks)
        self._callbacks = [self._log_signal]
        self._qt_signal.connect(self._log_signal)

    def emit(self, *args: Unpack[Ts]) -> None:
        for callback in self._callbacks:
            callback(*args)

    def _log_signal(self, *args: Unpack[Ts]) -> None:
        log_msgs = ["EMIT SIGNAL %s"]
        log_args = [self._name]
        nb_callbacks = 0
        for callback in self._callbacks:
            if callback != self._log_signal:
                callback_name = self.get_function_name(callback)
                callback_file = self.get_function_file(callback)
                if len(args) > 0:
                    log_msgs.append("  -> CALL %s(%s)\n          %s")
                else:
                    log_msgs.append("  -> CALL %s()\n          %s")
                log_args.append(callback_name)
                if len(args) > 0:
                    log_args.append(",".join(repr(arg) for arg in args))
                log_args.append(callback_file)
                nb_callbacks += 1
        if nb_callbacks > 0:
            self._logger.debug("\n".join(log_msgs), *log_args)

    def _inject_callback(
        self, callback: Callable[..., None]
    ) -> (
        Callable[[Unpack[Ts]], None]
        | InjectedCallback[Unpack[Ts]]
        | _FirstArgumentsCallback[Unpack[Ts]]
    ):
        requested_bounds = self._requested_bounds(callback)
        if len(requested_bounds) > 0:
            return InjectedCallback[Unpack[Ts]](
                callback=callback,
                requested_bounds=requested_bounds,
                optional_bounds=self._optional_bounds(callback),
                main_view=self._main_view,
                model=self._model,
            )
        count = _positional_count(callback)
        if count is not None:
            return _FirstArgumentsCallback[Unpack[Ts]](callback, count)
        return cast("Callable[[Unpack[Ts]], None]", callback)

    @staticmethod
    def _requested_bounds(callback: Callable[..., None]) -> frozenset[str]:
        names = ("main_view", "model")
        try:
            params = inspect.signature(callback).parameters
        except (TypeError, ValueError):
            return frozenset()
        return frozenset(name for name in names if name in params)

    @staticmethod
    def _optional_bounds(callback: Callable[..., None]) -> frozenset[str]:
        """Get the bounds `callback` has a default for, left out when there is none to give.

        Asked once `_requested_bounds` found some: its signature can be read.
        """
        params = inspect.signature(callback).parameters
        return frozenset(
            name
            for name in ("main_view", "model")
            if name in params and params[name].default is not inspect.Parameter.empty
        )

    @staticmethod
    def get_function_name(callback: CallbackT[Any]) -> str:
        if isinstance(callback, (InjectedCallback, _FirstArgumentsCallback)):
            wrapped = callback.get_callback()
            return "<collected>" if wrapped is None else Signal.get_function_name(wrapped)  # type: ignore[arg-type]
        if isinstance(callback, functools.partial):
            inner = Signal.get_function_name(callback.func)
            args = list(map(repr, callback.args))
            kwargs = [f"{n}={type(arg).__name__}" for n, arg in callback.keywords.items()]
            return f"{inner}({', '.join(args + kwargs)})"
        name = getattr(callback, "__qualname__", None) or getattr(callback, "__name__", None)
        return name or type(callback).__name__

    @staticmethod
    def get_function_file(callback: CallbackT[Any]) -> str:
        if isinstance(callback, (InjectedCallback, _FirstArgumentsCallback)):
            wrapped = callback.get_callback()
            return "" if wrapped is None else Signal.get_function_file(wrapped)  # type: ignore[arg-type]
        if isinstance(callback, functools.partial):
            return Signal.get_function_file(callback.func)
        code = getattr(callback, "__code__", None)
        if code is None:
            # built-ins (e.g. `list.append`) and callable instances have no code object
            return repr(callback)
        return f'File "{code.co_filename}", line {code.co_firstlineno}'


if TYPE_CHECKING:
    SignalNoArgs = Signal[()]
else:
    SignalNoArgs = Signal


class _QtSignal:
    def __init__(self) -> None:
        self._qt_signals: list[SignalInstance] = []

    def add_signal(self, signal: SignalInstance, callbacks: Sequence[Callable[..., None]]) -> None:
        """Add the Qt signal `signal`, and connect `callbacks` to it."""
        self._qt_signals.append(signal)
        for callback in callbacks:
            signal.connect(callback)

    def connect(self, callback: Callable[..., None]) -> None:
        for qt_signal in self._qt_signals:
            qt_signal.connect(callback)

    def disconnect(self, callbacks: Sequence[Callable[..., None]]) -> None:
        for qt_signal in self._qt_signals:
            for callback in callbacks:
                qt_signal.disconnect(callback)


class _FirstArgumentsCallback(Generic[Unpack[Ts]]):
    """A callback taking fewer positional arguments than its signal emits: the first ones."""

    def __init__(self, callback: Callable[..., None], count: int) -> None:
        self._callback = callback
        self._count = count

    def get_callback(self) -> Callable[..., None]:
        return self._callback

    def __call__(self, *args: Unpack[Ts]) -> None:
        self._callback(*args[: self._count])


class InjectedCallback(Generic[Unpack[Ts]]):
    """A callback that gets the ``main_view`` and ``model`` it asks for by name."""

    def __init__(
        self,
        *,
        callback: Callable[..., None],
        requested_bounds: frozenset[str],
        optional_bounds: frozenset[str] = frozenset(),
        main_view: ReferenceType[MainView] | None,
        model: ReferenceType[Model] | None,
    ) -> None:
        # a view's own method stays weak, so its signals don't keep the view alive; a function
        # or a partial (e.g. `Application.connect`'s) has no owner that would hold it
        self._callback: Callable[[], Callable[..., None] | None]
        if inspect.ismethod(callback):
            self._callback = cast("Callable[[], Any]", weakref.WeakMethod(callback))
        else:
            self._callback = lambda: callback
        self._requested_bounds = requested_bounds
        self._optional_bounds = optional_bounds
        self._main_view = main_view
        self._model = model
        #: how many of the signal's arguments the callback takes, the first ones; None for all
        self._count = _positional_count(callback)

    def set_main_view(self, main_view: ReferenceType[MainView]) -> None:
        self._main_view = main_view

    def set_model(self, model: ReferenceType[Model]) -> None:
        self._model = model

    def get_callback(self) -> Callable[..., None] | None:
        """Get the callback; None once it's a method of a view collected since."""
        return self._callback()

    def __call__(self, *args: Unpack[Ts]) -> None:
        callback = self._callback()
        if callback is None:
            return None  # its view is gone: as Qt, which drops a deleted receiver's slot
        kwargs: dict[str, MainView | Model] = {}
        if "main_view" in self._requested_bounds:
            main_view = None if self._main_view is None else self._main_view()
            if main_view is None:
                msg = "The main view is missing."
                raise ValueError(msg)
            kwargs["main_view"] = main_view
        if "model" in self._requested_bounds:
            model = None if self._model is None else self._model()
            if model is not None:
                kwargs["model"] = model
            elif "model" not in self._optional_bounds:
                msg = "The model is missing."
                raise ValueError(msg)
        return callback(*args[: self._count], **kwargs)

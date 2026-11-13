"""The signals, which carry events between the views, the model and the app's code."""

from __future__ import annotations

import functools
import inspect
import logging
import sys
import threading
import weakref
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Generic, TypeVar, Union, cast, overload

from typing_extensions import Protocol, TypeAliasType, TypeVarTuple, Unpack

from composeui.core import reactivity

if TYPE_CHECKING:
    from weakref import ReferenceType

    from composeui.core.model import Model
    from composeui.core.view import MainView, View

__all__ = ["Signal"]


LOGGER = logging.getLogger("COMPOSEUI_SIGNAL")
#: held as callbacks are registered or their owning view changes: registration must keep
#: the current owner, and two first connects must not each replace the empty tuple
_CONNECTING = threading.Lock()
_STREAM_HANDLER = logging.StreamHandler(sys.stdout)
_STREAM_HANDLER.setFormatter(logging.Formatter("%(asctime)s: %(message)s", "%Y-%m-%d %H:%M:%S"))
LOGGER.addHandler(_STREAM_HANDLER)

Ts = TypeVarTuple("Ts")
_Selected = TypeVarTuple("_Selected")
_Rest = TypeVarTuple("_Rest")
_FirstT = TypeVar("_FirstT")
_SecondT = TypeVar("_SecondT")

_MainViewT_contra = TypeVar("_MainViewT_contra", contravariant=True)
_ModelT_contra = TypeVar("_ModelT_contra", contravariant=True)
_ViewT_contra = TypeVar("_ViewT_contra", contravariant=True)
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


# Injected arguments are typed `Any`: a signal can't know its owner's or app's classes.
# A callback asks for those, not `View`, `MainView` and `Model`.
CallbackT = TypeAliasType(
    "CallbackT",
    (
        Union[
            Callable[[Unpack[Ts]], None],
            _MainViewCallback[Any, Unpack[Ts]],
            _ModelCallback[Any, Unpack[Ts]],
            _BoundCallback[Any, Any, Unpack[Ts]],
            _ViewOnlyCallback[Any, Unpack[Ts]],
            _ViewMainCallback[Any, Any, Unpack[Ts]],
            _ViewModelCallback[Any, Any, Unpack[Ts]],
            _ViewMainModelCallback[Any, Any, Any, Unpack[Ts]],
        ]
    ),
    type_params=(Ts,),
)


def _positional_count(callback: Callable[..., object]) -> int | None:
    """Get how many positional arguments `callback` takes; None for any number."""
    try:
        params = inspect.signature(callback).parameters.values()
    except (TypeError, ValueError):
        return None
    positional = (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    if any(param.kind is inspect.Parameter.VAR_POSITIONAL for param in params):
        return None
    return sum(
        param.kind in positional and param.name not in ("view", "main_view", "model")
        for param in params
    )


def _optional_bounds(callback: Callable[..., None]) -> frozenset[str]:
    """Get the bounds `callback` has a default for, left out when there is none to give.

    Asked once `_requested_bounds` found some: its signature can be read.
    """
    params = inspect.signature(callback).parameters
    return frozenset(
        name
        for name in ("view", "main_view", "model")
        if name in params and params[name].default is not inspect.Parameter.empty
    )


class Signal(Generic[Unpack[Ts]]):
    """An event that a view, a model or the app emits, with the callbacks connected to it.

    `connect` adds a callback, and `emit` calls each callback with the signal's arguments. A
    callback with a ``view``, ``main_view`` or ``model`` parameter gets it by name (see `connect`).
    """

    # a page makes several signals per widget, and a web session a page: slots keep each
    # small, and keep `Signal[int]()` from giving it a dict for `__orig_class__`
    __slots__ = ("__weakref__", "_callbacks", "_main_view", "_model", "_name", "_view")

    def __init__(self) -> None:
        self._name = ""
        # most signals stay unconnected: they share the empty tuple until `connect`
        self._callbacks: list[Callable[[Unpack[Ts]], None]] | tuple[()] = ()
        self._main_view: ReferenceType[MainView] | None = None
        self._model: ReferenceType[Model] | None = None
        self._view: ReferenceType[View] | None = None

    def set_name(self, name: str) -> None:
        self._name = name

    def set_view(self, view: View) -> None:
        with _CONNECTING:
            self._view = weakref.ref(view)
            for callback in self._callbacks:
                if isinstance(callback, InjectedCallback):
                    callback.set_view(self._view)

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

    @overload
    def connect(
        self,
        callback: Callable[[Unpack[_Selected]], None],
        *,
        arguments: Callable[[Unpack[Ts]], tuple[Unpack[_Selected]]],
        now: bool = False,
    ) -> None: ...
    @overload
    def connect(
        self,
        callback: _MainViewCallback[Any, Unpack[_Selected]],
        *,
        arguments: Callable[[Unpack[Ts]], tuple[Unpack[_Selected]]],
        now: bool = False,
    ) -> None: ...
    @overload
    def connect(
        self,
        callback: _ModelCallback[Any, Unpack[_Selected]],
        *,
        arguments: Callable[[Unpack[Ts]], tuple[Unpack[_Selected]]],
        now: bool = False,
    ) -> None: ...
    @overload
    def connect(
        self,
        callback: _BoundCallback[Any, Any, Unpack[_Selected]],
        *,
        arguments: Callable[[Unpack[Ts]], tuple[Unpack[_Selected]]],
        now: bool = False,
    ) -> None: ...
    @overload
    def connect(
        self,
        callback: _ViewOnlyCallback[Any, Unpack[_Selected]],
        *,
        arguments: Callable[[Unpack[Ts]], tuple[Unpack[_Selected]]],
        now: bool = False,
    ) -> None: ...
    @overload
    def connect(
        self,
        callback: _ViewMainCallback[Any, Any, Unpack[_Selected]],
        *,
        arguments: Callable[[Unpack[Ts]], tuple[Unpack[_Selected]]],
        now: bool = False,
    ) -> None: ...
    @overload
    def connect(
        self,
        callback: _ViewModelCallback[Any, Any, Unpack[_Selected]],
        *,
        arguments: Callable[[Unpack[Ts]], tuple[Unpack[_Selected]]],
        now: bool = False,
    ) -> None: ...
    @overload
    def connect(
        self,
        callback: _ViewMainModelCallback[Any, Any, Any, Unpack[_Selected]],
        *,
        arguments: Callable[[Unpack[Ts]], tuple[Unpack[_Selected]]],
        now: bool = False,
    ) -> None: ...
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
    @overload
    def connect(
        self, callback: _ViewOnlyCallback[Any, Unpack[Ts]], *, now: bool = False
    ) -> None: ...
    @overload
    def connect(
        self, callback: _ViewMainCallback[Any, _MainViewT, Unpack[Ts]], *, now: bool = False
    ) -> None: ...
    @overload
    def connect(
        self, callback: _ViewModelCallback[Any, Any, Unpack[Ts]], *, now: bool = False
    ) -> None: ...
    @overload
    def connect(
        self,
        callback: _ViewMainModelCallback[Any, _MainViewT, Any, Unpack[Ts]],
        *,
        now: bool = False,
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
    def connect(self, callback: _ViewOnlyCallback[Any], *, now: bool = False) -> None: ...
    @overload
    def connect(
        self, callback: _ViewMainCallback[Any, _MainViewT], *, now: bool = False
    ) -> None: ...
    @overload
    def connect(self, callback: _ViewModelCallback[Any, Any], *, now: bool = False) -> None: ...
    @overload
    def connect(
        self, callback: _ViewMainModelCallback[Any, _MainViewT, Any], *, now: bool = False
    ) -> None: ...
    @overload
    def connect(
        self: Signal[_FirstT, Unpack[_Rest]],
        callback: Callable[[_FirstT], None],
        *,
        now: bool = False,
    ) -> None: ...
    @overload
    def connect(
        self: Signal[_FirstT, Unpack[_Rest]],
        callback: _ViewOnlyCallback[Any, _FirstT],
        *,
        now: bool = False,
    ) -> None: ...
    @overload
    def connect(
        self: Signal[_FirstT, Unpack[_Rest]],
        callback: _ViewMainCallback[Any, _MainViewT, _FirstT],
        *,
        now: bool = False,
    ) -> None: ...
    @overload
    def connect(
        self: Signal[_FirstT, Unpack[_Rest]],
        callback: _ViewModelCallback[Any, Any, _FirstT],
        *,
        now: bool = False,
    ) -> None: ...
    @overload
    def connect(
        self: Signal[_FirstT, Unpack[_Rest]],
        callback: _ViewMainModelCallback[Any, _MainViewT, Any, _FirstT],
        *,
        now: bool = False,
    ) -> None: ...
    @overload
    def connect(
        self: Signal[_FirstT, _SecondT, Unpack[_Rest]],
        callback: _ViewOnlyCallback[Any, _FirstT, _SecondT],
        *,
        now: bool = False,
    ) -> None: ...
    @overload
    def connect(
        self: Signal[_FirstT, _SecondT, Unpack[_Rest]],
        callback: _ViewMainCallback[Any, _MainViewT, _FirstT, _SecondT],
        *,
        now: bool = False,
    ) -> None: ...
    @overload
    def connect(
        self: Signal[_FirstT, _SecondT, Unpack[_Rest]],
        callback: _ViewModelCallback[Any, Any, _FirstT, _SecondT],
        *,
        now: bool = False,
    ) -> None: ...
    @overload
    def connect(
        self: Signal[_FirstT, _SecondT, Unpack[_Rest]],
        callback: _ViewMainModelCallback[Any, _MainViewT, Any, _FirstT, _SecondT],
        *,
        now: bool = False,
    ) -> None: ...
    def connect(
        self,
        callback: Callable[..., None],
        *,
        arguments: Callable[[Unpack[Ts]], tuple[Any, ...]] | None = None,
        now: bool = False,
    ) -> None:
        """Call `callback` on each emit, and once right away too if `now`.

        The callback gets the owning `view`, `main_view` and `model` it asks for by name.
        It gets only as many of the signal's arguments as it takes, the first ones, and none
        when called `now`. A signal outside a view has no owning view. A missing view uses
        the callback's default, or raises `ValueError` if the parameter has no default.

        With `arguments`, call that function with every emitted argument and pass its
        tuple to the callback instead. This makes an arbitrary-length prefix explicit
        to type checkers. The immediate call from `now` does not call `arguments`.
        """
        injected_callback = self._inject_callback(callback, arguments=arguments)
        with _CONNECTING:
            if isinstance(injected_callback, InjectedCallback):
                injected_callback.set_view(self._view)
            if isinstance(self._callbacks, tuple):
                self._callbacks = []
            self._callbacks.append(injected_callback)
        if now:
            if isinstance(injected_callback, InjectedCallback):
                injected_callback.call_now()
            else:
                cast("Callable[[], None]", injected_callback)()

    def disconnect(self) -> None:
        self._callbacks = ()

    def call_callbacks(self, *args: Unpack[Ts]) -> None:
        """Call the callbacks, for a backend that connects a toolkit's signal to this method.

        Each callback runs, even after another one raised: its error goes to
        `sys.excepthook`, as a Qt slot's does. An app emits a signal with `emit`.
        """
        if LOGGER.isEnabledFor(logging.DEBUG):
            _call_reporting(self._log_signal, args)
        # the callbacks connected now, as Qt calls the slots connected when it emits
        for callback in tuple(self._callbacks):
            _call_reporting(callback, args)

    def emit(self, *args: Unpack[Ts]) -> None:
        if not reactivity.is_enabled():
            self._call_logged(args)
            return
        # the reactive methods run once all callbacks are done, without their reads, nor the
        # log's `repr` of the arguments
        with reactivity.batch(), reactivity.untracked():
            self._call_logged(args)

    def _call_logged(self, args: tuple[Unpack[Ts]]) -> None:
        if LOGGER.isEnabledFor(logging.DEBUG):
            self._log_signal(*args)
        for callback in self._callbacks:
            callback(*args)

    def _log_signal(self, *args: Unpack[Ts]) -> None:
        if not self._callbacks:
            return
        log_msgs = ["EMIT SIGNAL %s"]
        log_args = [self._name]
        arguments = ",".join(repr(arg) for arg in args)
        for callback in self._callbacks:
            log_msgs.append("  -> CALL %s(%s)\n          %s")
            log_args.extend(
                (self.get_function_name(callback), arguments, self.get_function_file(callback))
            )
        LOGGER.debug("\n".join(log_msgs), *log_args)

    def _inject_callback(
        self,
        callback: Callable[..., None],
        *,
        arguments: Callable[[Unpack[Ts]], tuple[Any, ...]] | None = None,
    ) -> (
        Callable[[Unpack[Ts]], None]
        | InjectedCallback[Unpack[Ts]]
        | _FirstArgumentsCallback[Unpack[Ts]]
    ):
        requested_bounds = self._requested_bounds(callback)
        if len(requested_bounds) > 0 or arguments is not None:
            return InjectedCallback[Unpack[Ts]](
                callback=callback,
                requested_bounds=requested_bounds,
                view=self._view,
                main_view=self._main_view,
                model=self._model,
                arguments=arguments,
            )
        count = _positional_count(callback)
        if count is not None:
            return _FirstArgumentsCallback[Unpack[Ts]](callback, count)
        return cast("Callable[[Unpack[Ts]], None]", callback)

    @staticmethod
    def _requested_bounds(callback: Callable[..., None]) -> frozenset[str]:
        names: tuple[str, ...] = ("view", "main_view", "model")
        if isinstance(callback, functools.partial) and "view" in callback.keywords:
            # `Application.connect(view=...)` explicitly picks a view, not always the owner.
            names = ("main_view", "model")
        try:
            params = inspect.signature(callback).parameters
        except (TypeError, ValueError):
            return frozenset()
        return frozenset(name for name in names if name in params)

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


def _call_reporting(callback: Callable[..., object], args: tuple[object, ...]) -> None:
    """Call `callback`, and report its error as PySide reports a slot's, without raising it.

    So the next callbacks still run, as the next slots did.
    """
    try:
        callback(*args)
    except Exception:  # noqa: BLE001 - reported through the hook, as by PySide
        sys.excepthook(*sys.exc_info())


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
    """A callback that gets the ``view``, ``main_view`` and ``model`` it asks for by name."""

    def __init__(  # noqa: PLR0913 - callback options and the signal's three weak contexts
        self,
        *,
        callback: Callable[..., None],
        requested_bounds: frozenset[str],
        view: ReferenceType[View] | None,
        main_view: ReferenceType[MainView] | None,
        model: ReferenceType[Model] | None,
        arguments: Callable[[Unpack[Ts]], tuple[Any, ...]] | None,
    ) -> None:
        # a view's own method stays weak, so its signals don't keep the view alive; a function
        # or a partial (e.g. `Application.connect`'s) has no owner that would hold it
        self._callback: Callable[[], Callable[..., None] | None]
        if inspect.ismethod(callback):
            self._callback = cast("Callable[[], Any]", weakref.WeakMethod(callback))
        else:
            self._callback = lambda: callback
        self._requested_bounds = requested_bounds
        self._optional_bounds = _optional_bounds(callback)
        self._main_view = main_view
        self._model = model
        self._view = view
        self._arguments: Callable[[], Callable[[Unpack[Ts]], tuple[Any, ...]] | None] | None
        if arguments is None:
            self._arguments = None
        elif inspect.ismethod(arguments):
            self._arguments = cast(
                "Callable[[], Callable[[Unpack[Ts]], tuple[Any, ...]] | None]",
                weakref.WeakMethod(arguments),
            )
        else:
            self._arguments = lambda: arguments
        #: how many of the signal's arguments the callback takes, the first ones; None for all
        self._count = _positional_count(callback)

    def set_main_view(self, main_view: ReferenceType[MainView]) -> None:
        self._main_view = main_view

    def set_view(self, view: ReferenceType[View] | None) -> None:
        self._view = view

    def set_model(self, model: ReferenceType[Model]) -> None:
        self._model = model

    def get_callback(self) -> Callable[..., None] | None:
        """Get the callback; None once it's a method of a view collected since."""
        return self._callback()

    def __call__(self, *args: Unpack[Ts]) -> None:
        self._invoke(args, project=True)

    def call_now(self) -> None:
        """Call without emitted values or an argument projection."""
        self._invoke((), project=False)

    def _invoke(self, args: tuple[Any, ...], *, project: bool) -> None:
        callback = self._callback()
        if callback is None:
            return None  # its view is gone: as Qt, which drops a deleted receiver's slot
        arguments: Callable[[Unpack[Ts]], tuple[Any, ...]] | None = None
        if project and self._arguments is not None:
            arguments = self._arguments()
            if arguments is None:
                return None  # the view whose method selected the arguments is gone
        kwargs = self._injected_kwargs()
        values = args if arguments is None else arguments(*args)
        return callback(*values[: self._count], **kwargs)

    def _injected_kwargs(self) -> dict[str, View | Model]:
        kwargs: dict[str, View | Model] = {}
        if "view" in self._requested_bounds:
            view = None if self._view is None else self._view()
            if view is not None:
                kwargs["view"] = view
            elif "view" not in self._optional_bounds:
                msg = "The view is missing."
                raise ValueError(msg)
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
        return kwargs

r"""Signal of a View."""

import asyncio
import enum
import functools
import logging
import sys
import typing

if typing.TYPE_CHECKING:
    from composeui.model.basemodel import BaseModel
    from composeui.form.formview import FormView
    from composeui.core.views.view import View

from typing_extensions import ParamSpec, TypeAlias

import inspect
from functools import partial
from typing import (
    Any,
    Callable,
    Iterable,
    List,
    MutableMapping,
    MutableSequence,
    Optional,
    Sequence,
    Set,
    Tuple,
    Type,
    Union,
    overload,
)
from weakref import ReferenceType, WeakKeyDictionary

CallbackFunc: TypeAlias = Callable[..., Any]
Callback: TypeAlias = Union[CallbackFunc, List[CallbackFunc]]
if sys.version_info >= (3, 9):
    TaskCallBackFunc: TypeAlias = asyncio.Task[CallbackFunc]
else:
    TaskCallBackFunc: TypeAlias = asyncio.Task

P = ParamSpec("P")

if typing.TYPE_CHECKING:
    from qtpy.QtCore import QObject, SignalInstance  # type: ignore[attr-defined]
    from composeui.apps.eventdrivenappmixin import EventDrivenAppMixin


SIGNAL_LOGGER = logging.getLogger("SIGNAL")
_stream_handler = logging.StreamHandler()
_stream_handler.setFormatter(
    logging.Formatter(
        "%(asctime)s: %(message)s",
        "%Y-%m-%d %H:%M:%S",
    )
)
SIGNAL_LOGGER.addHandler(_stream_handler)


def _call_callback_functions(
    callback: Iterable[CallbackFunc], *args: Any, **kwargs: Any
) -> None:
    r"""Call the functions of a callback."""
    for f in callback:
        status = f(*args, **kwargs)
        if status is not None and not status:
            break


def _extend_callback_parameters(
    callback: Callable[..., Any], missing_parameters_indices: List[int]
) -> Callable[..., Any]:
    """Extend the given callback by adding the missing parameters.

    The missing parameters indices correspond to the indices of the missing positional
    arguments of the given callback.

    It is used to mimic the behavior of PyQt5 which doesn't crash if the parameters of the
    signal are not provided.
    """

    @functools.wraps(callback)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        filtered_args = [
            arg for i, arg in enumerate(args) if i not in missing_parameters_indices
        ]
        return callback(*filtered_args, **kwargs)

    return wrapper


class _BaseQtSignal:
    def __init__(
        self,
        signal: "SignalInstance",
        obj: Optional["QObject"] = None,
        slots: Sequence[CallbackFunc] = (),
    ) -> None:
        self._signal = signal
        if obj is not None:
            self.parameter_types = self._find_parameter_types(obj, signal)
        else:
            self.parameter_types = []
        self._slots: MutableMapping[CallbackFunc, CallbackFunc] = WeakKeyDictionary()
        self.connect(*slots)

    def connect(self, *callback_functions: CallbackFunc) -> None:
        for callback_function in callback_functions:
            self._connect(callback_function)

    def disconnect(self, *callback_functions: CallbackFunc) -> None:
        for callback_function in callback_functions:
            self._disconnect(callback_function)

    def _connect(self, callback_function: CallbackFunc) -> None:
        slot_function = self._create_slot_function(callback_function)
        self._signal.connect(slot_function)
        self._slots[callback_function] = slot_function

    def _disconnect(self, callback_function: CallbackFunc) -> None:
        self._signal.disconnect(self._slots[callback_function])
        del self._slots[callback_function]

    def _create_slot_function(self, callback_function: CallbackFunc) -> CallbackFunc:
        """Adapt the callback to the parameter types of the qt signal."""
        if len(self.parameter_types) == 0:
            return callback_function
        else:
            missing_parameters_indices = []
            if (
                isinstance(callback_function, partial)
                and callback_function.func.__name__ == "_call_callback_functions"
            ):
                sub_callback_functions = callback_function.args[0]
                for sub_callback_function in sub_callback_functions:
                    if isinstance(sub_callback_function, partial):
                        if (
                            # _signal_log can accept any arguments
                            "_signal_log" in repr(sub_callback_function.func)
                            # .__name__ == "_signal_log"
                            # the function has been extended to manage extra arguments
                            or "_extend_callback_parameters"
                            in repr(sub_callback_function.func)
                        ):
                            continue
                        missing_parameters_indices += self._get_missing_parameters_indices(
                            sub_callback_function.func
                        )
                    else:
                        missing_parameters_indices += self._get_missing_parameters_indices(
                            sub_callback_function
                        )
            else:
                missing_parameters_indices = self._get_missing_parameters_indices(
                    callback_function
                )
            missing_parameters_indices = list(set(missing_parameters_indices))
            return _extend_callback_parameters(callback_function, missing_parameters_indices)

    def _get_missing_parameters_indices(self, callback_function: CallbackFunc) -> List[int]:
        signature = inspect.signature(callback_function)
        missing_parameters_indices = list(range(len(self.parameter_types)))
        missing_annotation = False
        for callback_parameter in signature.parameters.values():
            if callback_parameter.kind in (
                # inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.POSITIONAL_ONLY,
            ):
                # When annotation is missing it doesn't matter to check the type
                # of the parameters of the signal to remove precisely the existing
                # parameter. So the first parameter is removed instead. And the type is
                # no more checked going forward.
                if (
                    missing_annotation
                    or callback_parameter.annotation == inspect.Parameter.empty
                ):
                    missing_annotation = True
                    del missing_parameters_indices[0]
                else:
                    for i, signal_parameter in enumerate(self.parameter_types):
                        # the parameters of the signals are strings as opposed to
                        # the annotation of a signature
                        if signal_parameter in str(callback_parameter.annotation):
                            missing_parameters_indices.remove(i)
                            break
        return missing_parameters_indices

    @staticmethod
    def _find_parameter_types(obj: "QObject", signal: "SignalInstance") -> List[Any]:
        signal_name = ""
        for signal_name in dir(obj):
            if getattr(obj, signal_name) == signal or getattr(obj, signal_name) is signal:
                break
        else:
            # Unreachable
            msg = f"Can't find the signal name of '{signal}' from the given object {obj}"
            raise ValueError(msg)
        obj_meta = obj.metaObject()
        for i in range(obj_meta.methodCount()):
            m = obj_meta.method(i)
            m_type = m.methodType()
            if (
                # For PyQt5 methodType returns an int and for PySide6 it returns an Enum
                # Signal == 1
                (isinstance(m_type, enum.Enum) and m_type.value == 1)
                or m_type == 1
            ) and m.name().data().decode() == signal_name:
                return [param_type.data().decode() for param_type in m.parameterTypes()]
        return []


class BaseSignal(MutableSequence[Callback]):
    def __init__(self, *parameter_types: Any) -> None:
        super().__init__()
        self._name = ""
        self._parameter_types = parameter_types
        self._qt_signals: List[_BaseQtSignal] = []
        self.allow_calling = False
        self._initial_callbacks: List[Callback] = []
        self._callbacks: List[CallbackFunc] = []
        self._tasks: Set[TaskCallBackFunc] = set()
        self._objs: MutableMapping[View, BaseSignal] = WeakKeyDictionary()
        self.current_view: Optional[ReferenceType[View]] = None
        self.current_parent_view: Optional[ReferenceType[View]] = None
        self.current_form_view: Optional[  # type:ignore[type-arg]
            ReferenceType[FormView]
        ] = (
            None
        )
        self.main_view: Optional[ReferenceType[View]] = None
        self.model: Optional[ReferenceType[BaseModel]] = None
        self.event_driven_app: Optional[
            ReferenceType[EventDrivenAppMixin[View, BaseModel]]
        ] = None

    def _signal_log(self, callback: Callback, *args: Any, **kwargs: Any) -> None:
        if callable(callback):
            callback_log = f"\n  -> CALL \x1b[31;20m{self._get_callback_name(callback)}\x1b[0m"
        else:
            callback_log = ""
            for sub_callback in callback:
                callback_log += (
                    f"\n  -> CALL \x1b[31;20m{self._get_callback_name( sub_callback)}\x1b[0m"
                )
        SIGNAL_LOGGER.debug("EMIT \x1b[31;20m[%s]\x1b[0m:%s", self._name, callback_log)

    def _get_callback_name(self, callback: CallbackFunc) -> str:
        if isinstance(callback, partial):
            return callback.func.__name__
        elif isinstance(callback, BaseSignal):
            return callback.name
        else:
            return callback.__name__

    @property
    def callbacks(self) -> Tuple[CallbackFunc, ...]:
        """Get the list of adapted signature callbacks."""
        return tuple(self._callbacks)

    @property
    def tasks(self) -> Set[TaskCallBackFunc]:
        return self._tasks

    @property
    def name(self) -> str:
        return self._name

    def add_qt_signals(
        self, *signal_infos: Union["SignalInstance", Tuple["QObject", "SignalInstance"]]
    ) -> None:
        for signal_info in signal_infos:
            if isinstance(signal_info, (tuple, list)):
                obj, signal = signal_info
            else:
                obj, signal = None, signal_info
            qt_signal = _BaseQtSignal(signal, obj, self._callbacks)
            self._qt_signals.append(qt_signal)

    def insert(self, index: int, callback: Callback) -> None:
        callback_func = self._create_callback_function(callback)
        # disconnect to connect after with the correct order
        self._disconnect(*self._callbacks)
        self._initial_callbacks.insert(index, callback)
        self._callbacks.insert(index, callback_func)
        # connect all the callbacks in the correct order
        self._connect(*self._callbacks)

    def clear(self) -> None:
        self._disconnect(*self._callbacks)
        self._initial_callbacks.clear()
        self._callbacks.clear()

    @overload
    def __getitem__(self, index: int) -> Callback: ...
    @overload
    def __getitem__(self, index: slice) -> MutableSequence[Callback]: ...

    def __getitem__(
        self, index: Union[int, slice]
    ) -> Union[Callback, MutableSequence[Callback]]:
        return self._initial_callbacks[index]

    @overload
    def __setitem__(self, index: int, value: Callback) -> None: ...

    @overload
    def __setitem__(self, index: slice, value: Iterable[Callback]) -> None: ...

    def __setitem__(
        self, index: Union[int, slice], value: Union[Callback, Iterable[Callback]]
    ) -> None:
        if isinstance(index, slice) and isinstance(value, Iterable):
            self._disconnect(*self._callbacks[index])
            self._initial_callbacks[index] = value
            slot_functions = [self._create_callback_function(c) for c in value]
            self._callbacks[index] = slot_functions
            self._connect(*slot_functions)
        elif isinstance(index, int) and not isinstance(value, Iterable):
            self._disconnect(self._callbacks[index])
            self._initial_callbacks[index] = value
            slot_function = self._create_callback_function(value)
            self._callbacks[index] = slot_function
            self._connect(slot_function)

    @overload
    def __delitem__(self, index: int) -> None: ...
    @overload
    def __delitem__(self, index: slice) -> None: ...

    def __delitem__(self, index: Union[int, slice]) -> None:
        if isinstance(index, int):
            self._disconnect(self._callbacks[index])
        else:
            self._disconnect(*self._callbacks[index])
        del self._initial_callbacks[index]
        del self._callbacks[index]

    def __len__(self) -> int:
        return len(self._callbacks)

    def __call__(self, *args: Any) -> None:
        if self.allow_calling or len(self._qt_signals) == 0:
            for callback_function in self._callbacks:
                if asyncio.iscoroutinefunction(callback_function) or (
                    hasattr(callback_function, "func")
                    and asyncio.iscoroutinefunction(callback_function.func)
                ):
                    if sys.version_info >= (3, 7):  # noqa: UP036
                        task = asyncio.create_task(callback_function(*args))
                    else:
                        task = asyncio.ensure_future(callback_function(*args))
                    self._tasks.add(task)
                    task.add_done_callback(self._tasks.discard)
                else:
                    callback_function(*args)
        else:
            raise TypeError("'BaseSignal' is not callable")

    def _connect(self, *slot_functions: CallbackFunc) -> None:
        for signal in self._qt_signals:
            signal.connect(*slot_functions)

    def _disconnect(self, *slot_functions: CallbackFunc) -> None:
        r"""Disconnect all the callback functions of the signals."""
        for signal_child in self._qt_signals:
            signal_child.disconnect(*slot_functions)

    def _create_callback_function(self, callback: Callback) -> CallbackFunc:
        """Create a callback function compatible with the signature of the signal.

        - If it is a simple callback function then the signature is adapted to be compatible
            with the type of the parameters of the signal.
            * If the callback contains as parameters the usual
                view, parent_view, main_view, model then a partial is created to call them
            * If one of the parameter correspond to the parameter types of the signal
                then it is keeped
            * If the signal need parameter types that is missing in the callback then
                a function is created adding this parameter and calling the callback
                without using these parameters just to avoid a crash
            * If the function has excessive parameters then it will not be modified which
                can lead to a crash or if a qt signal is used then it is managed by the
                qt signal.
        - If it is a list of callback then a function is created calling each callback one
            after the other in the order of the given list.
            Each of the callback have there signature adapted as described above.
        """
        callback_function = None
        partial_callback: List[CallbackFunc]
        if asyncio.iscoroutinefunction(callback):
            callback_function = self._to_partial(callback)
            # TODO: manage signal_log for coroutines
        elif callable(callback):
            partial_callback = [
                partial(self._signal_log, callback),
                self._to_partial(callback),
            ]
            callback_function = partial(_call_callback_functions, partial_callback)
        elif isinstance(callback, Iterable):
            if len(callback) == 0:
                raise ValueError("Can't connect a signal to an empty list")
            elif all(callable(f) for f in callback):
                partial_callback = [
                    partial(self._signal_log, callback),
                    *(self._to_partial(f) for f in callback),
                ]
                callback_function = partial(_call_callback_functions, partial_callback)
        if callback_function is None:
            raise ValueError("A signal can be connected only to a callable object")
        else:
            return callback_function

    def _to_partial(self, callback: CallbackFunc) -> CallbackFunc:
        """Return a partial with eventually view, parent_view, main_view, model assigned."""
        signature = inspect.signature(callback)
        if len(signature.parameters) == 0:
            return callback
        else:
            default_kwargs = {
                "view": self.current_view,
                "parent_view": self.current_parent_view,
                "form_view": self.current_form_view,
                "main_view": self.main_view,
                "model": self.model,
                "app": self.event_driven_app,
            }
            kwargs = {}
            index_positional_arg = 0
            missing_parameters_indices = list(range(len(self._parameter_types)))
            missing_annotation = False
            for arg_name, callback_parameter in signature.parameters.items():
                if (
                    callback_parameter.kind == inspect.Parameter.KEYWORD_ONLY
                    and callback_parameter.default == inspect.Parameter.empty
                ):
                    if arg_name in default_kwargs:
                        default_kwargs_value = default_kwargs[arg_name]
                        if default_kwargs_value is not None:
                            kwargs[arg_name] = default_kwargs_value()
                elif callback_parameter.kind in (
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    inspect.Parameter.POSITIONAL_ONLY,
                ):
                    # When annotation is missing it doesn't matter to check the type
                    # of the parameters of the signal to remove precisely the existing
                    # parameter. So the first parameter is removed instead. And the type is
                    # no more checked going forward.
                    if (
                        missing_annotation
                        or callback_parameter.annotation == inspect.Parameter.empty
                    ):
                        missing_annotation = True
                        del missing_parameters_indices[0]
                    else:
                        for i, signal_parameter in enumerate(self._parameter_types):
                            if callback_parameter.annotation == signal_parameter:
                                missing_parameters_indices.remove(i)
                                break
                    index_positional_arg += 1
            if asyncio.iscoroutinefunction(callback) and len(self._qt_signals) > 0:
                async_callback = callback
                callback = lambda *args, **kwargs: asyncio.ensure_future(  # noqa: E731
                    async_callback(*args, **kwargs)
                )
            if len(missing_parameters_indices) > 0:
                return partial(
                    _extend_callback_parameters(callback, missing_parameters_indices),
                    **kwargs,
                )
            return partial(callback, **kwargs)

    def __set_name__(self, _: Optional[Type["View"]], name: str) -> None:
        self._name = name

    def __get__(self, obj: Optional["View"], obj_type: Optional[Type["View"]]) -> "BaseSignal":
        if obj is None:
            return self
        else:
            base_signal = BaseSignal(*self._parameter_types)
            base_signal._name = self._name
            return self._objs.setdefault(obj, base_signal)

    def __set__(self, obj: Optional["View"], value: Iterable[Callback]) -> None:
        if obj is not None:
            self._objs.setdefault(obj, BaseSignal(*self._parameter_types))
            if isinstance(value, BaseSignal):
                self._objs[obj] = value
            elif isinstance(value, Iterable):
                self._objs[obj].clear()
                self._objs[obj].extend(value)
            else:
                msg = (  # type: ignore[unreachable]
                    f"'{value}' is not admissible for BaseSignal."
                    "Only a list (or a list of lists) of callables "
                    "or an instanciation of BaseSignal is allowed"
                )
                raise TypeError(msg)

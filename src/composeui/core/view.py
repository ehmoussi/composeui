# from __future__ import annotations

import enum
import json
import logging
import sys
import threading
from abc import abstractmethod
from collections import deque
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Generic,
    Optional,
    TypeVar,
    Union,
    cast,
    get_args,
    get_origin,
    overload,
)

import attrs
import cattrs
from cattrs.gen import AttributeOverride, make_dict_unstructure_fn, override
from typing_extensions import dataclass_transform

from composeui.core.renderer import Renderer, RendererContainer
from composeui.core.signal import Signal, SignalNoArgs

if TYPE_CHECKING:
    from attrs import AttrsInstance


LOGGER = logging.getLogger("COMPOSEUI_VIEW")
_STREAM_HANDLER = logging.StreamHandler(sys.stdout)
_STREAM_HANDLER.setFormatter(logging.Formatter("%(asctime)s: %(message)s", "%Y-%m-%d %H:%M:%S"))
LOGGER.addHandler(_STREAM_HANDLER)


CONVERTER = cattrs.Converter()

_OMITTED_TYPES = (Signal, Renderer, RendererContainer, threading.Timer)


def _is_omitted_type(tp: Any) -> bool:
    """Check whether a (possibly generic/Optional/Union) type is or wraps an omitted type."""
    origin = get_origin(tp)
    if origin is Union:
        return any(_is_omitted_type(arg) for arg in get_args(tp))
    cls = origin if origin is not None else tp
    return isinstance(cls, type) and issubclass(cls, _OMITTED_TYPES)


@CONVERTER.register_unstructure_hook_factory(attrs.has)
def _omit_renderer_and_signals(
    cls: "type[AttrsInstance]",
) -> Callable[[Any], dict[str, Any]]:
    attrs.resolve_types(cls)
    overrides: dict[str, AttributeOverride] = {
        str(f.name): override(omit=True) for f in attrs.fields(cls) if _is_omitted_type(f.type)
    }
    unstructure = make_dict_unstructure_fn(
        cls,
        CONVERTER,
        _cattrs_omit_if_default=True,
        _cattrs_use_linecache=True,
        _cattrs_use_alias="from_converter",
        _cattrs_include_init_false=False,
        **overrides,
    )
    if not issubclass(cls, RadioGroupMixin):
        return unstructure

    def unstructure_radio_group(obj: "RadioGroupMixin[Any]") -> dict[str, Any]:
        data = unstructure(cast("AttrsInstance", obj))
        data["value"] = obj.serialize_value()
        return data

    return unstructure_radio_group


def _apply_state(view: "View", data: dict[str, Any]) -> None:
    """Update a live view tree in place from previously saved state.

    A fresh ``CONVERTER.structure(data, type(view))`` would build new nested
    view instances, losing their bound renderers and connected signals. Setting
    the existing attributes instead lets the normal ``notify_renderer``
    on_setattr hook refresh the UI as each value is applied.

    ``RadioGroupMixin.value`` is handled separately: its declared type is an
    unresolved generic ``TypeVar`` that cattrs can't structure statically, so it is
    restored through `RadioGroupMixin.deserialize_value` instead, which resolves it
    via the mixin's own `values` label lookup. ``RadioGroupMixin.values`` is included
    in saved state (for inspection/debugging) but never restored from it on load: it's
    app-defined config, not persisted user data, and has the same unresolved-`TValue`
    structuring problem `value` has, without an equivalent label-based workaround.
    """
    states = deque([(view, data)])
    while len(states) > 0:
        current_view, new_data = states.popleft()
        current_cls = cast("type[AttrsInstance]", type(current_view))
        attrs.resolve_types(current_cls)
        if isinstance(current_view, RadioGroupMixin) and "value" in new_data:
            current_view.value = current_view.deserialize_value(new_data["value"])
        for f in attrs.fields(current_cls):
            if (
                f.name not in new_data
                or _is_omitted_type(f.type)
                or f.on_setattr is attrs.setters.frozen
                or (f.name in ("value", "values") and isinstance(current_view, RadioGroupMixin))
            ):
                continue
            new_value = new_data[f.name]
            current_field = getattr(current_view, f.name, None)
            if isinstance(current_field, View) and isinstance(new_value, dict):
                states.append((current_field, new_value))
            else:
                setattr(current_view, f.name, CONVERTER.structure(new_value, f.type))


class RendererType(enum.Enum):
    QT = enum.auto()
    TEXTUAL = enum.auto()


def notify_renderer(instance: "View", attribute: Any, value: Any) -> Any:
    attribute_name = str(attribute.name)
    if not attribute_name.startswith("_") and hasattr(instance, attribute_name):
        old_value = getattr(instance, attribute_name)
        if (
            old_value != value
            and isinstance(instance.renderer, (Renderer, RendererContainer))
            and not instance.renderer.is_updating_state()
        ):
            instance.renderer.refresh_attribute(attribute.name, value)
    return value


T = TypeVar("T", bound=type)


@overload
def define_view(cls: T) -> T: ...
@overload
def define_view(cls: None = None, **kwargs: Any) -> Callable[[T], T]: ...
@dataclass_transform(kw_only_default=True, field_specifiers=(attrs.field,))
def define_view(cls: Union[T, None] = None, **kwargs: Any) -> Union[T, Callable[[T], T]]:
    def wrap(cls: T) -> T:
        if "on_setattr" in kwargs:
            if isinstance(kwargs["on_setattr"], Sequence):
                kwargs["on_setattr"] = [*kwargs["on_setattr"], notify_renderer]
            else:
                kwargs["on_setattr"] = [kwargs["on_setattr"], notify_renderer]
        return attrs.define(
            cls,
            on_setattr=[attrs.setters.validate, notify_renderer],
            kw_only=True,
            slots=False,
            **kwargs,
        )

    if cls is None:
        return wrap
    return wrap(cls)


@define_view
class View:
    # properties
    is_visible: bool = attrs.field(default=True)
    is_enabled: bool = attrs.field(default=True)
    # renderer
    renderer: Optional[Union[Renderer[Any, Any], RendererContainer[Any]]] = attrs.field(
        default=None
    )

    def __attrs_post_init__(self) -> None:
        for f in attrs.fields(cast("type[AttrsInstance]", type(self))):
            signal = getattr(self, f.name, None)
            if isinstance(signal, Signal):
                signal.set_name(f"{type(self).__name__}.{f.name}")

    @property
    def children_views(self) -> list["View"]:
        """Get all the field rows of the form view."""
        children_views: list[View] = []
        for field_row_attr in attrs.fields(cast("type[AttrsInstance]", type(self))):
            view = getattr(self, field_row_attr.name)
            if isinstance(view, View):
                children_views.append(view)
        return children_views

    def render(self, renderer_type: RendererType) -> None:
        self._render_children(renderer_type)
        if self.renderer is None:
            self._create_renderer(renderer_type)
        if self.renderer is not None:
            self.renderer.render()

    def _create_renderer(self, renderer_type: RendererType) -> None:
        """Create the renderer of the view."""
        raise NotImplementedError(self._create_renderer)

    def _render_children(self, renderer_type: RendererType) -> None:
        for child_view in self.children_views:
            child_view.render(renderer_type)


@define_view
class StatusBar(View):
    message: str = attrs.field(default="")
    message_changed: Signal[str] = attrs.Factory(Signal[str])
    timeout: float = attrs.field(default=3.0)
    _timer: Optional[threading.Timer] = attrs.field(default=None)

    def show_message(self, message: str) -> None:
        """Show a message.

        The message is dismissed after timeout seconds. A timeout of 0 means
        the message is never automatically dismissed.
        """
        self.message = message
        if self._timer is not None:
            self._timer.cancel()
        if self.timeout > 0:
            self._timer = threading.Timer(self.timeout, self._dispatch_clear_message)
            self._timer.start()

    def _dispatch_clear_message(self) -> None:
        """Run `clear_message` on the renderer's thread, not the timer's own thread.

        `threading.Timer` calls its target on a dedicated background thread; a bound
        renderer (e.g. Qt) may only be touched from its GUI thread, so the actual
        mutation has to be marshaled through `Renderer.call_on_main_thread` instead
        of calling `clear_message` here directly.
        """
        if self.renderer is not None:
            self.renderer.call_on_main_thread(self.clear_message)
        else:
            self.clear_message()

    def clear_message(self) -> None:
        self.message = ""
        self._timer = None

    def _create_renderer(self, renderer_type: RendererType) -> None:
        if renderer_type == RendererType.QT:
            from composeui.qtcore.qtrenderer import QtStatusBarRenderer  # noqa: PLC0415

            self.renderer = QtStatusBarRenderer(self)
        elif renderer_type == RendererType.TEXTUAL:
            from composeui.textualcore.textualrenderer import (  # noqa: PLC0415
                TextualStatusBarRenderer,
            )

            self.renderer = TextualStatusBarRenderer(self)


# class FileType(enum.Enum):
#     OpenFile = enum.auto()
#     SaveFile = enum.auto()


@define_view
class FileView(View):
    filepath: Optional[Path] = attrs.field(default=None)
    extensions: dict[str, tuple[str, ...]] = attrs.Factory(dict[str, tuple[str, ...]])
    # file_type: FileType = attrs.field(default=FileType.OpenFile)

    def _create_renderer(self, renderer_type: RendererType) -> None:
        return None


@define_view
class ActionView(View):
    text: str = attrs.field(default="")
    icon: Optional[str] = attrs.field(default=None)
    data: Any = attrs.field(default=None)
    shortcut: Optional[str] = attrs.field(default=None)
    is_checkable: bool = attrs.field(default=False)
    is_checked: bool = attrs.field(default=False)

    triggered: SignalNoArgs = attrs.Factory(SignalNoArgs)

    def _create_renderer(self, renderer_type: RendererType) -> None:
        if renderer_type == RendererType.QT:
            from composeui.qtcore.qtrenderer import QtActionRenderer  # noqa: PLC0415

            self.renderer = QtActionRenderer(self)


@define_view
class SeparatorAction(View):
    def _create_renderer(self, renderer_type: RendererType) -> None:
        if renderer_type == RendererType.QT:
            from composeui.qtcore.qtrenderer import QtSeparatorRenderer  # noqa: PLC0415

            self.renderer = QtSeparatorRenderer(self)


@define_view
class Menu(View):
    title: str = attrs.field(default="")

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        # the menu should be visible only when triggered
        self.is_visible = False


@define_view
class NewAction(ActionView):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.shortcut = "Ctrl+n"
        self.text = "New"
        self.is_checkable = False
        self.icon = None
        self.data = None
        self.triggered.connect(self._new_study)

    def _new_study(self) -> None: ...


@define_view
class OpenFileAction(ActionView):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.text = "Open"
        self.shortcut = "Ctrl+o"
        self.is_checkable = False
        self.icon = None
        self.data = None
        self.triggered.connect(self._open_study)

    def _open_study(self) -> None: ...


@define_view
class SaveAction(ActionView):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.text = "Save"
        self.shortcut = "Ctrl+s"
        self.is_checkable = False
        self.icon = None
        self.data = None
        self.triggered.connect(self._save_study)

    def _save_study(self) -> None: ...


@define_view
class SaveAsAction(ActionView):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.text = "Save As"
        self.shortcut = "Ctrl+Shift+s"
        self.is_checkable = False
        self.icon = None
        self.data = None
        self.triggered.connect(self._save_new_study)

    def _save_new_study(self) -> None: ...


@define_view
class ExitAppAction(ActionView):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.text = "Exit"
        self.shortcut = "Ctrl+q"
        self.is_checkable = False
        self.icon = None
        self.data = None
        self.triggered.connect(self._exit_app)

    def _exit_app(self, *, main_view: "MainView") -> None:
        main_view.close()


@define_view
class FileMenu(Menu):
    new: NewAction = attrs.Factory(NewAction)
    open_file: OpenFileAction = attrs.Factory(OpenFileAction)
    save: SaveAction = attrs.Factory(SaveAction)
    save_as: SaveAsAction = attrs.Factory(SaveAsAction)
    separator_exit: SeparatorAction = attrs.Factory(SeparatorAction)
    exit_app: ExitAppAction = attrs.Factory(ExitAppAction)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.title = "File"
        self.save.triggered.connect(self._save_state)
        self.open_file.triggered.connect(self._load_state)

    def _create_renderer(self, renderer_type: RendererType) -> None:
        if renderer_type == RendererType.QT:
            from composeui.qtcore.qtrenderer import QtMenuRenderer  # noqa: PLC0415

            self.renderer = QtMenuRenderer(self)

    def _load_state(self, *, main_view: "MainView") -> None:
        filepath = main_view.ask_open_filepath(
            extensions={main_view.extension: (f"{main_view.extension}",)}
        )
        if filepath is not None:
            main_view.load_state(filepath)

    def _save_state(self, *, main_view: "MainView") -> None:
        filepath = main_view.ask_save_filepath(
            extensions={main_view.extension: (f"{main_view.extension}",)}
        )
        if filepath is not None:
            main_view.save_state(filepath)


@define_view
class MainView(View):
    title: str = attrs.field(init=False, on_setattr=attrs.setters.frozen)
    extension: str = attrs.field(init=False, on_setattr=attrs.setters.frozen)
    state_filepath: Optional[Path] = None

    minimum_width: int = attrs.field(default=720)
    minimum_height: int = attrs.field(default=480)

    file_menu: FileMenu = FileMenu(title="File")
    # study_toolbar: StudyToolbar = StudyToolbar(title="study")
    file_view: FileView = attrs.Factory(FileView)
    # message_view: MessageView = MessageView()
    status_bar: StatusBar = attrs.Factory(StatusBar)

    def _init_app_info(self, *, title: str, extension: str) -> None:
        """Set `title`/`extension` once, meant to be called from `__attrs_post_init__`."""
        object.__setattr__(self, "title", title)
        object.__setattr__(self, "extension", extension)

    def load_state(self, filepath: Path) -> None:
        """Load the current state saved in a json file."""
        with filepath.open() as f:
            data = json.load(f)
        _apply_state(self, data)
        self.state_filepath = filepath

    def save_state(self, filepath: Path) -> None:
        """Save the current state into a json file."""
        with filepath.open("w") as f:
            json.dump(CONVERTER.unstructure(self), f)
        self.state_filepath = filepath

    def ask_open_filepath(self, extensions: dict[str, tuple[str, ...]]) -> Optional[Path]:
        from composeui.qtcore.qtrenderer import QtMainRenderer  # noqa: PLC0415

        self.file_view.extensions = extensions
        if isinstance(self.renderer, QtMainRenderer):
            self.file_view.filepath = self.renderer.open_file()
        return self.file_view.filepath

    def ask_save_filepath(self, extensions: dict[str, tuple[str, ...]]) -> Optional[Path]:
        from composeui.qtcore.qtrenderer import QtMainRenderer  # noqa: PLC0415

        self.file_view.extensions = extensions
        if isinstance(self.renderer, QtMainRenderer):
            self.file_view.filepath = self.renderer.save_file()
        return self.file_view.filepath

    def close(self) -> None:
        from composeui.qtcore.qtrenderer import QtMainRenderer  # noqa: PLC0415
        from composeui.textualcore.textualrenderer import TextualMainRenderer  # noqa: PLC0415

        if isinstance(self.renderer, (QtMainRenderer, TextualMainRenderer)):
            self.renderer.close()

    def _create_renderer(self, renderer_type: RendererType) -> None:
        if renderer_type == RendererType.QT:
            from composeui.qtcore.qtrenderer import QtMainRenderer  # noqa: PLC0415

            self.renderer = QtMainRenderer(self)
        elif renderer_type == RendererType.TEXTUAL:
            from composeui.textualcore.textualrenderer import (  # noqa: PLC0415
                TextualMainRenderer,
            )

            self.renderer = TextualMainRenderer(self)


@define_view
class _InputView:
    # properties
    placeholder: str = attrs.field(default="")
    # signals
    editing_finished: SignalNoArgs = attrs.field(factory=SignalNoArgs)
    text_changed: Signal[str] = attrs.field(factory=Signal[str])
    text_edited: Signal[str] = attrs.field(factory=Signal[str])


@define_view
class InputMixin(_InputView):
    # properties
    text: str = attrs.field(default="")


@define_view
class InputView(InputMixin, View):
    def _create_renderer(self, renderer_type: RendererType) -> None:
        if renderer_type == RendererType.QT:
            from composeui.qtcore.qtrenderer import QtInputRenderer  # noqa: PLC0415

            self.renderer = QtInputRenderer(self)
        elif renderer_type == RendererType.TEXTUAL:
            from composeui.textualcore.textualrenderer import (  # noqa: PLC0415
                TextualInputRenderer,
            )

            self.renderer = TextualInputRenderer(self)


@define_view
class FloatInputMixin(_InputView):
    # properties
    value: Optional[float] = attrs.field(default=None)
    minimum: Optional[float] = attrs.field(default=None)
    maximum: Optional[float] = attrs.field(default=None)
    decimals: Optional[int] = attrs.field(default=None)


@define_view
class FloatInputView(FloatInputMixin, View):
    def _create_renderer(self, renderer_type: RendererType) -> None:
        if renderer_type == RendererType.QT:
            from composeui.qtcore.qtrenderer import QtFloatInputRenderer  # noqa: PLC0415

            self.renderer = QtFloatInputRenderer(self)
        elif renderer_type == RendererType.TEXTUAL:
            from composeui.textualcore.textualrenderer import (  # noqa: PLC0415
                TextualFloatInputRenderer,
            )

            self.renderer = TextualFloatInputRenderer(self)


class LogType(enum.Enum):
    ERROR = enum.auto()
    WARNING = enum.auto()
    INFO = enum.auto()


@define_view
class LogMixin:
    log_message: str = attrs.field(default="")
    log_type: LogType = attrs.field(default=LogType.ERROR)


@define_view
class LogView(LogMixin, View):
    def _create_renderer(self, renderer_type: RendererType) -> None:
        if renderer_type == RendererType.QT:
            from composeui.qtcore.qtrenderer import QtLogRenderer  # noqa: PLC0415

            self.renderer = QtLogRenderer(self)
        elif renderer_type == RendererType.TEXTUAL:
            from composeui.textualcore.textualrenderer import (  # noqa: PLC0415
                TextualLogRenderer,
            )

            self.renderer = TextualLogRenderer(self)


@define_view
class LabelMixin:
    text: str = attrs.field(default="")


@define_view
class LabelView(LabelMixin, View):
    def _create_renderer(self, renderer_type: RendererType) -> None:
        if renderer_type == RendererType.QT:
            from composeui.qtcore.qtrenderer import QtLabelRenderer  # noqa: PLC0415

            self.renderer = QtLabelRenderer(self)
        elif renderer_type == RendererType.TEXTUAL:
            from composeui.textualcore.textualrenderer import (  # noqa: PLC0415
                TextualLabelRenderer,
            )

            self.renderer = TextualLabelRenderer(self)


TValue = TypeVar("TValue")


@define_view
class RadioGroupMixin(Generic[TValue]):
    def _check_value(self, _attribute: "attrs.Attribute[Any]", value: Optional[TValue]) -> None:
        """Reject a `value` that isn't `None` or one of the current `values`.

        Runs both at construction and on every later assignment (`define_view` wires
        `attrs.setters.validate` into the on_setattr pipeline). Set `values` before
        assigning `value`, or the check would always fail.
        """
        if value is not None and value not in self.values.values():
            if len(self.values) == 0:
                msg = (
                    f"Cannot set {type(self).__name__}.value to {value!r}: `values` is "
                    "empty. Set `values` before setting `value`."
                )
            else:
                msg = (
                    f"Cannot set {type(self).__name__}.value to {value!r}: not one of "
                    f"the available values {list(self.values)}."
                )
            raise ValueError(msg)

    def _reconcile_values(
        self, attribute: "attrs.Attribute[Any]", values: dict[str, TValue]
    ) -> dict[str, TValue]:
        """Clear `value` if it won't be a member of the new `values`, then notify the renderer.

        A dedicated on_setattr hook rather than a `validator=`: unlike `_check_value`, it
        has the side effect of resetting `value` when `values` changes out from under it,
        not just rejecting an invalid assignment. It replaces the class-level on_setattr
        pipeline for this field, so it calls `notify_renderer` itself at the end.
        """
        if self.value is not None and self.value not in values.values():
            LOGGER.warning(
                "%s.values no longer contains %r (the current value); clearing it.",
                type(self).__name__,
                self.value,
            )
            self.value = None
        return notify_renderer(cast("View", self), attribute, values)

    value: Optional[TValue] = attrs.field(default=None, validator=[_check_value])
    values: dict[str, TValue] = attrs.field(
        factory=dict[str, TValue],
        on_setattr=_reconcile_values,
    )
    value_changed: Signal[Optional[TValue]] = attrs.Factory(Signal[Optional[TValue]])

    def serialize_value(self) -> Optional[str]:
        """Serialize `value` as its label, the key it has in `values`."""
        if self.value is None:
            return None
        for label, candidate in self.values.items():
            if candidate == self.value:
                return label
        return None

    def deserialize_value(self, label: Optional[str]) -> Optional[TValue]:
        """Look up a label previously produced by `serialize_value` back into a TValue."""
        if label is None:
            return None
        if label not in self.values:
            LOGGER.warning(
                "Cannot restore %s.value from saved state: label %r is not among "
                "the current options %r.",
                type(self).__name__,
                label,
                list(self.values),
            )
            return None
        return self.values[label]


@define_view
class RadioGroupView(RadioGroupMixin[TValue], View):
    def _create_renderer(self, renderer_type: RendererType) -> None:
        if renderer_type == RendererType.QT:
            from composeui.qtcore.qtrenderer import QtRadioGroupRenderer  # noqa: PLC0415

            self.renderer = QtRadioGroupRenderer(self)
        elif renderer_type == RendererType.TEXTUAL:
            from composeui.textualcore.textualrenderer import (  # noqa: PLC0415
                TextualRadioGroupRenderer,
            )

            self.renderer = TextualRadioGroupRenderer(self)


@define_view
class FormRowView(LogMixin, View):
    def _create_renderer(self, renderer_type: RendererType) -> None:
        field_renderer = self._create_field_renderer(renderer_type)
        log_renderer: Renderer[Any, Any]
        if renderer_type == RendererType.QT and field_renderer is not None:
            from composeui.qtcore.qtrenderer import QtLogRenderer  # noqa: PLC0415

            log_renderer = QtLogRenderer(self)
            self.renderer = RendererContainer(self, {"field": field_renderer, "log": log_renderer})
        elif renderer_type == RendererType.TEXTUAL and field_renderer is not None:
            from composeui.textualcore.textualrenderer import (  # noqa: PLC0415
                TextualLogRenderer,
            )

            log_renderer = TextualLogRenderer(self)
            self.renderer = RendererContainer(self, {"field": field_renderer, "log": log_renderer})

    @abstractmethod
    def _create_field_renderer(
        self, renderer_type: RendererType
    ) -> Union[Renderer[Any, Any], None]: ...


@define_view
class FormLabelRowView(FormRowView):
    label: str = attrs.field(default="")

    def _create_renderer(self, renderer_type: RendererType) -> None:
        field_renderer = self._create_field_renderer(renderer_type)
        log_renderer: Renderer[Any, Any]
        label_renderer: Renderer[Any, Any]
        if renderer_type == RendererType.QT and field_renderer is not None:
            from composeui.qtcore.qtrenderer import (  # noqa: PLC0415
                QtFormLabelRenderer,
                QtLogRenderer,
            )

            log_renderer = QtLogRenderer(self)
            label_renderer = QtFormLabelRenderer(self)
            self.renderer = RendererContainer(
                self,
                {"label": label_renderer, "field": field_renderer, "log": log_renderer},
            )
        elif renderer_type == RendererType.TEXTUAL and field_renderer is not None:
            from composeui.textualcore.textualrenderer import (  # noqa: PLC0415
                TextualFormLabelRenderer,
                TextualLogRenderer,
            )

            log_renderer = TextualLogRenderer(self)
            label_renderer = TextualFormLabelRenderer(self)
            self.renderer = RendererContainer(
                self,
                {"label": label_renderer, "field": field_renderer, "log": log_renderer},
            )

    @abstractmethod
    def _create_field_renderer(
        self, renderer_type: RendererType
    ) -> Union[Renderer[Any, Any], None]: ...


@define_view
class RowInputView(FormRowView, InputMixin):
    def _create_field_renderer(
        self, renderer_type: RendererType
    ) -> Union[Renderer[Any, Any], None]:
        if renderer_type == RendererType.QT:
            from composeui.qtcore.qtrenderer import QtInputRenderer  # noqa: PLC0415

            return QtInputRenderer(self)
        if renderer_type == RendererType.TEXTUAL:
            from composeui.textualcore.textualrenderer import (  # noqa: PLC0415
                TextualInputRenderer,
            )

            return TextualInputRenderer(self)
        return None


@define_view
class LabelRowInputView(FormLabelRowView, InputMixin):
    def _create_field_renderer(
        self, renderer_type: RendererType
    ) -> Union[Renderer[Any, Any], None]:
        if renderer_type == RendererType.QT:
            from composeui.qtcore.qtrenderer import QtInputRenderer  # noqa: PLC0415

            return QtInputRenderer(self)
        if renderer_type == RendererType.TEXTUAL:
            from composeui.textualcore.textualrenderer import (  # noqa: PLC0415
                TextualInputRenderer,
            )

            return TextualInputRenderer(self)
        return None


@define_view
class RowFloatInputView(FormRowView, FloatInputMixin):
    def _create_field_renderer(
        self, renderer_type: RendererType
    ) -> Union[Renderer[Any, Any], None]:
        if renderer_type == RendererType.QT:
            from composeui.qtcore.qtrenderer import QtFloatInputRenderer  # noqa: PLC0415

            return QtFloatInputRenderer(self)
        if renderer_type == RendererType.TEXTUAL:
            from composeui.textualcore.textualrenderer import (  # noqa: PLC0415
                TextualFloatInputRenderer,
            )

            return TextualFloatInputRenderer(self)
        return None


@define_view
class LabelRowFloatInputView(FormLabelRowView, FloatInputMixin):
    def _create_field_renderer(
        self, renderer_type: RendererType
    ) -> Union[Renderer[Any, Any], None]:
        if renderer_type == RendererType.QT:
            from composeui.qtcore.qtrenderer import QtFloatInputRenderer  # noqa: PLC0415

            return QtFloatInputRenderer(self)
        if renderer_type == RendererType.TEXTUAL:
            from composeui.textualcore.textualrenderer import (  # noqa: PLC0415
                TextualFloatInputRenderer,
            )

            return TextualFloatInputRenderer(self)
        return None


@define_view
class RowRadioGroupView(FormRowView, RadioGroupMixin[TValue]):
    def _create_field_renderer(
        self, renderer_type: RendererType
    ) -> Union[Renderer[Any, Any], None]:
        if renderer_type == RendererType.QT:
            from composeui.qtcore.qtrenderer import QtRadioGroupRenderer  # noqa: PLC0415

            return QtRadioGroupRenderer(self)
        if renderer_type == RendererType.TEXTUAL:
            from composeui.textualcore.textualrenderer import (  # noqa: PLC0415
                TextualRadioGroupRenderer,
            )

            return TextualRadioGroupRenderer(self)
        return None


@define_view
class LabelRowRadioGroupView(FormLabelRowView, RadioGroupMixin[TValue]):
    def _create_field_renderer(
        self, renderer_type: RendererType
    ) -> Union[Renderer[Any, Any], None]:
        if renderer_type == RendererType.QT:
            from composeui.qtcore.qtrenderer import QtRadioGroupRenderer  # noqa: PLC0415

            return QtRadioGroupRenderer(self)
        if renderer_type == RendererType.TEXTUAL:
            from composeui.textualcore.textualrenderer import (  # noqa: PLC0415
                TextualRadioGroupRenderer,
            )

            return TextualRadioGroupRenderer(self)
        return None


@define_view
class FormView(View):
    log_view: LogView = attrs.field(factory=LogView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.log_view.is_visible = False

    @property
    def field_rows(self) -> list[Union[FormRowView, "FormView"]]:
        """Get all the field rows of the form view."""
        return [
            getattr(self, field_row_attr.name)
            for field_row_attr in attrs.fields(cast("type[AttrsInstance]", type(self)))
            if isinstance(getattr(self, field_row_attr.name), (FormRowView, FormView))
        ]

    def _create_renderer(self, renderer_type: RendererType) -> None:
        if renderer_type == RendererType.QT:
            from composeui.qtcore.qtrenderer import QtFormRenderer  # noqa: PLC0415

            self.renderer = QtFormRenderer(self)
        elif renderer_type == RendererType.TEXTUAL:
            from composeui.textualcore.textualrenderer import (  # noqa: PLC0415
                TextualFormRenderer,
            )

            self.renderer = TextualFormRenderer(self)


@define_view
class GroupFormView(FormView):
    title: str = attrs.field(default="")

    def _create_renderer(self, renderer_type: RendererType) -> None:
        if renderer_type == RendererType.QT:
            from composeui.qtcore.qtrenderer import QtGroupFormRenderer  # noqa: PLC0415

            self.renderer = QtGroupFormRenderer(self)
        elif renderer_type == RendererType.TEXTUAL:
            from composeui.textualcore.textualrenderer import (  # noqa: PLC0415
                TextualGroupFormRenderer,
            )

            self.renderer = TextualGroupFormRenderer(self)

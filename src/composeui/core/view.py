# from __future__ import annotations

import enum
import json
import logging
import sys
import threading
from collections import deque
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
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
from typing_extensions import Unpack, dataclass_transform

from composeui.core.registry import RendererType, create_renderer
from composeui.core.renderer import MainRenderer, Renderer, RendererContainer
from composeui.core.signal import Signal, SignalNoArgs

if TYPE_CHECKING:
    from attrs import AttrsInstance


LOGGER = logging.getLogger("COMPOSEUI_VIEW")
_STREAM_HANDLER = logging.StreamHandler(sys.stdout)
_STREAM_HANDLER.setFormatter(logging.Formatter("%(asctime)s: %(message)s", "%Y-%m-%d %H:%M:%S"))
LOGGER.addHandler(_STREAM_HANDLER)


CONVERTER = cattrs.Converter()

_OMITTED_TYPES = (Signal, Renderer, RendererContainer, threading.Timer)
#: Field metadata key for fields that must skip (de)serialization but aren't one of
#: `_OMITTED_TYPES` - e.g. `Validator` fields, whose type (bare/`Optional`/`list`-
#: wrapped `Callable`) isn't a single class `_is_omitted_type` can match generically.
OMIT = "omit"


def _is_omitted_type(tp: Any) -> bool:
    """Check whether a (possibly generic/Optional/Union) type is or wraps an omitted type."""
    origin = get_origin(tp)
    if origin is Union:
        return any(_is_omitted_type(arg) for arg in get_args(tp))
    cls = origin if origin is not None else tp
    return isinstance(cls, type) and issubclass(cls, _OMITTED_TYPES)


def _is_omitted_field(f: "attrs.Attribute[Any]") -> bool:
    """Check whether `f` should skip (de)serialization: by type, or by `OMIT` tag."""
    return _is_omitted_type(f.type) or bool(f.metadata.get(OMIT, False))


@CONVERTER.register_unstructure_hook_factory(attrs.has)
def _omit_renderer_and_signals(
    cls: "type[AttrsInstance]",
) -> Callable[[Any], dict[str, Any]]:
    attrs.resolve_types(cls)
    overrides: dict[str, AttributeOverride] = {
        str(f.name): override(omit=True) for f in attrs.fields(cls) if _is_omitted_field(f)
    }
    unstructure = make_dict_unstructure_fn(
        cls,
        CONVERTER,
        # every field, even one equal to its attrs default: views set their starting
        # state in `__attrs_post_init__`, so a default value left out of the file would
        # load back as that starting state instead (e.g. a validator message, or a
        # group hidden until an option shows it)
        _cattrs_omit_if_default=False,
        _cattrs_use_linecache=True,
        _cattrs_use_alias="from_converter",
        _cattrs_include_init_false=False,
        **overrides,
    )
    if not issubclass(cls, ValuesGroupMixin):
        return unstructure

    def unstructure_radio_group(obj: "ValuesGroupMixin[Any]") -> dict[str, Any]:
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

    ``ValuesGroupMixin.value`` is handled separately: its declared type is an
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
        if isinstance(current_view, ValuesGroupMixin) and "value" in new_data:
            current_view.value = current_view.deserialize_value(new_data["value"])
        for f in attrs.fields(current_cls):
            if (
                f.name not in new_data
                or _is_omitted_field(f)
                or f.on_setattr is attrs.setters.frozen
                or (f.name in ("value", "values") and isinstance(current_view, ValuesGroupMixin))
            ):
                continue
            new_value = new_data[f.name]
            current_field = getattr(current_view, f.name, None)
            if isinstance(current_field, View) and isinstance(new_value, dict):
                states.append((current_field, new_value))
            else:
                setattr(current_view, f.name, CONVERTER.structure(new_value, f.type))


def _reset_state(view: "View", initial: "View") -> None:
    """Set a live view tree back to `initial`'s state, in place.

    `initial` is a freshly built instance of the same class: copying from it, rather than
    from attrs defaults, also restores whatever its `__attrs_post_init__` set up (titles,
    `values`, an initial validator message...). Like `_apply_state`, it sets the existing
    attributes, so renderers and connected signals stay bound and only what actually
    changed is pushed to the UI. Fields `_apply_state` never restores are skipped the
    same way (omitted, frozen); `ValuesGroupMixin.values` is reset before `value`, which
    must be one of them.
    """
    states: deque[tuple[View, View]] = deque([(view, initial)])
    while len(states) > 0:
        current_view, initial_view = states.popleft()
        current_cls = cast("type[AttrsInstance]", type(current_view))
        attrs.resolve_types(current_cls)
        for f in attrs.fields(current_cls):
            if (
                _is_omitted_field(f)
                or f.on_setattr is attrs.setters.frozen
                or (f.name in ("value", "values") and isinstance(current_view, ValuesGroupMixin))
            ):
                continue
            current_field = getattr(current_view, f.name)
            initial_field = getattr(initial_view, f.name)
            if isinstance(current_field, View) and isinstance(initial_field, View):
                states.append((current_field, initial_field))
            else:
                setattr(current_view, f.name, initial_field)
        if isinstance(current_view, ValuesGroupMixin) and isinstance(
            initial_view, ValuesGroupMixin
        ):
            current_view.values = initial_view.values
            current_view.value = initial_view.value


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
    #: key of this view's renderer in the backend's ``RENDERERS`` mapping
    #: (see `composeui.core.registry`); concrete views set it
    _renderer_key: ClassVar[Optional[str]] = None

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
        if self._renderer_key is None:
            raise NotImplementedError(self._create_renderer)
        self.renderer = create_renderer(renderer_type, self._renderer_key, self)

    def _render_children(self, renderer_type: RendererType) -> None:
        for child_view in self.children_views:
            child_view.render(renderer_type)


@define_view
class StatusBar(View):
    _renderer_key = "status_bar"

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
    _renderer_key = "action"

    text: str = attrs.field(default="")
    icon: Optional[str] = attrs.field(default=None)
    data: Any = attrs.field(default=None)
    shortcut: Optional[str] = attrs.field(default=None)
    is_checkable: bool = attrs.field(default=False)
    is_checked: bool = attrs.field(default=False)

    triggered: SignalNoArgs = attrs.Factory(SignalNoArgs)


@define_view
class SeparatorAction(View):
    _renderer_key = "separator"


@define_view
class Menu(View):
    _renderer_key = "menu"

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

    def _new_study(self, *, main_view: "MainView") -> None:
        main_view.reset_state()


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
    _renderer_key = "main"

    title: str = attrs.field(init=False, on_setattr=attrs.setters.frozen)
    extension: str = attrs.field(init=False, on_setattr=attrs.setters.frozen)
    state_filepath: Optional[Path] = None

    minimum_width: int = attrs.field(default=720)
    minimum_height: int = attrs.field(default=480)

    file_menu: FileMenu = attrs.Factory(FileMenu)
    # study_toolbar: StudyToolbar = StudyToolbar(title="study")
    # a file dialog's last answer, not study data: never saved, loaded or reset
    file_view: FileView = attrs.field(factory=FileView, metadata={OMIT: True})
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

    def reset_state(self) -> None:
        """Set every view back to the state of a newly built main view (a new study).

        The tree is reset in place, as `load_state` loads into it, so renderers and
        connected signals keep working.
        """
        _reset_state(self, type(self)())

    def save_state(self, filepath: Path) -> None:
        """Save the current state into a json file."""
        with filepath.open("w") as f:
            json.dump(CONVERTER.unstructure(self), f)
        self.state_filepath = filepath

    def ask_open_filepath(self, extensions: dict[str, tuple[str, ...]]) -> Optional[Path]:
        self.file_view.extensions = extensions
        if isinstance(self.renderer, MainRenderer):
            self.file_view.filepath = self.renderer.open_file()
        return self.file_view.filepath

    def ask_save_filepath(self, extensions: dict[str, tuple[str, ...]]) -> Optional[Path]:
        self.file_view.extensions = extensions
        if isinstance(self.renderer, MainRenderer):
            self.file_view.filepath = self.renderer.save_file()
        return self.file_view.filepath

    def close(self) -> None:
        if isinstance(self.renderer, MainRenderer):
            self.renderer.close()


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
    _renderer_key = "input"


@define_view
class FloatInputMixin(_InputView):
    # properties
    value: Optional[float] = attrs.field(default=None)
    minimum: Optional[float] = attrs.field(default=None)
    maximum: Optional[float] = attrs.field(default=None)
    decimals: Optional[int] = attrs.field(default=None)


@define_view
class FloatInputView(FloatInputMixin, View):
    _renderer_key = "float_input"


class LogType(enum.Enum):
    ERROR = enum.auto()
    WARNING = enum.auto()
    INFO = enum.auto()


#: A zero-argument check: reads whatever state it needs itself (e.g. `self.text`
#: via a bound method) and returns an error message, or None if it passes.
Validator = Callable[[], Optional[str]]


@define_view
class LogMixin:
    log_message: str = attrs.field(default="")
    log_type: LogType = attrs.field(default=LogType.ERROR)
    validator: Optional[Validator] = attrs.field(default=None, repr=False, metadata={OMIT: True})

    def set_validator(
        self, validator: Validator, *signals: Signal[Unpack[tuple[Any, ...]]]
    ) -> None:
        """Wire `validator` to run against this row whenever any of `signals` fires.

        A failing (non-None) result is pushed into this row's own `log_message`/
        `log_type`; a passing (None) one clears them. Doesn't run `validator`
        immediately - call `run_validator()` afterward for an initial check (e.g. an
        empty required field should already show its error before the first edit).
        """
        self.validator = validator
        for signal in signals:
            signal.connect(self.run_validator)

    def run_validator(self, *_args: Any) -> None:
        """Re-run `validator`, if set, and push its result into the row's own log.

        Takes (and ignores) any positional args so it can be connected directly to
        signals of any arity - a per-keystroke `text_edited: Signal[str]` or a
        no-argument `editing_finished: SignalNoArgs` alike.
        """
        if self.validator is None:
            return
        message = self.validator()
        self.log_message = message or ""
        self.log_type = LogType.ERROR if message else LogType.INFO


@define_view
class LogView(LogMixin, View):
    _renderer_key = "log"


@define_view
class LabelMixin:
    text: str = attrs.field(default="")


@define_view
class LabelView(LabelMixin, View):
    _renderer_key = "label"


TValue = TypeVar("TValue")


@define_view
class ValuesGroupMixin(Generic[TValue]):
    def _check_value(self, _attribute: "attrs.Attribute[Any]", value: Optional[TValue]) -> None:
        """Reject a `value` that isn't `None` or one of the current `values`."""
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
        """Clear `value` if it won't be a member of the new `values`, then notify the renderer."""
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
class RadioGroupView(ValuesGroupMixin[TValue], View):
    _renderer_key = "radio_group"


@define_view
class ComboboxView(ValuesGroupMixin[TValue], View):
    _renderer_key = "combobox"


@define_view
class FormRowView(LogMixin, View):
    #: registry key of the row's field renderer; concrete rows set it
    _field_renderer_key: ClassVar[Optional[str]] = None

    def _create_renderer(self, renderer_type: RendererType) -> None:
        renderers = self._create_row_renderers(renderer_type)
        if renderers is not None:
            self.renderer = RendererContainer(self, renderers)

    def _create_row_renderers(
        self, renderer_type: RendererType
    ) -> Optional[dict[str, Renderer[Any, Any]]]:
        """Create the row's renderers, or None if the backend doesn't support the field."""
        if self._field_renderer_key is None:
            raise NotImplementedError(self._create_renderer)
        field_renderer = create_renderer(renderer_type, self._field_renderer_key, self)
        log_renderer = create_renderer(renderer_type, "log", self)
        if field_renderer is None or log_renderer is None:
            return None
        return {"field": field_renderer, "log": log_renderer}


@define_view
class FormLabelRowView(FormRowView):
    label: str = attrs.field(default="")

    def _create_row_renderers(
        self, renderer_type: RendererType
    ) -> Optional[dict[str, Renderer[Any, Any]]]:
        renderers = super()._create_row_renderers(renderer_type)
        label_renderer = create_renderer(renderer_type, "form_label", self)
        if renderers is None or label_renderer is None:
            return None
        return {"label": label_renderer, **renderers}


@define_view
class RowInputView(FormRowView, InputMixin):
    _field_renderer_key = "input"


@define_view
class LabelRowInputView(FormLabelRowView, InputMixin):
    _field_renderer_key = "input"


@define_view
class RowFloatInputView(FormRowView, FloatInputMixin):
    _field_renderer_key = "float_input"


@define_view
class LabelRowFloatInputView(FormLabelRowView, FloatInputMixin):
    _field_renderer_key = "float_input"


@define_view
class RowRadioGroupView(FormRowView, ValuesGroupMixin[TValue]):
    _field_renderer_key = "radio_group"


@define_view
class LabelRowRadioGroupView(FormLabelRowView, ValuesGroupMixin[TValue]):
    _field_renderer_key = "radio_group"


@define_view
class RowComboboxView(FormRowView, ValuesGroupMixin[TValue]):
    _field_renderer_key = "combobox"


@define_view
class LabelRowComboboxView(FormLabelRowView, ValuesGroupMixin[TValue]):
    _field_renderer_key = "combobox"


@define_view
class FormView(View):
    _renderer_key = "form"

    log_view: LogView = attrs.field(factory=LogView)
    _validators: list[Validator] = attrs.field(
        factory=list, init=False, repr=False, metadata={OMIT: True}
    )

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

    def add_validator(
        self, validator: Validator, *signals: Signal[Unpack[tuple[Any, ...]]]
    ) -> None:
        """Register a cross-field `validator`, re-run whenever any of `signals` fires.

        Unlike `LogMixin.set_validator` (one validator per row, using that row's own
        log), a form can have several independent cross-field checks - each failing
        (non-None) result is combined into this form's shared `log_view` instead of
        the last one winning (see `PipeFormView` in `examples/pipeform.py`, which has
        two independent checks spanning `main_pipe`/`incident_pipe`). Doesn't run
        immediately - call `validate()` afterward for an initial check.
        """
        self._validators.append(validator)
        for signal in signals:
            signal.connect(self.validate)

    def validate(self, *_args: Any) -> None:
        """Re-run every registered validator and push the combined result to `log_view`.

        Takes (and ignores) any positional args so it can be connected directly to
        signals of any arity, same as `LogMixin.run_validator`.
        """
        messages = [message for validator in self._validators if (message := validator())]
        if len(messages) > 0:
            self.log_view.log_message = "- " + "\n- ".join(messages)
            self.log_view.log_type = LogType.ERROR
            self.log_view.is_visible = True
        else:
            self.log_view.is_visible = False
            self.log_view.log_message = ""
            self.log_view.log_type = LogType.INFO


@define_view
class GroupFormView(FormView):
    _renderer_key = "group_form"

    title: str = attrs.field(default="")

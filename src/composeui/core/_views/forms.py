"""The form views and their rows."""

from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Optional,
    TypeVar,
    Union,
)

import attrs
from typing_extensions import override

from composeui.core._views.base import (
    OMIT,
    UI_TEXT,
    LogType,
    View,
    define_view,
    emit_if_made,
    view_fields,
)
from composeui.core._views.choices import (
    MultiComboBoxMixin,
    MultiValuesMixin,
    TValue,
    ValuesGroupMixin,
)
from composeui.core._views.content import LogMixin, LogView, Validator
from composeui.core._views.controls import (
    CheckBoxMixin,
    FloatRangeSliderMixin,
    FloatSliderMixin,
    RangeSliderMixin,
    SliderMixin,
)
from composeui.core._views.files import (
    FilePathInputMixin,
    FileUploadMixin,
    FolderPathInputMixin,
    SavePathInputMixin,
)
from composeui.core._views.inputs import (
    DateInputMixin,
    DateRangeInputMixin,
    FloatInputMixin,
    InputMixin,
    IntInputMixin,
    TextAreaMixin,
)
from composeui.core.registry import RendererType, create_renderer
from composeui.core.renderer import Renderer, RendererContainer
from composeui.core.signal import Signal, SignalNoArgs
from composeui.core.translation import (
    T,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from typing_extensions import Unpack


@define_view
class FormRowView(LogMixin, View):
    """A row of a form: a field, and the message of its check under it."""

    #: registry key of the row's field renderer; concrete rows set it
    _field_renderer_key: ClassVar[Optional[str]] = None

    #: set by `FormView.validate` while a cross-field check naming this row fails
    has_form_error: bool = attrs.field(default=False)

    @property
    def is_invalid(self) -> bool:
        """Whether the row's field shows as invalid: its own check or its form's fails."""
        return self.is_invalid_once("has_form_error", self.has_form_error)

    def is_invalid_once(self, name: str, value: Any) -> bool:
        """Get `is_invalid` once the attribute `name` is set to `value`.

        For renderers: they are notified of a change before it lands in the view (see
        `notify_renderer`), so `is_invalid` itself still answers for the old value.
        """
        state = {
            "has_form_error": self.has_form_error,
            "log_type": self.log_type,
            "log_message": self.log_message,
            name: value,
        }
        own_error = state["log_type"] is LogType.ERROR and state["log_message"] != ""
        return bool(state["has_form_error"]) or own_error

    @override
    def _create_renderer(self, renderer_type: RendererType) -> None:
        renderers = self._create_row_renderers(renderer_type)
        if renderers is not None:
            self.renderer = RendererContainer(self, renderers)

    @override
    @classmethod
    def _renderer_keys(cls) -> tuple[str, ...]:
        return () if cls._field_renderer_key is None else (cls._field_renderer_key, "log")

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
    """A row of a form with a label before its field, and a help button if it has `help`."""

    label: str = attrs.field(default="", metadata={UI_TEXT: True})
    #: what to enter in the field, shown by a "?" button beside the label (a hint on Textual)
    help: str = attrs.field(default="", metadata={UI_TEXT: True})
    #: the "?" button's name for screen readers
    help_button_text: str = attrs.field(default=T("Help"), metadata={UI_TEXT: True})

    @override
    @classmethod
    def _renderer_keys(cls) -> tuple[str, ...]:
        keys = super()._renderer_keys()
        return (*keys, "form_label") if len(keys) > 0 else ()

    @override
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
    """A row of a form with a field for one line of text, without a label."""

    _field_renderer_key = "input"


@define_view
class LabelRowInputView(FormLabelRowView, InputMixin):
    """A row of a form with a label and a field for one line of text."""

    _field_renderer_key = "input"


@define_view
class RowTextAreaView(FormRowView, TextAreaMixin):
    """A row of a form with a field for several lines of text, without a label."""

    _field_renderer_key = "text_area"


@define_view
class LabelRowTextAreaView(FormLabelRowView, TextAreaMixin):
    """A row of a form with a label and a field for several lines of text."""

    _field_renderer_key = "text_area"


@define_view
class RowFloatInputView(FormRowView, FloatInputMixin):
    """A row of a form with a field for a decimal number, without a label."""

    _field_renderer_key = "float_input"


@define_view
class LabelRowFloatInputView(FormLabelRowView, FloatInputMixin):
    """A row of a form with a label and a field for a decimal number."""

    _field_renderer_key = "float_input"


@define_view
class RowIntInputView(FormRowView, IntInputMixin):
    """A row of a form with a field for a whole number, without a label."""

    _field_renderer_key = "int_input"


@define_view
class LabelRowIntInputView(FormLabelRowView, IntInputMixin):
    """A row of a form with a label and a field for a whole number."""

    _field_renderer_key = "int_input"


@define_view
class RowDateInputView(FormRowView, DateInputMixin):
    """A row of a form with a date field, without a label."""

    _field_renderer_key = "date_input"


@define_view
class LabelRowDateInputView(FormLabelRowView, DateInputMixin):
    """A row of a form with a label and a date field."""

    _field_renderer_key = "date_input"


@define_view
class RowFileUploadView(FormRowView, FileUploadMixin):
    """A row of a form with a file upload, without a label."""

    _field_renderer_key = "file_upload"


@define_view
class LabelRowFileUploadView(FormLabelRowView, FileUploadMixin):
    """A row of a form with a label and a file upload."""

    _field_renderer_key = "file_upload"


@define_view
class RowFilePathInputView(FormRowView, FilePathInputMixin):
    """A row of a form with a file path field, without a label."""

    _field_renderer_key = "file_path_input"


@define_view
class LabelRowFilePathInputView(FormLabelRowView, FilePathInputMixin):
    """A row of a form with a label and a file path field."""

    _field_renderer_key = "file_path_input"


@define_view
class RowSavePathInputView(FormRowView, SavePathInputMixin):
    """A row of a form with a field of a path to save a file to, without a label."""

    _field_renderer_key = "save_path_input"


@define_view
class LabelRowSavePathInputView(FormLabelRowView, SavePathInputMixin):
    """A row of a form with a label and a field of a path to save a file to."""

    _field_renderer_key = "save_path_input"


@define_view
class RowFolderPathInputView(FormRowView, FolderPathInputMixin):
    """A row of a form with a folder path field, without a label."""

    _field_renderer_key = "folder_path_input"


@define_view
class LabelRowFolderPathInputView(FormLabelRowView, FolderPathInputMixin):
    """A row of a form with a label and a folder path field."""

    _field_renderer_key = "folder_path_input"


@define_view
class RowSliderView(FormRowView, SliderMixin):
    """A row of a form with a slider, without a label."""

    _field_renderer_key = "slider"


@define_view
class LabelRowSliderView(FormLabelRowView, SliderMixin):
    """A row of a form with a label and a slider."""

    _field_renderer_key = "slider"


@define_view
class RowFloatSliderView(FormRowView, FloatSliderMixin):
    """A row of a form with a decimal slider, without a label."""

    _field_renderer_key = "float_slider"


@define_view
class LabelRowFloatSliderView(FormLabelRowView, FloatSliderMixin):
    """A row of a form with a label and a decimal slider."""

    _field_renderer_key = "float_slider"


@define_view
class RowRangeSliderView(FormRowView, RangeSliderMixin):
    """A row of a form with a range slider, without a label."""

    _field_renderer_key = "range_slider"


@define_view
class LabelRowRangeSliderView(FormLabelRowView, RangeSliderMixin):
    """A row of a form with a label and a range slider."""

    _field_renderer_key = "range_slider"


@define_view
class RowFloatRangeSliderView(FormRowView, FloatRangeSliderMixin):
    """A row of a form with a decimal range slider, without a label."""

    _field_renderer_key = "float_range_slider"


@define_view
class LabelRowFloatRangeSliderView(FormLabelRowView, FloatRangeSliderMixin):
    """A row of a form with a label and a decimal range slider."""

    _field_renderer_key = "float_range_slider"


@define_view
class RowDateRangeInputView(FormRowView, DateRangeInputMixin):
    """A row of a form with a date range, without a label."""

    _field_renderer_key = "date_range_input"


@define_view
class LabelRowDateRangeInputView(FormLabelRowView, DateRangeInputMixin):
    """A row of a form with a label and a date range."""

    _field_renderer_key = "date_range_input"


@define_view
class RowCheckBoxView(FormRowView, CheckBoxMixin):
    """A row of a form with a check box, without a label."""

    _field_renderer_key = "checkbox"


@define_view
class LabelRowCheckBoxView(FormLabelRowView, CheckBoxMixin):
    """A row of a form with a label and a check box."""

    _field_renderer_key = "checkbox"


@define_view
class RowRadioGroupView(FormRowView, ValuesGroupMixin[TValue]):
    """A row of a form with a group of radio buttons, without a label."""

    _field_renderer_key = "radio_group"


@define_view
class LabelRowRadioGroupView(FormLabelRowView, ValuesGroupMixin[TValue]):
    """A row of a form with a label and a group of radio buttons."""

    _field_renderer_key = "radio_group"


@define_view
class RowComboBoxView(FormRowView, ValuesGroupMixin[TValue]):
    """A row of a form with a drop-down list, without a label."""

    _field_renderer_key = "combobox"


@define_view
class LabelRowComboBoxView(FormLabelRowView, ValuesGroupMixin[TValue]):
    """A row of a form with a label and a drop-down list."""

    _field_renderer_key = "combobox"


@define_view
class RowCheckListView(FormRowView, MultiValuesMixin[TValue]):
    """A row of a form with a list of check boxes, without a label."""

    _field_renderer_key = "check_list"


@define_view
class LabelRowCheckListView(FormLabelRowView, MultiValuesMixin[TValue]):
    """A row of a form with a label and a list of check boxes."""

    _field_renderer_key = "check_list"


@define_view
class RowMultiComboBoxView(FormRowView, MultiComboBoxMixin[TValue]):
    """A row of a form with a drop-down list of check boxes, without a label."""

    _field_renderer_key = "multi_combobox"


@define_view
class LabelRowMultiComboBoxView(FormLabelRowView, MultiComboBoxMixin[TValue]):
    """A row of a form with a label and a drop-down list of check boxes."""

    _field_renderer_key = "multi_combobox"


@define_view
class FormView(View):
    """A form: its rows, one above the other, and the message of its cross-field checks.

    Its `FormRowView` and `FormView` fields are its rows, in order (`field_rows`). Its
    other view fields, such as a table or a row of buttons, show in their place between
    the rows, as wide as the form (`content_views`). Its checks run on its rows only.
    """

    _renderer_key = "form"

    log_view: LogView = attrs.field(factory=LogView)
    #: the form's cross-field checks ran (`validate`), passing or not
    checked: SignalNoArgs = attrs.Factory(SignalNoArgs)
    #: each cross-field check with the rows it is about
    _validators: list[tuple[Validator, tuple[FormRowView, ...]]] = attrs.field(
        factory=list, init=False, repr=False, metadata={OMIT: True}
    )

    @override
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.log_view.is_visible = False

    @property
    def content_views(self) -> list[View]:
        """Get the views the form shows, in order: its rows and its other views, not its log."""
        return [view for view in self.children_views if view is not self.log_view]

    @property
    def field_rows(self) -> list[Union[FormRowView, FormView]]:
        """Get the rows of the form and its nested forms, in order."""
        return [
            getattr(self, field_row_attr.name)
            for field_row_attr in view_fields(type(self))
            if isinstance(getattr(self, field_row_attr.name), (FormRowView, FormView))
        ]

    def add_validator(
        self,
        validator: Validator,
        *signals: Signal[Unpack[tuple[Any, ...]]],
        rows: Sequence[FormRowView] = (),
    ) -> None:
        """Register a cross-field `validator`, re-run whenever any of `signals` fires.

        Unlike `LogMixin.set_validator` (one validator per row, in that row's own log), a form
        can have several independent cross-field checks. The form combines each failing
        (non-None) result into its shared `log_view`, instead of the last one winning. See
        ``PipeFormView`` in ``examples/pipeform.py``: it has two independent checks spanning
        ``main_pipe`` and ``incident_pipe``. It doesn't run immediately: call `validate`
        afterward for an initial check.

        `rows` are the rows that the check is about. While the check fails, each of them shows
        its field as invalid (`FormRowView.has_form_error`). So the user sees which values to
        fix, even though the message is in the form's log. The form that last validated a row
        flags it, so name a row in the checks of one form only.
        """
        self._validators.append((validator, tuple(rows)))
        for signal in signals:
            signal.connect(self.validate)

    @override
    def _check_again(self) -> None:
        if self.log_view.log_message != "":
            self.validate()

    def validate(self, *_args: Any) -> None:
        """Re-run every registered validator and push the combined result to `log_view`.

        Takes (and ignores) any positional args so it can be connected directly to
        signals of any arity, same as `LogMixin.run_validator`.
        """
        messages: list[str] = []
        failing: list[FormRowView] = []
        for validator, rows in self._validators:
            message = validator()
            if message:
                messages.append(message)
                failing.extend(rows)
        for _, rows in self._validators:
            for row in rows:
                row.has_form_error = any(row is failing_row for failing_row in failing)
        if len(messages) > 0:
            self.log_view.log_message = "- " + "\n- ".join(messages)
            self.log_view.log_type = LogType.ERROR
            self.log_view.is_visible = True
        else:
            self.log_view.is_visible = False
            self.log_view.log_message = ""
            self.log_view.log_type = LogType.INFO
        emit_if_made(self, "checked")  # a form's own isn't always connected: don't make it

    def check(self) -> None:
        """Run every check now: each row's, then each form's, nested forms first."""
        for row in self.field_rows:
            if isinstance(row, FormView):
                row.check()
            else:
                row.run_validator()
        self.validate()

    @property
    def is_valid(self) -> bool:
        """Whether no check shown fails: a row's own, the form's, or a nested form's.

        As last checked: a check that hasn't run yet passes (see `check`).
        """
        if self.log_view.log_type is LogType.ERROR and self.log_view.log_message != "":
            return False
        return all(
            row.is_valid if isinstance(row, FormView) else not row.is_invalid
            for row in self.field_rows
        )


@define_view
class GroupFormView(FormView):
    """A form in a box with a `title`, for example a group of related fields."""

    _renderer_key = "group_form"

    title: str = attrs.field(default="", metadata={UI_TEXT: True})


FormT = TypeVar("FormT", bound=FormView)

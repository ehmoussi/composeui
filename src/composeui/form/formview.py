from composeui.commontypes import AnyFormItems
from composeui.core.basesignal import BaseSignal
from composeui.core.views.pendingview import PendingView
from composeui.core.views.selectpathview import FileMode
from composeui.core.views.view import View
from composeui.form.abstractcomboboxitems import AbstractComboboxItems

from typing_extensions import OrderedDict

import enum
from dataclasses import dataclass, field
from typing import Any, Generic, Optional, Tuple, TypeVar, Union


@dataclass(eq=False)
class RowItemView(View, Generic[AnyFormItems]):
    parent_fields: Tuple[str, ...] = field(init=False, default_factory=tuple)
    field_name: str = field(init=False, default="")
    is_label: bool = field(init=False, default=False)
    items: Optional[AnyFormItems] = field(init=False, default=None)
    color: Optional[Tuple[int, int, int]] = field(init=False, default=None)


@dataclass(eq=False)
class NoLabelView(RowItemView[AnyFormItems]): ...


@dataclass(eq=False)
class LabelView(RowItemView[AnyFormItems]):
    text: str = field(init=False, default="")


@dataclass(eq=False)
class CheckBoxView(RowItemView[AnyFormItems]):
    text: str = field(init=False, default="")
    is_checked: bool = field(init=False, default=False)
    status_changed: BaseSignal = field(init=False, default=BaseSignal())

    def update(self) -> None:
        """Update the status of the checkbox label."""
        if self.items is not None:
            self.items.update(self.field_name, self.parent_fields, self.is_label)
        super().update()


@dataclass(eq=False)
class EditView(RowItemView[AnyFormItems]):
    editing_finished: BaseSignal = field(init=False, default=BaseSignal())
    text_edited: BaseSignal = field(init=False, default=BaseSignal())
    text_changed: BaseSignal = field(init=False, default=BaseSignal())

    def update(self) -> None:
        """Update the lineedit according to the items."""
        if self.items is not None:
            self.items.update(self.field_name, self.parent_fields, self.is_label)
        super().update()


@dataclass(eq=False)
class LineEditView(EditView[AnyFormItems]):
    text: str = field(init=False, default="")


class TextEditType(enum.Enum):
    PLAINTEXT = enum.auto()
    HTML = enum.auto()
    MARKDOWN = enum.auto()


@dataclass(eq=False)
class TextEditView(RowItemView[AnyFormItems]):
    text: str = field(init=False, default="")
    text_type: TextEditType = field(init=False, default=TextEditType.PLAINTEXT)
    text_color: Tuple[int, int, int, int] = field(init=False, default=(0, 0, 0, 255))
    text_background_color: Tuple[int, int, int, int] = field(
        init=False, default=(255, 255, 255, 255)
    )
    is_read_only: bool = field(init=False, default=False)

    cursor_position_changed: BaseSignal = field(init=False, default=BaseSignal())
    selection_changed: BaseSignal = field(init=False, default=BaseSignal())
    text_changed: BaseSignal = field(init=False, default=BaseSignal())

    def update(self) -> None:
        """Update the textedit according to the items."""
        if self.items is not None:
            self.items.update(self.field_name, self.parent_fields, self.is_label)
        super().update()

    def append_text(self, text: str) -> None:
        """Append the given text."""
        self.text += text


@dataclass(eq=False)
class DoubleLineEditView(EditView[AnyFormItems]):
    value: Optional[float] = field(init=False, default=None)
    minimum: float = field(init=False, default=0.0)
    maximum: float = field(init=False, default=0.0)
    decimals: int = field(init=False, default=0)


@dataclass(eq=False)
class Vector3DView(RowItemView[AnyFormItems]):
    values: Tuple[Optional[float], Optional[float], Optional[float]] = field(init=False)
    minimums: Tuple[float, float, float] = field(init=False)
    maximums: Tuple[float, float, float] = field(init=False)
    decimals: Tuple[int, int, int] = field(init=False)
    # signals
    editing_finished: BaseSignal = field(init=False, default=BaseSignal())
    text_edited: BaseSignal = field(init=False, default=BaseSignal())
    text_changed: BaseSignal = field(init=False, default=BaseSignal())

    def __post_init__(self) -> None:
        self.values = (None, None, None)
        self.minimums = (0.0, 0.0, 0.0)
        self.maximums = (0.0, 0.0, 0.0)
        self.decimals = (0, 0, 0)

    def update(self) -> None:
        """Update the view with the items."""
        if self.items is not None:
            self.items.update(self.field_name, self.parent_fields, self.is_label)
        super().update()


@dataclass(eq=False)
class SpinBoxView(RowItemView[AnyFormItems]):
    value: Optional[int] = field(init=False, default=None)
    minimum: int = field(init=False, default=0)
    maximum: int = field(init=False, default=0)
    step: int = field(init=False, default=0)
    value_changed: BaseSignal = field(init=False, default=BaseSignal())

    def update(self) -> None:
        """Update the view with the items."""
        if self.items is not None:
            self.items.update(self.field_name, self.parent_fields, self.is_label)
        super().update()


@dataclass(eq=False)
class ComboBoxView(RowItemView[AnyFormItems]):
    values: OrderedDict[Any, str] = field(init=False, default_factory=OrderedDict)
    current_index: int = field(init=False, default=0)
    current_index_changed: BaseSignal = field(init=False, default=BaseSignal())

    def update(self) -> None:
        """Update the view with the items."""
        if self.items is not None:
            self.items.update(self.field_name, self.parent_fields, self.is_label)
        super().update()


@dataclass(eq=False)
class ComboBoxItemsView(RowItemView[AnyFormItems], PendingView):
    pending_until_visible: bool = field(init=False, default=False)
    combobox_items: Optional[AbstractComboboxItems] = field(init=False, default=None)
    current_index: int = field(init=False, default=0)
    current_index_changed: BaseSignal = field(init=False, default=BaseSignal())


@dataclass(eq=False)
class ButtonsGroupView(RowItemView[AnyFormItems]):
    values: Tuple[str, ...] = field(init=False, default_factory=tuple)
    current_index: int = field(init=False, default=0)
    is_exclusive: bool = field(init=False, default=False)
    current_index_changed: BaseSignal = field(init=False, default=BaseSignal())

    def update(self) -> None:
        """Update the view with the items."""
        if self.items is not None:
            self.items.update(self.field_name, self.parent_fields, self.is_label)
        super().update()


@dataclass(eq=False)
class CheckBoxGroupView(ButtonsGroupView[AnyFormItems]): ...


@dataclass(eq=False)
class RadioButtonGroupView(ButtonsGroupView[AnyFormItems]): ...


@dataclass(eq=False)
class SelectFileView(LineEditView[AnyFormItems]):
    mode: FileMode = field(init=False, default="open_file")
    is_text_field_enabled: bool = field(init=False, default=False)
    is_button_enabled: bool = field(init=False, default=False)
    extensions: str = field(init=False, default="")
    button_text: str = field(init=False, default="")
    clicked: BaseSignal = field(init=False, default=BaseSignal())

    def update(self) -> None:
        """Update the text field according to the items."""
        if self.items is not None:
            self.items.update(self.field_name, self.parent_fields, self.is_label)
        super().update()


L = TypeVar("L", bound=RowItemView[Any])
F = TypeVar("F", bound=RowItemView[Any])


@dataclass(eq=False)
class RowView(View, Generic[AnyFormItems]):
    parent_fields: Tuple[str, ...] = field(init=False, default_factory=tuple)
    field_name: str = field(init=False, default="")
    items: Optional[AnyFormItems] = field(init=False, default=None)
    label_view: RowItemView[AnyFormItems] = field(init=False)
    field_view: RowItemView[AnyFormItems] = field(init=False)

    @property  # type: ignore[misc]
    def is_visible(self) -> bool:
        return self.label_view.is_visible and self.field_view.is_visible

    @is_visible.setter
    def is_visible(self, is_visible: bool) -> None:
        self.label_view.is_visible = is_visible
        self.field_view.is_visible = is_visible

    @property  # type: ignore[misc]
    def is_enabled(self) -> bool:
        return self.label_view.is_enabled and self.field_view.is_enabled

    @is_enabled.setter
    def is_enabled(self, is_enabled: bool) -> None:
        self.label_view.is_enabled = is_enabled
        self.field_view.is_enabled = is_enabled


@dataclass(eq=False)
class FormView(View, Generic[AnyFormItems]):
    parent_fields: Tuple[str, ...] = field(init=False, default_factory=tuple)
    field_name: str = field(init=False, default="")
    items: Optional[AnyFormItems] = field(init=False, default=None)
    infos: str = field(init=False, default="")
    field_changed: BaseSignal = field(init=False, default=BaseSignal())


@dataclass(eq=False)
class ApplyFormView(FormView[AnyFormItems]):
    validate_before_apply: bool = field(init=False, default=False)
    apply_clicked: BaseSignal = field(init=False, default=BaseSignal())


@dataclass(eq=False)
class GroupBoxFormView(FormView[AnyFormItems]):  # TODO: use IGroupView instead
    title: str = field(init=False, default="")
    is_checkable: bool = field(init=False, default=False)
    is_checked: bool = field(init=False, default=False)


@dataclass(eq=False)
class GroupBoxApplyFormView(ApplyFormView[AnyFormItems]):
    title: str = field(init=False, default="")
    is_checkable: bool = field(init=False, default=False)
    is_checked: bool = field(init=False, default=False)


RowItemValueView = Union[DoubleLineEditView[AnyFormItems], SpinBoxView[AnyFormItems]]
RowItemTextView = Union[
    LabelView[AnyFormItems],
    CheckBoxView[AnyFormItems],
    LineEditView[AnyFormItems],
    TextEditView[AnyFormItems],
    SelectFileView[AnyFormItems],
]
RowItemIndexView = Union[
    ComboBoxView[AnyFormItems],
    ComboBoxItemsView[AnyFormItems],
    ButtonsGroupView[AnyFormItems],
]


AnyRowItemView = TypeVar("AnyRowItemView", bound=RowItemView[Any])


# Label - Field View
@dataclass(eq=False)
class LabelLabelView(RowView[AnyFormItems]):
    label_view: LabelView[AnyFormItems] = field(
        init=False, default_factory=LabelView[AnyFormItems]
    )
    field_view: LabelView[AnyFormItems] = field(
        init=False, default_factory=LabelView[AnyFormItems]
    )


@dataclass(eq=False)
class LabelCheckBoxView(RowView[AnyFormItems]):
    label_view: LabelView[AnyFormItems] = field(
        init=False, default_factory=LabelView[AnyFormItems]
    )
    field_view: CheckBoxView[AnyFormItems] = field(
        init=False, default_factory=CheckBoxView[AnyFormItems]
    )


@dataclass(eq=False)
class LabelLineEditView(RowView[AnyFormItems]):
    label_view: LabelView[AnyFormItems] = field(
        init=False, default_factory=LabelView[AnyFormItems]
    )
    field_view: LineEditView[AnyFormItems] = field(
        init=False, default_factory=LineEditView[AnyFormItems]
    )


@dataclass(eq=False)
class LabelTextEditView(RowView[AnyFormItems]):
    label_view: LabelView[AnyFormItems] = field(
        init=False, default_factory=LabelView[AnyFormItems]
    )
    field_view: TextEditView[AnyFormItems] = field(
        init=False, default_factory=TextEditView[AnyFormItems]
    )


@dataclass(eq=False)
class LabelDoubleLineEditView(RowView[AnyFormItems]):
    label_view: LabelView[AnyFormItems] = field(
        init=False, default_factory=LabelView[AnyFormItems]
    )
    field_view: DoubleLineEditView[AnyFormItems] = field(
        init=False, default_factory=DoubleLineEditView[AnyFormItems]
    )


@dataclass(eq=False)
class LabelVector3DView(RowView[AnyFormItems]):
    label_view: LabelView[AnyFormItems] = field(
        init=False, default_factory=LabelView[AnyFormItems]
    )
    field_view: Vector3DView[AnyFormItems] = field(
        init=False, default_factory=Vector3DView[AnyFormItems]
    )


@dataclass(eq=False)
class LabelSpinBoxView(RowView[AnyFormItems]):
    label_view: LabelView[AnyFormItems] = field(
        init=False, default_factory=LabelView[AnyFormItems]
    )
    field_view: SpinBoxView[AnyFormItems] = field(
        init=False, default_factory=SpinBoxView[AnyFormItems]
    )


@dataclass(eq=False)
class LabelComboBoxView(RowView[AnyFormItems]):
    label_view: LabelView[AnyFormItems] = field(
        init=False, default_factory=LabelView[AnyFormItems]
    )
    field_view: ComboBoxView[AnyFormItems] = field(
        init=False, default_factory=ComboBoxView[AnyFormItems]
    )


@dataclass(eq=False)
class LabelComboBoxItemsView(RowView[AnyFormItems]):
    label_view: LabelView[AnyFormItems] = field(
        init=False, default_factory=LabelView[AnyFormItems]
    )
    field_view: ComboBoxItemsView[AnyFormItems] = field(
        init=False, default_factory=ComboBoxItemsView[AnyFormItems]
    )


@dataclass(eq=False)
class LabelCheckBoxGroupView(RowView[AnyFormItems]):
    label_view: LabelView[AnyFormItems] = field(
        init=False, default_factory=LabelView[AnyFormItems]
    )
    field_view: CheckBoxGroupView[AnyFormItems] = field(
        init=False, default_factory=CheckBoxGroupView[AnyFormItems]
    )


@dataclass(eq=False)
class LabelRadioButtonGroupView(RowView[AnyFormItems]):
    label_view: LabelView[AnyFormItems] = field(
        init=False, default_factory=LabelView[AnyFormItems]
    )
    field_view: RadioButtonGroupView[AnyFormItems] = field(
        init=False, default_factory=RadioButtonGroupView[AnyFormItems]
    )


@dataclass(eq=False)
class LabelSelectFileView(RowView[AnyFormItems]):
    label_view: LabelView[AnyFormItems] = field(
        init=False, default_factory=LabelView[AnyFormItems]
    )
    field_view: SelectFileView[AnyFormItems] = field(
        init=False, default_factory=SelectFileView[AnyFormItems]
    )


# Checkbox - Field View


@dataclass(eq=False)
class CheckBoxLabelView(RowView[AnyFormItems]):
    label_view: CheckBoxView[AnyFormItems] = field(
        init=False, default_factory=CheckBoxView[AnyFormItems]
    )
    field_view: LabelView[AnyFormItems] = field(
        init=False, default_factory=LabelView[AnyFormItems]
    )


@dataclass(eq=False)
class CheckBoxCheckBoxView(RowView[AnyFormItems]):
    label_view: CheckBoxView[AnyFormItems] = field(
        init=False, default_factory=CheckBoxView[AnyFormItems]
    )
    field_view: CheckBoxView[AnyFormItems] = field(
        init=False, default_factory=CheckBoxView[AnyFormItems]
    )


@dataclass(eq=False)
class CheckBoxLineEditView(RowView[AnyFormItems]):
    label_view: CheckBoxView[AnyFormItems] = field(
        init=False, default_factory=CheckBoxView[AnyFormItems]
    )
    field_view: LineEditView[AnyFormItems] = field(
        init=False, default_factory=LineEditView[AnyFormItems]
    )


@dataclass(eq=False)
class CheckBoxTextEditView(RowView[AnyFormItems]):
    label_view: CheckBoxView[AnyFormItems] = field(
        init=False, default_factory=CheckBoxView[AnyFormItems]
    )
    field_view: TextEditView[AnyFormItems] = field(
        init=False, default_factory=TextEditView[AnyFormItems]
    )


@dataclass(eq=False)
class CheckBoxDoubleLineEditView(RowView[AnyFormItems]):
    label_view: CheckBoxView[AnyFormItems] = field(
        init=False, default_factory=CheckBoxView[AnyFormItems]
    )
    field_view: DoubleLineEditView[AnyFormItems] = field(
        init=False, default_factory=DoubleLineEditView[AnyFormItems]
    )


@dataclass(eq=False)
class CheckBoxVector3DView(RowView[AnyFormItems]):
    label_view: CheckBoxView[AnyFormItems] = field(
        init=False, default_factory=CheckBoxView[AnyFormItems]
    )
    field_view: Vector3DView[AnyFormItems] = field(
        init=False, default_factory=Vector3DView[AnyFormItems]
    )


@dataclass(eq=False)
class CheckBoxSpinBoxView(RowView[AnyFormItems]):
    label_view: CheckBoxView[AnyFormItems] = field(
        init=False, default_factory=CheckBoxView[AnyFormItems]
    )
    field_view: SpinBoxView[AnyFormItems] = field(
        init=False, default_factory=SpinBoxView[AnyFormItems]
    )


@dataclass(eq=False)
class CheckBoxComboBoxView(RowView[AnyFormItems]):
    label_view: CheckBoxView[AnyFormItems] = field(
        init=False, default_factory=CheckBoxView[AnyFormItems]
    )
    field_view: ComboBoxView[AnyFormItems] = field(
        init=False, default_factory=ComboBoxView[AnyFormItems]
    )


@dataclass(eq=False)
class CheckBoxComboBoxItemsView(RowView[AnyFormItems]):
    label_view: CheckBoxView[AnyFormItems] = field(
        init=False, default_factory=CheckBoxView[AnyFormItems]
    )
    field_view: ComboBoxItemsView[AnyFormItems] = field(
        init=False, default_factory=ComboBoxItemsView[AnyFormItems]
    )


@dataclass(eq=False)
class CheckBoxButtonsGroupView(RowView[AnyFormItems]):
    label_view: CheckBoxView[AnyFormItems] = field(
        init=False, default_factory=CheckBoxView[AnyFormItems]
    )
    field_view: ButtonsGroupView[AnyFormItems] = field(
        init=False, default_factory=ButtonsGroupView[AnyFormItems]
    )


@dataclass(eq=False)
class CheckBoxCheckBoxGroupView(RowView[AnyFormItems]):
    label_view: CheckBoxView[AnyFormItems] = field(
        init=False, default_factory=CheckBoxView[AnyFormItems]
    )
    field_view: CheckBoxGroupView[AnyFormItems] = field(
        init=False, default_factory=CheckBoxGroupView[AnyFormItems]
    )


@dataclass(eq=False)
class CheckBoxRadioButtonGroupView(RowView[AnyFormItems]):
    label_view: CheckBoxView[AnyFormItems] = field(
        init=False, default_factory=CheckBoxView[AnyFormItems]
    )
    field_view: RadioButtonGroupView[AnyFormItems] = field(
        init=False, default_factory=RadioButtonGroupView[AnyFormItems]
    )


@dataclass(eq=False)
class CheckBoxSelectFileView(RowView[AnyFormItems]):
    label_view: CheckBoxView[AnyFormItems] = field(
        init=False, default_factory=CheckBoxView[AnyFormItems]
    )
    field_view: SelectFileView[AnyFormItems] = field(
        init=False, default_factory=SelectFileView[AnyFormItems]
    )


# NoLabel - Field View


@dataclass(eq=False)
class NoLabelLabelView(RowView[AnyFormItems]):
    label_view: NoLabelView[AnyFormItems] = field(
        init=False, default_factory=NoLabelView[AnyFormItems]
    )
    field_view: LabelView[AnyFormItems] = field(
        init=False, default_factory=LabelView[AnyFormItems]
    )


@dataclass(eq=False)
class NoLabelCheckBoxView(RowView[AnyFormItems]):
    label_view: NoLabelView[AnyFormItems] = field(
        init=False, default_factory=NoLabelView[AnyFormItems]
    )
    field_view: CheckBoxView[AnyFormItems] = field(
        init=False, default_factory=CheckBoxView[AnyFormItems]
    )


@dataclass(eq=False)
class NoLabelLineEditView(RowView[AnyFormItems]):
    label_view: NoLabelView[AnyFormItems] = field(
        init=False, default_factory=NoLabelView[AnyFormItems]
    )
    field_view: LineEditView[AnyFormItems] = field(
        init=False, default_factory=LineEditView[AnyFormItems]
    )


@dataclass(eq=False)
class NoLabelTextEditView(RowView[AnyFormItems]):
    label_view: NoLabelView[AnyFormItems] = field(
        init=False, default_factory=NoLabelView[AnyFormItems]
    )
    field_view: TextEditView[AnyFormItems] = field(
        init=False, default_factory=TextEditView[AnyFormItems]
    )


@dataclass(eq=False)
class NoLabelDoubleLineEditView(RowView[AnyFormItems]):
    label_view: NoLabelView[AnyFormItems] = field(
        init=False, default_factory=NoLabelView[AnyFormItems]
    )
    field_view: DoubleLineEditView[AnyFormItems] = field(
        init=False, default_factory=DoubleLineEditView[AnyFormItems]
    )


@dataclass(eq=False)
class NoLabelVector3DView(RowView[AnyFormItems]):
    label_view: NoLabelView[AnyFormItems] = field(
        init=False, default_factory=NoLabelView[AnyFormItems]
    )
    field_view: Vector3DView[AnyFormItems] = field(
        init=False, default_factory=Vector3DView[AnyFormItems]
    )


@dataclass(eq=False)
class NoLabelSpinBoxView(RowView[AnyFormItems]):
    label_view: NoLabelView[AnyFormItems] = field(
        init=False, default_factory=NoLabelView[AnyFormItems]
    )
    field_view: SpinBoxView[AnyFormItems] = field(
        init=False, default_factory=SpinBoxView[AnyFormItems]
    )


@dataclass(eq=False)
class NoLabelComboBoxView(RowView[AnyFormItems]):
    label_view: NoLabelView[AnyFormItems] = field(
        init=False, default_factory=NoLabelView[AnyFormItems]
    )
    field_view: ComboBoxView[AnyFormItems] = field(
        init=False, default_factory=ComboBoxView[AnyFormItems]
    )


@dataclass(eq=False)
class NoLabelComboBoxItemsView(RowView[AnyFormItems]):
    label_view: NoLabelView[AnyFormItems] = field(
        init=False, default_factory=NoLabelView[AnyFormItems]
    )
    field_view: ComboBoxItemsView[AnyFormItems] = field(
        init=False, default_factory=ComboBoxItemsView[AnyFormItems]
    )


@dataclass(eq=False)
class NoLabelCheckBoxGroupView(RowView[AnyFormItems]):
    label_view: NoLabelView[AnyFormItems] = field(
        init=False, default_factory=NoLabelView[AnyFormItems]
    )
    field_view: CheckBoxGroupView[AnyFormItems] = field(
        init=False, default_factory=CheckBoxGroupView[AnyFormItems]
    )


@dataclass(eq=False)
class NoLabelRadioButtonGroupView(RowView[AnyFormItems]):
    label_view: NoLabelView[AnyFormItems] = field(
        init=False, default_factory=NoLabelView[AnyFormItems]
    )
    field_view: RadioButtonGroupView[AnyFormItems] = field(
        init=False, default_factory=RadioButtonGroupView[AnyFormItems]
    )


@dataclass(eq=False)
class NoLabelSelectFileView(RowView[AnyFormItems]):
    label_view: NoLabelView[AnyFormItems] = field(
        init=False, default_factory=NoLabelView[AnyFormItems]
    )
    field_view: SelectFileView[AnyFormItems] = field(
        init=False, default_factory=SelectFileView[AnyFormItems]
    )

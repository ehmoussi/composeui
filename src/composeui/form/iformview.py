from composeui.commontypes import AnyFormItems
from composeui.core.basesignal import BaseSignal
from composeui.core.views.ipendingview import IPendingView
from composeui.core.views.iselectpathview import FileMode
from composeui.core.views.iview import IView
from composeui.form.abstractcomboboxitems import AbstractComboboxItems

from typing_extensions import OrderedDict

import enum
from dataclasses import dataclass, field
from typing import Any, Generic, Optional, Tuple, TypeVar, Union


@dataclass(eq=False)
class IRowItemView(IView, Generic[AnyFormItems]):
    parent_fields: Tuple[str, ...] = field(init=False, default_factory=tuple)
    field_name: str = field(init=False, default="")
    is_label: bool = field(init=False, default=False)
    items: Optional[AnyFormItems] = field(init=False, default=None)
    color: Optional[Tuple[int, int, int]] = field(init=False, default=None)


@dataclass(eq=False)
class INoLabelView(IRowItemView[AnyFormItems]): ...


@dataclass(eq=False)
class ILabelView(IRowItemView[AnyFormItems]):
    text: str = field(init=False, default="")


@dataclass(eq=False)
class ICheckBoxView(IRowItemView[AnyFormItems]):
    text: str = field(init=False, default="")
    is_checked: bool = field(init=False, default=False)
    status_changed: BaseSignal = field(init=False, default=BaseSignal())

    def update(self) -> None:
        """Update the status of the checkbox label."""
        if self.items is not None:
            self.items.update(self.field_name, self.parent_fields, self.is_label)
        super().update()


@dataclass(eq=False)
class IEditView(IRowItemView[AnyFormItems]):
    editing_finished: BaseSignal = field(init=False, default=BaseSignal())
    text_edited: BaseSignal = field(init=False, default=BaseSignal())
    text_changed: BaseSignal = field(init=False, default=BaseSignal())

    def update(self) -> None:
        """Update the lineedit according to the items."""
        if self.items is not None:
            self.items.update(self.field_name, self.parent_fields, self.is_label)
        super().update()


@dataclass(eq=False)
class ILineEditView(IEditView[AnyFormItems]):
    text: str = field(init=False, default="")


class TextEditType(enum.Enum):
    PLAINTEXT = enum.auto()
    HTML = enum.auto()
    MARKDOWN = enum.auto()


@dataclass(eq=False)
class ITextEditView(IRowItemView[AnyFormItems]):
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
class IDoubleLineEditView(IEditView[AnyFormItems]):
    value: Optional[float] = field(init=False, default=None)
    minimum: float = field(init=False, default=0.0)
    maximum: float = field(init=False, default=0.0)
    decimals: int = field(init=False, default=0)


@dataclass(eq=False)
class IVector3DView(IRowItemView[AnyFormItems]):
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
class ISpinBoxView(IRowItemView[AnyFormItems]):
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
class IComboBoxView(IRowItemView[AnyFormItems]):
    values: OrderedDict[Any, str] = field(init=False, default_factory=OrderedDict)
    current_index: int = field(init=False, default=0)
    current_index_changed: BaseSignal = field(init=False, default=BaseSignal())

    def update(self) -> None:
        """Update the view with the items."""
        if self.items is not None:
            self.items.update(self.field_name, self.parent_fields, self.is_label)
        super().update()


@dataclass(eq=False)
class IComboBoxItemsView(IRowItemView[AnyFormItems], IPendingView):
    pending_until_visible: bool = field(init=False, default=False)
    combobox_items: Optional[AbstractComboboxItems] = field(init=False, default=None)
    current_index: int = field(init=False, default=0)
    current_index_changed: BaseSignal = field(init=False, default=BaseSignal())


@dataclass(eq=False)
class IButtonsGroupView(IRowItemView[AnyFormItems]):
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
class ICheckBoxGroupView(IButtonsGroupView[AnyFormItems]): ...


@dataclass(eq=False)
class IRadioButtonGroupView(IButtonsGroupView[AnyFormItems]): ...


@dataclass(eq=False)
class ISelectFileView(ILineEditView[AnyFormItems]):
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


L = TypeVar("L", bound=IRowItemView[Any])
F = TypeVar("F", bound=IRowItemView[Any])


@dataclass(eq=False)
class IRowView(IView, Generic[AnyFormItems]):
    parent_fields: Tuple[str, ...] = field(init=False, default_factory=tuple)
    field_name: str = field(init=False, default="")
    items: Optional[AnyFormItems] = field(init=False, default=None)
    label_view: IRowItemView[AnyFormItems] = field(init=False)
    field_view: IRowItemView[AnyFormItems] = field(init=False)

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
class IFormView(IView, Generic[AnyFormItems]):
    parent_fields: Tuple[str, ...] = field(init=False, default_factory=tuple)
    field_name: str = field(init=False, default="")
    items: Optional[AnyFormItems] = field(init=False, default=None)
    infos: str = field(init=False, default="")
    field_changed: BaseSignal = field(init=False, default=BaseSignal())


@dataclass(eq=False)
class IApplyFormView(IFormView[AnyFormItems]):
    validate_before_apply: bool = field(init=False, default=False)
    apply_clicked: BaseSignal = field(init=False, default=BaseSignal())


@dataclass(eq=False)
class IGroupBoxFormView(IFormView[AnyFormItems]):  # TODO: use IGroupView instead
    title: str = field(init=False, default="")
    is_checkable: bool = field(init=False, default=False)
    is_checked: bool = field(init=False, default=False)


@dataclass(eq=False)
class IGroupBoxApplyFormView(IApplyFormView[AnyFormItems]):
    title: str = field(init=False, default="")
    is_checkable: bool = field(init=False, default=False)
    is_checked: bool = field(init=False, default=False)


IRowItemValueView = Union[IDoubleLineEditView[AnyFormItems], ISpinBoxView[AnyFormItems]]
IRowItemTextView = Union[
    ILabelView[AnyFormItems],
    ICheckBoxView[AnyFormItems],
    ILineEditView[AnyFormItems],
    ITextEditView[AnyFormItems],
    ISelectFileView[AnyFormItems],
]
IRowItemIndexView = Union[
    IComboBoxView[AnyFormItems],
    IComboBoxItemsView[AnyFormItems],
    IButtonsGroupView[AnyFormItems],
]


AnyRowItemView = TypeVar("AnyRowItemView", bound=IRowItemView[Any])


# Label - Field View
@dataclass(eq=False)
class ILabelLabelView(IRowView[AnyFormItems]):
    label_view: ILabelView[AnyFormItems] = field(
        init=False, default_factory=ILabelView[AnyFormItems]
    )
    field_view: ILabelView[AnyFormItems] = field(
        init=False, default_factory=ILabelView[AnyFormItems]
    )


@dataclass(eq=False)
class ILabelCheckBoxView(IRowView[AnyFormItems]):
    label_view: ILabelView[AnyFormItems] = field(
        init=False, default_factory=ILabelView[AnyFormItems]
    )
    field_view: ICheckBoxView[AnyFormItems] = field(
        init=False, default_factory=ICheckBoxView[AnyFormItems]
    )


@dataclass(eq=False)
class ILabelLineEditView(IRowView[AnyFormItems]):
    label_view: ILabelView[AnyFormItems] = field(
        init=False, default_factory=ILabelView[AnyFormItems]
    )
    field_view: ILineEditView[AnyFormItems] = field(
        init=False, default_factory=ILineEditView[AnyFormItems]
    )


@dataclass(eq=False)
class ILabelTextEditView(IRowView[AnyFormItems]):
    label_view: ILabelView[AnyFormItems] = field(
        init=False, default_factory=ILabelView[AnyFormItems]
    )
    field_view: ITextEditView[AnyFormItems] = field(
        init=False, default_factory=ITextEditView[AnyFormItems]
    )


@dataclass(eq=False)
class ILabelDoubleLineEditView(IRowView[AnyFormItems]):
    label_view: ILabelView[AnyFormItems] = field(
        init=False, default_factory=ILabelView[AnyFormItems]
    )
    field_view: IDoubleLineEditView[AnyFormItems] = field(
        init=False, default_factory=IDoubleLineEditView[AnyFormItems]
    )


@dataclass(eq=False)
class ILabelVector3DView(IRowView[AnyFormItems]):
    label_view: ILabelView[AnyFormItems] = field(
        init=False, default_factory=ILabelView[AnyFormItems]
    )
    field_view: IVector3DView[AnyFormItems] = field(
        init=False, default_factory=IVector3DView[AnyFormItems]
    )


@dataclass(eq=False)
class ILabelSpinBoxView(IRowView[AnyFormItems]):
    label_view: ILabelView[AnyFormItems] = field(
        init=False, default_factory=ILabelView[AnyFormItems]
    )
    field_view: ISpinBoxView[AnyFormItems] = field(
        init=False, default_factory=ISpinBoxView[AnyFormItems]
    )


@dataclass(eq=False)
class ILabelComboBoxView(IRowView[AnyFormItems]):
    label_view: ILabelView[AnyFormItems] = field(
        init=False, default_factory=ILabelView[AnyFormItems]
    )
    field_view: IComboBoxView[AnyFormItems] = field(
        init=False, default_factory=IComboBoxView[AnyFormItems]
    )


@dataclass(eq=False)
class ILabelComboBoxItemsView(IRowView[AnyFormItems]):
    label_view: ILabelView[AnyFormItems] = field(
        init=False, default_factory=ILabelView[AnyFormItems]
    )
    field_view: IComboBoxItemsView[AnyFormItems] = field(
        init=False, default_factory=IComboBoxItemsView[AnyFormItems]
    )


@dataclass(eq=False)
class ILabelCheckBoxGroupView(IRowView[AnyFormItems]):
    label_view: ILabelView[AnyFormItems] = field(
        init=False, default_factory=ILabelView[AnyFormItems]
    )
    field_view: ICheckBoxGroupView[AnyFormItems] = field(
        init=False, default_factory=ICheckBoxGroupView[AnyFormItems]
    )


@dataclass(eq=False)
class ILabelRadioButtonGroupView(IRowView[AnyFormItems]):
    label_view: ILabelView[AnyFormItems] = field(
        init=False, default_factory=ILabelView[AnyFormItems]
    )
    field_view: IRadioButtonGroupView[AnyFormItems] = field(
        init=False, default_factory=IRadioButtonGroupView[AnyFormItems]
    )


@dataclass(eq=False)
class ILabelSelectFileView(IRowView[AnyFormItems]):
    label_view: ILabelView[AnyFormItems] = field(
        init=False, default_factory=ILabelView[AnyFormItems]
    )
    field_view: ISelectFileView[AnyFormItems] = field(
        init=False, default_factory=ISelectFileView[AnyFormItems]
    )


# Checkbox - Field View


@dataclass(eq=False)
class ICheckBoxLabelView(IRowView[AnyFormItems]):
    label_view: ICheckBoxView[AnyFormItems] = field(
        init=False, default_factory=ICheckBoxView[AnyFormItems]
    )
    field_view: ILabelView[AnyFormItems] = field(
        init=False, default_factory=ILabelView[AnyFormItems]
    )


@dataclass(eq=False)
class ICheckBoxCheckBoxView(IRowView[AnyFormItems]):
    label_view: ICheckBoxView[AnyFormItems] = field(
        init=False, default_factory=ICheckBoxView[AnyFormItems]
    )
    field_view: ICheckBoxView[AnyFormItems] = field(
        init=False, default_factory=ICheckBoxView[AnyFormItems]
    )


@dataclass(eq=False)
class ICheckBoxLineEditView(IRowView[AnyFormItems]):
    label_view: ICheckBoxView[AnyFormItems] = field(
        init=False, default_factory=ICheckBoxView[AnyFormItems]
    )
    field_view: ILineEditView[AnyFormItems] = field(
        init=False, default_factory=ILineEditView[AnyFormItems]
    )


@dataclass(eq=False)
class ICheckBoxTextEditView(IRowView[AnyFormItems]):
    label_view: ICheckBoxView[AnyFormItems] = field(
        init=False, default_factory=ICheckBoxView[AnyFormItems]
    )
    field_view: ITextEditView[AnyFormItems] = field(
        init=False, default_factory=ITextEditView[AnyFormItems]
    )


@dataclass(eq=False)
class ICheckBoxDoubleLineEditView(IRowView[AnyFormItems]):
    label_view: ICheckBoxView[AnyFormItems] = field(
        init=False, default_factory=ICheckBoxView[AnyFormItems]
    )
    field_view: IDoubleLineEditView[AnyFormItems] = field(
        init=False, default_factory=IDoubleLineEditView[AnyFormItems]
    )


@dataclass(eq=False)
class ICheckBoxVector3DView(IRowView[AnyFormItems]):
    label_view: ICheckBoxView[AnyFormItems] = field(
        init=False, default_factory=ICheckBoxView[AnyFormItems]
    )
    field_view: IVector3DView[AnyFormItems] = field(
        init=False, default_factory=IVector3DView[AnyFormItems]
    )


@dataclass(eq=False)
class ICheckBoxSpinBoxView(IRowView[AnyFormItems]):
    label_view: ICheckBoxView[AnyFormItems] = field(
        init=False, default_factory=ICheckBoxView[AnyFormItems]
    )
    field_view: ISpinBoxView[AnyFormItems] = field(
        init=False, default_factory=ISpinBoxView[AnyFormItems]
    )


@dataclass(eq=False)
class ICheckBoxComboBoxView(IRowView[AnyFormItems]):
    label_view: ICheckBoxView[AnyFormItems] = field(
        init=False, default_factory=ICheckBoxView[AnyFormItems]
    )
    field_view: IComboBoxView[AnyFormItems] = field(
        init=False, default_factory=IComboBoxView[AnyFormItems]
    )


@dataclass(eq=False)
class ICheckBoxComboBoxItemsView(IRowView[AnyFormItems]):
    label_view: ICheckBoxView[AnyFormItems] = field(
        init=False, default_factory=ICheckBoxView[AnyFormItems]
    )
    field_view: IComboBoxItemsView[AnyFormItems] = field(
        init=False, default_factory=IComboBoxItemsView[AnyFormItems]
    )


@dataclass(eq=False)
class ICheckBoxButtonsGroupView(IRowView[AnyFormItems]):
    label_view: ICheckBoxView[AnyFormItems] = field(
        init=False, default_factory=ICheckBoxView[AnyFormItems]
    )
    field_view: IButtonsGroupView[AnyFormItems] = field(
        init=False, default_factory=IButtonsGroupView[AnyFormItems]
    )


@dataclass(eq=False)
class ICheckBoxCheckBoxGroupView(IRowView[AnyFormItems]):
    label_view: ICheckBoxView[AnyFormItems] = field(
        init=False, default_factory=ICheckBoxView[AnyFormItems]
    )
    field_view: ICheckBoxGroupView[AnyFormItems] = field(
        init=False, default_factory=ICheckBoxGroupView[AnyFormItems]
    )


@dataclass(eq=False)
class ICheckBoxRadioButtonGroupView(IRowView[AnyFormItems]):
    label_view: ICheckBoxView[AnyFormItems] = field(
        init=False, default_factory=ICheckBoxView[AnyFormItems]
    )
    field_view: IRadioButtonGroupView[AnyFormItems] = field(
        init=False, default_factory=IRadioButtonGroupView[AnyFormItems]
    )


@dataclass(eq=False)
class ICheckBoxSelectFileView(IRowView[AnyFormItems]):
    label_view: ICheckBoxView[AnyFormItems] = field(
        init=False, default_factory=ICheckBoxView[AnyFormItems]
    )
    field_view: ISelectFileView[AnyFormItems] = field(
        init=False, default_factory=ISelectFileView[AnyFormItems]
    )


# NoLabel - Field View


@dataclass(eq=False)
class INoLabelLabelView(IRowView[AnyFormItems]):
    label_view: INoLabelView[AnyFormItems] = field(
        init=False, default_factory=INoLabelView[AnyFormItems]
    )
    field_view: ILabelView[AnyFormItems] = field(
        init=False, default_factory=ILabelView[AnyFormItems]
    )


@dataclass(eq=False)
class INoLabelCheckBoxView(IRowView[AnyFormItems]):
    label_view: INoLabelView[AnyFormItems] = field(
        init=False, default_factory=INoLabelView[AnyFormItems]
    )
    field_view: ICheckBoxView[AnyFormItems] = field(
        init=False, default_factory=ICheckBoxView[AnyFormItems]
    )


@dataclass(eq=False)
class INoLabelLineEditView(IRowView[AnyFormItems]):
    label_view: INoLabelView[AnyFormItems] = field(
        init=False, default_factory=INoLabelView[AnyFormItems]
    )
    field_view: ILineEditView[AnyFormItems] = field(
        init=False, default_factory=ILineEditView[AnyFormItems]
    )


@dataclass(eq=False)
class INoLabelTextEditView(IRowView[AnyFormItems]):
    label_view: INoLabelView[AnyFormItems] = field(
        init=False, default_factory=INoLabelView[AnyFormItems]
    )
    field_view: ITextEditView[AnyFormItems] = field(
        init=False, default_factory=ITextEditView[AnyFormItems]
    )


@dataclass(eq=False)
class INoLabelDoubleLineEditView(IRowView[AnyFormItems]):
    label_view: INoLabelView[AnyFormItems] = field(
        init=False, default_factory=INoLabelView[AnyFormItems]
    )
    field_view: IDoubleLineEditView[AnyFormItems] = field(
        init=False, default_factory=IDoubleLineEditView[AnyFormItems]
    )


@dataclass(eq=False)
class INoLabelVector3DView(IRowView[AnyFormItems]):
    label_view: INoLabelView[AnyFormItems] = field(
        init=False, default_factory=INoLabelView[AnyFormItems]
    )
    field_view: IVector3DView[AnyFormItems] = field(
        init=False, default_factory=IVector3DView[AnyFormItems]
    )


@dataclass(eq=False)
class INoLabelSpinBoxView(IRowView[AnyFormItems]):
    label_view: INoLabelView[AnyFormItems] = field(
        init=False, default_factory=INoLabelView[AnyFormItems]
    )
    field_view: ISpinBoxView[AnyFormItems] = field(
        init=False, default_factory=ISpinBoxView[AnyFormItems]
    )


@dataclass(eq=False)
class INoLabelComboBoxView(IRowView[AnyFormItems]):
    label_view: INoLabelView[AnyFormItems] = field(
        init=False, default_factory=INoLabelView[AnyFormItems]
    )
    field_view: IComboBoxView[AnyFormItems] = field(
        init=False, default_factory=IComboBoxView[AnyFormItems]
    )


@dataclass(eq=False)
class INoLabelComboBoxItemsView(IRowView[AnyFormItems]):
    label_view: INoLabelView[AnyFormItems] = field(
        init=False, default_factory=INoLabelView[AnyFormItems]
    )
    field_view: IComboBoxItemsView[AnyFormItems] = field(
        init=False, default_factory=IComboBoxItemsView[AnyFormItems]
    )


@dataclass(eq=False)
class INoLabelCheckBoxGroupView(IRowView[AnyFormItems]):
    label_view: INoLabelView[AnyFormItems] = field(
        init=False, default_factory=INoLabelView[AnyFormItems]
    )
    field_view: ICheckBoxGroupView[AnyFormItems] = field(
        init=False, default_factory=ICheckBoxGroupView[AnyFormItems]
    )


@dataclass(eq=False)
class INoLabelRadioButtonGroupView(IRowView[AnyFormItems]):
    label_view: INoLabelView[AnyFormItems] = field(
        init=False, default_factory=INoLabelView[AnyFormItems]
    )
    field_view: IRadioButtonGroupView[AnyFormItems] = field(
        init=False, default_factory=IRadioButtonGroupView[AnyFormItems]
    )


@dataclass(eq=False)
class INoLabelSelectFileView(IRowView[AnyFormItems]):
    label_view: INoLabelView[AnyFormItems] = field(
        init=False, default_factory=INoLabelView[AnyFormItems]
    )
    field_view: ISelectFileView[AnyFormItems] = field(
        init=False, default_factory=ISelectFileView[AnyFormItems]
    )

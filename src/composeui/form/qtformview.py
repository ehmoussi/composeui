"""Form View."""

from composeui.commontypes import AnyFormItems
from composeui.core.basesignal import BaseSignal
from composeui.core.pendingupdate import pending_until_visible
from composeui.core.qt.qtview import QtView
from composeui.core.qt.widgets.widget import ComboBox
from composeui.form.abstractcomboboxitems import AbstractComboboxItems
from composeui.form.comboboxitemmodel import ComboBoxItemModel
from composeui.form.formvalidators import FormDoubleValidator, FormVector3DValidator
from composeui.form.formview import (  # IFormView,; IGroupBoxFormView,
    ApplyFormView,
    ButtonsGroupView,
    CheckBoxGroupView,
    CheckBoxView,
    ComboBoxItemsView,
    ComboBoxView,
    DoubleLineEditView,
    EditView,
    FormView,
    GroupBoxApplyFormView,
    GroupBoxFormView,
    LabelView,
    LineEditView,
    NoLabelView,
    RadioButtonGroupView,
    RowItemView,
    RowView,
    SelectFileView,
    SpinBoxView,
    TextEditType,
    TextEditView,
    Vector3DView,
)

from qtpy.QtGui import QColor, QTextCursor
from qtpy.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from typing_extensions import OrderedDict

from dataclasses import dataclass, field, fields, make_dataclass
from enum import Enum
from typing import Any, List, Optional, Tuple, Type, Union


@dataclass(eq=False)
class QtRowItemView(QtView, RowItemView[AnyFormItems]):

    view: Optional[QWidget] = field(init=False, repr=False, default=None)
    _color: Optional[Tuple[int, int, int]] = field(init=False, repr=False, default=None)

    def __post_init__(self) -> None:
        super().__post_init__()
        self._field_name = ""
        self.is_label = False
        self._color: Optional[Tuple[int, int, int]] = None

    @property  # type: ignore[misc]
    def color(self) -> Optional[Tuple[int, int, int]]:
        return self._color

    @color.setter
    def color(self, color: Optional[Tuple[int, int, int]]) -> None:
        self._color = color
        if self.view is not None and isinstance(self.view, (QLineEdit, QSpinBox, QComboBox)):
            if color is None:
                self.view.setStyleSheet("")
            else:
                self.view.setStyleSheet(
                    f"border:1px solid rgb({color[0]}, {color[1]}, {color[2]});"
                )


@dataclass(eq=False)
class QtNoLabelView(QtRowItemView[AnyFormItems], NoLabelView[AnyFormItems]): ...


@dataclass(eq=False)
class QtLabelView(QtRowItemView[AnyFormItems], LabelView[AnyFormItems]):
    view: QLabel = field(init=False, repr=False, default_factory=QLabel)

    @property  # type: ignore[misc]
    def text(self) -> str:
        return str(self.view.text())

    @text.setter
    def text(self, text: str) -> None:
        self.view.setText(text)


@dataclass(eq=False)
class QtCheckBoxView(QtRowItemView[AnyFormItems], CheckBoxView[AnyFormItems]):
    view: QCheckBox = field(init=False, repr=False, default_factory=QCheckBox)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.status_changed.add_qt_signals((self.view, self.view.clicked))

    @property  # type:ignore[misc]
    def text(self) -> str:
        return self.view.text()

    @text.setter
    def text(self, text: str) -> None:
        self.view.setText(text)

    @property  # type:ignore[misc]
    def is_checked(self) -> bool:
        return self.view.isChecked()

    @is_checked.setter
    def is_checked(self, is_checked: bool) -> None:
        self.view.setChecked(is_checked)


@dataclass(eq=False)
class _QtEditView(QtRowItemView[AnyFormItems], EditView[AnyFormItems]):
    view: QLineEdit = field(init=False, repr=False, default_factory=QLineEdit)

    def __post_init__(self) -> None:
        super().__post_init__()
        # assign signals
        self.editing_finished.add_qt_signals((self.view, self.view.editingFinished))
        self.text_edited.add_qt_signals((self.view, self.view.textEdited))
        self.text_changed.add_qt_signals((self.view, self.view.textChanged))


@dataclass(eq=False)
class QtLineEditView(_QtEditView[AnyFormItems], LineEditView[AnyFormItems]):

    @property  # type:ignore[misc]
    def text(self) -> str:
        return self.view.text()

    @text.setter
    def text(self, text: str) -> None:
        self.view.setText(text)


@dataclass(eq=False)
class QtTextEditView(QtRowItemView[AnyFormItems], TextEditView[AnyFormItems]):
    view: QTextEdit = field(init=False, repr=False, default_factory=QTextEdit)

    def __post_init__(self) -> None:
        super().__post_init__()
        # assign signals
        self.cursor_position_changed.add_qt_signals(
            (self.view, self.view.cursorPositionChanged)
        )
        self.selection_changed.add_qt_signals((self.view, self.view.selectionChanged))
        self.text_changed.add_qt_signals((self.view, self.view.textChanged))

    @property  # type:ignore[misc]
    def text(self) -> str:
        if self.text_type == TextEditType.HTML:
            return self.view.toHtml()
        elif self.text_type == TextEditType.MARKDOWN:
            return self.view.toMarkdown()
        else:
            return self.view.toPlainText()

    @text.setter
    def text(self, text: str) -> None:
        if self.text_type == TextEditType.HTML:
            self.view.setHtml(text)
        elif self.text_type == TextEditType.MARKDOWN:
            self.view.setMarkdown(text)
        else:
            self.view.setPlainText(text)

    @property  # type:ignore[misc]
    def text_color(self) -> Tuple[int, int, int, int]:
        color = self.view.textColor()
        return (color.red(), color.green(), color.blue(), color.alpha())

    @text_color.setter
    def text_color(self, color: Tuple[int, int, int, int]) -> None:
        self.view.setTextColor(QColor(*color))

    @property  # type:ignore[misc]
    def text_background_color(self) -> Tuple[int, int, int, int]:
        color = self.view.textBackgroundColor()
        return (color.red(), color.green(), color.blue(), color.alpha())

    @text_background_color.setter
    def text_background_color(self, color: Tuple[int, int, int, int]) -> None:
        self.view.setTextBackgroundColor(QColor(*color))

    @property  # type:ignore[misc]
    def is_read_only(self) -> bool:
        return self.view.isReadOnly()

    @is_read_only.setter
    def is_read_only(self, is_read_only: bool) -> None:
        self.view.setReadOnly(is_read_only)

    def append_text(self, text: str) -> None:
        """Append the given text."""
        if self.text_type == TextEditType.HTML:
            self.view.insertHtml(text)
            self.view.moveCursor(QTextCursor.End)
            self.view.ensureCursorVisible()
        else:
            self.view.append(text.rstrip("\n"))


@dataclass(eq=False)
class QtDoubleLineEditView(_QtEditView[AnyFormItems], DoubleLineEditView[AnyFormItems]):
    validator: FormDoubleValidator = field(init=False, repr=False)
    _items: Optional[AnyFormItems] = field(init=False, repr=False, default=None)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.validator = FormDoubleValidator(self)
        self.view.setValidator(self.validator)

    @property  # type: ignore[misc]
    def value(self) -> Optional[float]:
        try:
            value = float(self.view.text())
        except (ValueError, TypeError):
            value = None
        return value

    @value.setter
    def value(self, value: Optional[float]) -> None:
        if value is None:
            self.view.setText("")
        else:
            self.view.setText(str(value))

    @property  # type: ignore[misc]
    def minimum(self) -> float:
        return self.validator.bottom()

    @minimum.setter
    def minimum(self, minimum: float) -> None:
        self.validator.setBottom(minimum)

    @property  # type: ignore[misc]
    def maximum(self) -> float:
        return self.validator.top()

    @maximum.setter
    def maximum(self, maximum: float) -> None:
        self.validator.setTop(maximum)

    @property  # type: ignore[misc]
    def decimals(self) -> int:
        return self.validator.decimals()

    @decimals.setter
    def decimals(self, decimals: int) -> None:
        self.validator.setDecimals(decimals)


@dataclass(eq=False)
class QtVector3DView(QtRowItemView[AnyFormItems], Vector3DView[AnyFormItems]):
    view: QWidget = field(init=False, repr=False)

    line_edit_1: QLineEdit = field(init=False, repr=False)
    validator_1: FormVector3DValidator = field(init=False, repr=False)

    line_edit_2: QLineEdit = field(init=False, repr=False)
    validator_2: FormVector3DValidator = field(init=False, repr=False)

    line_edit_3: QLineEdit = field(init=False, repr=False)
    validator_3: FormVector3DValidator = field(init=False, repr=False)

    _items: Optional[AnyFormItems] = field(init=False, repr=False, default=None)

    def __post_init__(self) -> None:
        self.view = QWidget()
        layout = QHBoxLayout()
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)
        self.view.setLayout(layout)
        # lineedit 1
        self.line_edit_1 = QLineEdit()
        self.validator_1 = FormVector3DValidator(self, 0)
        self.line_edit_1.setValidator(self.validator_1)
        layout.addWidget(self.line_edit_1)
        # lineedit 2
        self.line_edit_2 = QLineEdit()
        self.validator_2 = FormVector3DValidator(self, 1)
        self.line_edit_2.setValidator(self.validator_2)
        layout.addWidget(self.line_edit_2)
        # lineedit 3
        self.line_edit_3 = QLineEdit()
        self.validator_3 = FormVector3DValidator(self, 2)
        self.line_edit_3.setValidator(self.validator_3)
        layout.addWidget(self.line_edit_3)
        self.editing_finished.add_qt_signals(
            (self.line_edit_1, self.line_edit_1.editingFinished),
            (self.line_edit_2, self.line_edit_2.editingFinished),
            (self.line_edit_3, self.line_edit_3.editingFinished),
        )
        self.text_edited.add_qt_signals(
            (self.line_edit_1, self.line_edit_1.textEdited),
            (self.line_edit_2, self.line_edit_2.textEdited),
            (self.line_edit_3, self.line_edit_3.textEdited),
        )
        self.text_changed.add_qt_signals(
            (self.line_edit_1, self.line_edit_1.textChanged),
            (self.line_edit_2, self.line_edit_2.textChanged),
            (self.line_edit_3, self.line_edit_3.textChanged),
        )
        # the instanciation of the values need to be done after creation of the widgets
        super().__post_init__()

    @property  # type: ignore[misc]
    def values(self) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        return (
            self._to_float(self.line_edit_1.text()),
            self._to_float(self.line_edit_2.text()),
            self._to_float(self.line_edit_3.text()),
        )

    @values.setter
    def values(self, values: Tuple[Optional[float], Optional[float], Optional[float]]) -> None:
        for line_edit_name, value in zip(
            ("line_edit_1", "line_edit_2", "line_edit_3"), values
        ):
            # if hasattr(self, line_edit_name):
            line_edit = getattr(self, line_edit_name)
            if value is None:
                line_edit.setText("")
            else:
                line_edit.setText(str(value))

    @property  # type: ignore[misc]
    def minimums(self) -> Tuple[float, float, float]:
        return (
            self.validator_1.bottom(),
            self.validator_2.bottom(),
            self.validator_3.bottom(),
        )

    @minimums.setter
    def minimums(self, minimums: Tuple[float, float, float]) -> None:
        self.validator_1.setBottom(minimums[0])
        self.validator_2.setBottom(minimums[1])
        self.validator_3.setBottom(minimums[2])

    @property  # type: ignore[misc]
    def maximums(self) -> Tuple[float, float, float]:
        return (
            self.validator_1.top(),
            self.validator_2.top(),
            self.validator_3.top(),
        )

    @maximums.setter
    def maximums(self, maximums: Tuple[float, float, float]) -> None:
        self.validator_1.setTop(maximums[0])
        self.validator_2.setTop(maximums[1])
        self.validator_3.setTop(maximums[2])

    @property  # type: ignore[misc]
    def decimals(self) -> Tuple[int, int, int]:
        return (
            self.validator_1.decimals(),
            self.validator_2.decimals(),
            self.validator_3.decimals(),
        )

    @decimals.setter
    def decimals(self, decimals: Tuple[int, int, int]) -> None:
        self.validator_1.setDecimals(decimals[0])
        self.validator_2.setDecimals(decimals[1])
        self.validator_3.setDecimals(decimals[2])

    def _to_float(self, text: str) -> Optional[float]:
        try:
            value = float(text)
        except (ValueError, TypeError):
            value = None
        return value


@dataclass(eq=False)
class QtSpinBoxView(QtRowItemView[AnyFormItems], SpinBoxView[AnyFormItems]):
    view: QSpinBox = field(init=False, repr=False, default_factory=QSpinBox)
    value_changed = BaseSignal()

    def __post_init__(self) -> None:
        super().__post_init__()
        # assign signals
        self.value_changed.add_qt_signals((self.view, self.view.valueChanged))

    @property  # type: ignore[misc]
    def value(self) -> Optional[int]:
        if self.view.text() == "":
            return None
        else:
            return int(self.view.value())

    @value.setter
    def value(self, value: Optional[int]) -> None:
        if value is None:
            self.view.cleanText()
        else:
            self.view.setValue(value)

    @property  # type: ignore[misc]
    def minimum(self) -> int:
        return self.view.minimum()

    @minimum.setter
    def minimum(self, value: int) -> None:
        self.view.setMinimum(value)

    @property  # type: ignore[misc]
    def maximum(self) -> int:
        return self.view.maximum()

    @maximum.setter
    def maximum(self, value: int) -> None:
        self.view.setMaximum(value)

    @property  # type: ignore[misc]
    def step(self) -> int:
        return self.view.singleStep()

    @step.setter
    def step(self, value: int) -> None:
        self.view.setSingleStep(value)


@dataclass(eq=False)
class QtComboBoxView(QtRowItemView[AnyFormItems], ComboBoxView[AnyFormItems]):
    view: QComboBox = field(init=False, repr=False, default_factory=QComboBox)

    def __post_init__(self) -> None:
        super().__post_init__()
        # assign signals
        self.current_index_changed.add_qt_signals((self.view, self.view.currentIndexChanged))

    @property  # type: ignore[misc]
    def values(self) -> OrderedDict[Any, str]:
        return OrderedDict(
            (self.view.itemData(index), self.view.itemText(index))
            for index in range(self.view.count())
        )

    @values.setter
    def values(self, values: OrderedDict[Any, str]) -> None:
        if self.view is not None:
            self.view.clear()
            for data, text in values.items():
                self.view.addItem(text, data)

    @property  # type: ignore[misc]
    def current_index(self) -> int:
        return int(self.view.currentIndex())

    @current_index.setter
    def current_index(self, index: int) -> None:
        self.view.setCurrentIndex(index)


@dataclass(eq=False)
class QtComboBoxItemsView(QtRowItemView[AnyFormItems], ComboBoxItemsView[AnyFormItems]):
    view: ComboBox = field(init=False, repr=False, default_factory=ComboBox)
    _combobox_items: Optional[AbstractComboboxItems] = field(
        init=False, repr=False, default=None
    )

    def __post_init__(self) -> None:
        super().__post_init__()
        # assign signals
        self.current_index_changed.add_qt_signals((self.view, self.view.currentIndexChanged))
        # connect to an internal slot to manage the pending of the update
        self.view.view_visible.connect(self._update_if_pending)

    def _update_if_pending(self) -> None:
        r"""Update the table if an update is pending."""
        if self.is_update_pending:
            self.update()

    @pending_until_visible
    def update(self) -> None:
        """Update the model of the combobox."""
        if self._combobox_items is not None:
            model = self.view.model()
            model.beginResetModel()
            model.endResetModel()
        super().update()

    @property  # type: ignore[misc]
    def combobox_items(self) -> Optional[AbstractComboboxItems]:
        return self._combobox_items

    @combobox_items.setter
    def combobox_items(self, combobox_items: Optional[AbstractComboboxItems]) -> None:
        self._combobox_items = combobox_items
        if combobox_items is not None:
            model = ComboBoxItemModel(combobox_items)
            self.view.setModel(model)
        if self.items is not None:
            if combobox_items is None:
                del self.items.combobox_items[self.field_name]
            else:
                self.items.combobox_items[self.field_name] = combobox_items

    @property  # type: ignore[misc]
    def current_index(self) -> int:
        return self.view.currentIndex()

    @current_index.setter
    def current_index(self, index: int) -> None:
        self.view.setCurrentIndex(index)


class ButtonType(Enum):
    CHECKBOX = 0
    RADIOBUTTON = 1


@dataclass(eq=False)
class QtButtonsGroupView(QtRowItemView[AnyFormItems], ButtonsGroupView[AnyFormItems]):

    view: QWidget = field(init=False, repr=False, default_factory=QWidget)
    button_type: ButtonType
    _group: QButtonGroup = field(init=False, repr=False, default_factory=QButtonGroup)

    def __post_init__(self) -> None:
        super().__post_init__()
        self._layout = QHBoxLayout()
        self._layout.setContentsMargins(0, 0, 0, 0)
        self.view.setLayout(self._layout)
        self._group.setExclusive(True)
        # assign signals
        self.current_index_changed.add_qt_signals((self._group, self._group.buttonClicked))

    @property  # type: ignore[misc]
    def values(self) -> Tuple[str, ...]:
        return tuple(button.text() for button in self._group.buttons())

    @values.setter
    def values(self, values: Tuple[str, ...]) -> None:
        if hasattr(self, "_group"):
            self._adjust_buttons(tuple(values))
            self._set_text_buttons(tuple(values))

    @property  # type: ignore[misc]
    def current_index(self) -> int:
        return self._get_current_index()

    @current_index.setter
    def current_index(self, index: int) -> None:
        self._update_current_index(index)

    @property  # type: ignore[misc]
    def is_exclusive(self) -> bool:
        return self._group.exclusive()

    @is_exclusive.setter
    def is_exclusive(self, is_exclusive: bool) -> None:
        self._group.setExclusive(is_exclusive)

    def _update_current_index(self, index: int) -> None:
        """Update the current index."""
        if self._group.exclusive():
            button = self._group.button(index)
            # .button -> QAbstractButton but it can return None the stubs are wrong
            # TODO: write an issue in github
            if button is None:
                self._group.setExclusive(False)  # type: ignore[unreachable]
                for button in self._group.buttons():
                    button.setChecked(False)
                self._group.setExclusive(True)
            else:
                button.setChecked(True)
        else:
            buttons = self._group.buttons()
            for index_bit, button in zip(
                self._to_binary_digits(index, len(buttons)), reversed(buttons)
            ):
                button.setChecked(bool(index_bit))

    def _to_binary_digits(self, index: int, size: int) -> List[int]:
        """Transform to a list of binary digits to identify wihch buttons are checked."""
        binary_digits = [0] * size
        for i in range(size - 1, -1, -1):
            binary_digits[i] = index & 1
            index >>= 1
            if index == 0:
                break
        return binary_digits

    def _get_current_index(self) -> int:
        if self._group.exclusive():
            return int(self._group.checkedId())
        else:
            # if the group is not exclusive the index correspond to the
            # binary representation of the id of the checked buttons
            # e.g for two buttons
            # "00" -> all are unchecked
            # "01" -> only the first button is checked
            # "10" -> only the second button is checked
            # "11" -> all the buttons are checked
            return sum(
                2 ** self._group.id(button)
                for button in self._group.buttons()
                if button.isChecked()
            )

    def _adjust_buttons(self, values: Tuple[str, ...]) -> None:
        r"""Adjust the number of buttons according to the given list of text."""
        buttons = self._group.buttons()
        nb_current = len(buttons)
        nb_buttons = len(values)
        if nb_current < nb_buttons:
            for index in range(nb_buttons - nb_current):
                new_button = self._create_button()
                self._group.addButton(new_button, id=index)
                self._layout.addWidget(new_button)
        elif nb_current > nb_buttons:
            for index in range(nb_current - 1, nb_buttons - 1, -1):
                button = buttons[index]
                self._layout.removeWidget(button)
                self._group.removeButton(button)
                button.deleteLater()

    def _set_text_buttons(self, values: Tuple[str, ...]) -> None:
        for button, text in zip(self._group.buttons(), values):
            button.setText(text)

    def _create_button(self) -> Union[QCheckBox, QRadioButton]:
        if self.button_type == ButtonType.CHECKBOX:
            return QCheckBox()
        # elif self._button_type == ButtonType.RADIOBUTTON:
        return QRadioButton()


@dataclass(eq=False)
class QtSelectFileView(QtRowItemView[AnyFormItems], SelectFileView[AnyFormItems]):
    view: QWidget = field(init=False, repr=False, default_factory=QWidget)

    text_field: QLineEdit = field(init=False, repr=False, default_factory=QLineEdit)
    button: QPushButton = field(init=False, repr=False, default_factory=QPushButton)

    def __post_init__(self) -> None:
        super().__post_init__()
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        self.view.setLayout(layout)
        # text field
        layout.addWidget(self.text_field)
        # button
        self.button.setText("...")
        layout.addWidget(self.button)
        # signals
        self.editing_finished.add_qt_signals(
            (self.text_field, self.text_field.editingFinished)
        )
        self.text_edited.add_qt_signals((self.text_field, self.text_field.textEdited))
        self.text_changed.add_qt_signals((self.text_field, self.text_field.textChanged))
        self.clicked.add_qt_signals((self.button, self.button.clicked))

    @property  # type: ignore[misc]
    def text(self) -> str:
        return str(self.text_field.text())

    @text.setter
    def text(self, text: str) -> None:
        self.text_field.setText(text)

    @property  # type: ignore[misc]
    def is_text_field_enabled(self) -> bool:
        return self.text_field.isEnabled()

    @is_text_field_enabled.setter
    def is_text_field_enabled(self, is_enabled: bool) -> None:
        self.text_field.setEnabled(is_enabled)

    @property  # type: ignore[misc]
    def is_button_enabled(self) -> bool:
        return self.button.isEnabled()

    @is_button_enabled.setter
    def is_button_enabled(self, is_enabled: bool) -> None:
        self.button.setEnabled(is_enabled)

    @property  # type: ignore[misc]
    def button_text(self) -> str:
        return self.button.text()

    @button_text.setter
    def button_text(self, text: str) -> None:
        self.button.setText(text)


@dataclass(eq=False)
# This view don't inherit from View because it doesn't have one
# And the is_visible/is_enabled are implemented in IRowView
class QtRowView(RowView[AnyFormItems]):
    label_view: QtRowItemView[AnyFormItems] = field(repr=False)
    field_view: QtRowItemView[AnyFormItems] = field(repr=False)


@dataclass(eq=False)
class QtFormView(QtView, FormView[AnyFormItems]):

    view: QWidget = field(init=False, repr=False, default_factory=QWidget)
    form_infos: QLabel = field(init=False, repr=False, default_factory=QLabel)

    def __post_init__(self) -> None:
        self.field_changed.allow_calling = True
        super().__post_init__()
        self.parent_fields = ()
        self.layout = QVBoxLayout()
        self.view.setLayout(self.layout)
        self.form_layout = QFormLayout()
        self.layout.addLayout(self.form_layout)
        # self.layout.addStretch()
        self.form_infos = QLabel()
        self.form_infos.setStyleSheet("color: red")
        self.layout.addWidget(self.form_infos)
        self._add_rows()

    @property  # type: ignore[misc]
    def infos(self) -> str:
        return str(self.form_infos.text())

    @infos.setter
    def infos(self, infos: str) -> None:
        self.form_infos.setText(infos)
        self.form_infos.setVisible(infos != "")

    def add_row(self, row_view: QtRowView[AnyFormItems]) -> None:
        if row_view.label_view.view is not None and row_view.field_view.view is not None:
            self.form_layout.addRow(row_view.label_view.view, row_view.field_view.view)
        elif row_view.field_view.view is not None:
            self.form_layout.addRow(row_view.field_view.view)
        elif row_view.label_view.view is not None:
            self.form_layout.addRow(row_view.label_view.view)

    def add_form(self, form_view: "QtFormView[AnyFormItems]") -> None:
        self.form_layout.addRow(form_view.view)

    def _add_rows(self) -> None:
        for row_field in fields(self):
            irow_view = getattr(self, row_field.name)
            form_view: Union[QtApplyFormView[AnyFormItems], QtFormView[AnyFormItems]]
            if isinstance(irow_view, RowView):
                label_view = self._make_view(irow_view.label_view)
                field_view = self._make_view(irow_view.field_view)
                if label_view is not None and field_view is not None:
                    row_view = QtRowView(label_view, field_view)
                    setattr(self, row_field.name, row_view)
                    self.add_row(row_view)
                else:
                    msg = f"Invalid row view for {irow_view}"
                    raise ValueError(msg)  # pragama: no cover
            elif isinstance(irow_view, (ApplyFormView, GroupBoxApplyFormView)):
                form_view = self._make_apply_form(irow_view)
                setattr(self, row_field.name, form_view)
                self.add_form(form_view)
            elif isinstance(irow_view, (FormView, GroupBoxFormView)):
                form_view = self._make_form(irow_view)
                setattr(self, row_field.name, form_view)
                self.add_form(form_view)

    def _make_form(self, iview: FormView[AnyFormItems]) -> "QtFormView[AnyFormItems]":
        """Make a form view from the given interface."""
        iview_type = type(iview)
        cls_name = iview_type.__name__[1:]
        bases: Tuple[Any, ...]
        if isinstance(iview, GroupBoxFormView):
            bases = (QtGroupBoxFormView[AnyFormItems],)
        else:
            bases = (QtFormView[AnyFormItems],)
        bases += (iview_type,)
        form_view_type: Type[QtFormView[AnyFormItems]] = make_dataclass(
            cls_name,
            fields=(),
            bases=bases,
            eq=False,
        )
        return form_view_type()

    def _make_apply_form(
        self, iview: ApplyFormView[AnyFormItems]
    ) -> "QtApplyFormView[AnyFormItems]":
        """Make an apply form view from the given interface."""
        iview_type = type(iview)
        cls_name = iview_type.__name__[1:]
        bases: Tuple[Any, ...]
        if isinstance(iview, GroupBoxApplyFormView):
            bases = (QtGroupBoxApplyFormView[AnyFormItems],)
        else:
            bases = (QtApplyFormView[AnyFormItems],)
        bases += (iview_type,)
        form_view_type: Type[QtApplyFormView[AnyFormItems]] = make_dataclass(
            cls_name,
            fields=(),
            bases=bases,
            eq=False,
        )
        return form_view_type()

    def _make_view(
        self, iview: RowItemView[AnyFormItems]
    ) -> Optional[QtRowItemView[AnyFormItems]]:
        if isinstance(iview, NoLabelView):
            return QtNoLabelView[AnyFormItems]()
        elif isinstance(iview, LabelView):
            return QtLabelView[AnyFormItems]()
        elif isinstance(iview, CheckBoxView):
            return QtCheckBoxView[AnyFormItems]()
        elif isinstance(iview, SelectFileView):
            return QtSelectFileView[AnyFormItems]()
        elif isinstance(iview, DoubleLineEditView):
            return QtDoubleLineEditView[AnyFormItems]()
        elif isinstance(iview, Vector3DView):
            return QtVector3DView[AnyFormItems]()
        elif isinstance(iview, LineEditView):
            return QtLineEditView[AnyFormItems]()
        elif isinstance(iview, TextEditView):
            return QtTextEditView[AnyFormItems]()
        elif isinstance(iview, SpinBoxView):
            return QtSpinBoxView[AnyFormItems]()
        elif isinstance(iview, ComboBoxView):
            return QtComboBoxView[AnyFormItems]()
        elif isinstance(iview, ComboBoxItemsView):
            return QtComboBoxItemsView[AnyFormItems]()
        elif isinstance(iview, CheckBoxGroupView):
            return QtButtonsGroupView[AnyFormItems](ButtonType.CHECKBOX)
        elif isinstance(iview, RadioButtonGroupView):
            return QtButtonsGroupView[AnyFormItems](ButtonType.RADIOBUTTON)
        return None


@dataclass(eq=False)
class QtApplyFormView(QtFormView[AnyFormItems], ApplyFormView[AnyFormItems]):

    validate_before_apply: bool = field(init=False, default=True)

    def __post_init__(self) -> None:
        self.apply_button = QPushButton("Apply")
        super().__post_init__()
        self.apply_button_layout = QHBoxLayout()
        self.apply_button_layout.addStretch()
        self.apply_button_layout.addWidget(self.apply_button)
        # add signals
        self.apply_clicked.add_qt_signals((self.apply_button, self.apply_button.clicked))
        self.add_apply_button()

    @property  # type: ignore[misc]
    def apply_button_text(self) -> str:
        return self.apply_button.text()

    @apply_button_text.setter
    def apply_button_text(self, text: str) -> None:
        self.apply_button.setText(text)

    def add_apply_button(self) -> None:
        self.form_layout.addRow(self.apply_button_layout)

    def _make_form(self, iview: FormView[AnyFormItems]) -> "QtFormView[AnyFormItems]":
        """Make a form view from the given interface."""
        if isinstance(iview, ApplyFormView):
            iview_type = type(iview)
            cls_name = iview_type.__name__[1:]
            form_view_type: Type[QtApplyFormView[AnyFormItems]] = make_dataclass(
                cls_name,
                fields=(),
                bases=(QtApplyFormView[AnyFormItems], iview_type),
                eq=False,
            )
            form_view = form_view_type()
            form_view.add_apply_button()
            return form_view
        else:
            return super()._make_form(iview)


@dataclass(eq=False)
class QtGroupBoxFormView(QtFormView[AnyFormItems], GroupBoxFormView[AnyFormItems]):
    view: QGroupBox = field(init=False, repr=False, default_factory=QGroupBox)

    @property  # type: ignore[misc]
    def title(self) -> str:
        return self.view.title()

    @title.setter
    def title(self, title: str) -> None:
        self.view.setTitle(title)

    @property  # type: ignore[misc]
    def is_checkable(self) -> bool:
        return self.view.isCheckable()

    @is_checkable.setter
    def is_checkable(self, is_checkable: bool) -> None:
        self.view.setCheckable(is_checkable)

    @property  # type: ignore[misc]
    def is_checked(self) -> bool:
        return self.view.isChecked()

    @is_checked.setter
    def is_checked(self, is_checked: bool) -> None:
        self.view.setChecked(is_checked)


@dataclass(eq=False)
class QtGroupBoxApplyFormView(
    QtApplyFormView[AnyFormItems], GroupBoxApplyFormView[AnyFormItems]
):
    view: QGroupBox = field(init=False, repr=False, default_factory=QGroupBox)

    @property  # type: ignore[misc]
    def title(self) -> str:
        return str(self.view.title())

    @title.setter
    def title(self, title: str) -> None:
        self.view.setTitle(title)

    @property  # type: ignore[misc]
    def is_checkable(self) -> bool:
        return bool(self.view.isCheckable())

    @is_checkable.setter
    def is_checkable(self, is_checkable: bool) -> None:
        self.view.setCheckable(is_checkable)

    @property  # type: ignore[misc]
    def is_checked(self) -> bool:
        return bool(self.view.isChecked())

    @is_checked.setter
    def is_checked(self, is_checked: bool) -> None:
        self.view.setChecked(is_checked)

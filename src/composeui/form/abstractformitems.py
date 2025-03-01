from composeui.commontypes import AnyFormView, AnyModel
from composeui.form.abstractcomboboxitems import AbstractComboboxItems
from composeui.form.iformview import (
    ButtonsGroupView,
    CheckBoxView,
    ComboBoxView,
    DoubleLineEditView,
    FormView,
    LineEditView,
    RowView,
    SelectFileView,
    SpinBoxView,
    TextEditView,
    Vector3DView,
)

from typing_extensions import OrderedDict, Self

import itertools as it
from abc import ABC, abstractmethod
from typing import Any, Dict, Generic, List, Optional, Sequence, Tuple, Union


class AbstractFormItems(ABC, Generic[AnyModel, AnyFormView]):
    def __init__(self, model: AnyModel, view: AnyFormView) -> None:
        self._model: AnyModel = model
        self._view: AnyFormView = view
        self.combobox_items: Dict[str, AbstractComboboxItems] = {}

    def get_label(self, field: str, parent_fields: Tuple[str, ...] = ()) -> str:
        """Get the label for the item of the form with the given field."""
        return field.replace("_", " ").title()

    def is_visible(self, field: str, parent_fields: Tuple[str, ...] = ()) -> bool:
        return True

    def is_enabled(self, field: str, parent_fields: Tuple[str, ...] = ()) -> bool:
        return True

    def get_error_messages(self, field: str, parent_fields: Tuple[str, ...] = ()) -> List[str]:
        return []

    @abstractmethod
    def get_value(self, field: str, parent_fields: Tuple[str, ...] = ()) -> Any:
        """Get the value for the given field."""
        msg = f"The given field is unknown: {(*parent_fields,field)}"
        raise ValueError(msg)

    @abstractmethod
    def set_value(self, field: str, value: Any, parent_fields: Tuple[str, ...] = ()) -> bool:
        """Set the value for the given field."""
        return False

    def get_current_index(self, field: str, parent_fields: Tuple[str, ...] = ()) -> int:
        """Get the current index for the given field."""
        acceptable_values = self.acceptable_values(field, parent_fields)
        if acceptable_values is not None:
            try:
                return acceptable_values.index(self.get_value(field, parent_fields))
            except ValueError:
                return -1
        elif field in self.combobox_items:
            combobox_items = self.combobox_items[field]
            for index in range(combobox_items.row_count()):
                if combobox_items.data(index, 0) == self.get_value(field, parent_fields):
                    return index
            return -1
        else:
            msg = (
                f"No index for the given field: '{field}'\n"
                f"[Hint]: The field '{field}' is not managed in the:\n"
                "  - 'acceptable_values' method\n"
                "  - 'combobox_items' attribute doesn't point to it's 'items'"
            )
            raise ValueError(msg)

    def set_current_index(
        self,
        field: str,
        current_index: int,
        parent_fields: Tuple[str, ...] = (),
    ) -> bool:
        """Set the current index for the given field."""
        acceptable_values = self.acceptable_values(field, parent_fields)
        if acceptable_values is not None:
            if len(acceptable_values) > 0 and current_index != -1:
                return self.set_value(field, acceptable_values[current_index], parent_fields)
            return False
        elif field in self.combobox_items:
            value = self.combobox_items[field].data(current_index, 0)
            return self.set_value(field, value, parent_fields)
        else:
            msg = f"No index for the given field: {field}"
            raise ValueError(msg)

    def acceptable_values(
        self,
        field: str,
        parent_fields: Tuple[str, ...] = (),
    ) -> Optional[Sequence[Any]]:
        """Get the acceptable values for the given field."""
        return None

    def acceptable_displayed_values(
        self,
        field: str,
        parent_fields: Tuple[str, ...] = (),
    ) -> Optional[Sequence[str]]:
        """Get the acceptable values to display to the user."""
        values = self.acceptable_values(field, parent_fields)
        if values is not None:
            return [str(value) if value is not None else "" for value in values]
        return None

    def is_field_available(self, field: str, parent_fields: Tuple[str, ...] = ()) -> bool:
        """Check if the field is available or not."""
        return True

    def set_field_available(
        self,
        field: str,
        is_available: bool,
        parent_fields: Tuple[str, ...] = (),
    ) -> bool:
        """Set if the field is available or not."""
        return True

    def update(
        self, field: str, parent_fields: Tuple[str, ...] = (), is_label: bool = False
    ) -> None:
        row_view: Union[FormView[Self], RowView[Self]] = self._view
        for parent_field in parent_fields:
            row_view = getattr(row_view, parent_field)
        row_view = getattr(row_view, field)
        if isinstance(row_view, RowView):
            if is_label:
                view = row_view.label_view
            else:
                view = row_view.field_view
            if isinstance(view, CheckBoxView):
                is_checked = self.is_field_available(field, parent_fields)
                if is_checked != view.is_checked:
                    view.is_checked = is_checked
            # only field_view
            if not is_label:
                if isinstance(view, DoubleLineEditView):
                    value = self.get_value(field, parent_fields)
                    if value is None:
                        view.value = None
                    else:
                        view.value = float(value)
                elif isinstance(view, (LineEditView, SelectFileView, TextEditView)):
                    value = self.get_value(field, parent_fields)
                    if value is None:
                        view.text = ""
                    else:
                        view.text = str(value)
                elif isinstance(view, Vector3DView):
                    value = self.get_value(field, parent_fields)
                    if value is None:
                        view.values = (None, None, None)
                    elif isinstance(value, tuple) and len(value) == 3:
                        view.values = value
                    else:
                        msg = (
                            "Type of the returned value of get_value for "
                            f"{(*parent_fields, field)} is incorrect. "
                            "Expected None or a tuple of 3 float|None values"
                        )
                        raise ValueError(msg)
                elif isinstance(view, SpinBoxView):
                    value = self.get_value(field, parent_fields)
                    if value is None:
                        view.value = None
                    else:
                        view.value = int(value)
                elif isinstance(view, ButtonsGroupView):
                    # update the proposed values if different
                    values = self.acceptable_displayed_values(field, parent_fields)
                    if values is not None:
                        str_values = tuple(map(str, values))
                        if str_values != view.values:
                            view.values = str_values
                    elif len(view.values) > 0:
                        view.values = ()
                    # update the current value
                    value = self.get_current_index(field, parent_fields)
                    view.current_index = value
                elif isinstance(view, ComboBoxView):
                    current_index = self.get_current_index(field, parent_fields)
                    # update the proposed values if different
                    values = self.acceptable_values(field, parent_fields)
                    displayed_values = self.acceptable_displayed_values(field, parent_fields)
                    if displayed_values is not None and values is not None:
                        new_values = OrderedDict(
                            (value, displayed_value)
                            for value, displayed_value in zip(values, displayed_values)
                        )
                        if new_values != values:
                            # find the value for the current index
                            if current_index >= 0:
                                try:
                                    current_value = next(
                                        it.islice(view.values, current_index, None)
                                    )
                                except StopIteration:
                                    # it means the current index has been modified beforehand
                                    # therefore it is the responsability of the user
                                    # so we keep it the same
                                    pass
                                else:
                                    try:
                                        # update the current index according to the new values
                                        current_index = values.index(current_value)
                                    except ValueError:
                                        # if the new values doesn't contain the value for the
                                        # previous current index fallback to -1
                                        current_index = -1
                            # update the values of the view
                            view.values = new_values
                    elif len(view.values) > 0:
                        view.values = OrderedDict[Any, str]()
                        current_index = -1
                    # update the current index in the view if different
                    if current_index != view.current_index:
                        view.current_index = current_index

    def to_float_value(
        self,
        value: Any,
        default: Optional[float] = None,
        min_value: Optional[float] = None,
        max_value: Optional[float] = None,
    ) -> Optional[float]:
        """Transform the given value to a float or None if failed."""
        if str(value) == "":
            return default
        else:
            try:
                float_value = float(value)
            except (ValueError, TypeError):
                return None
            else:
                if (min_value is not None and float_value < min_value) or (
                    max_value is not None and float_value > max_value
                ):
                    return None
                else:
                    return float_value

    def to_int_value(
        self,
        value: Any,
        default: Optional[int] = None,
        min_value: Optional[int] = None,
        max_value: Optional[int] = None,
    ) -> Optional[int]:
        """Transform the given value to an int or None if failed."""
        if str(value) == "":
            return default
        else:
            try:
                int_value = int(value)
            except (ValueError, TypeError):
                return None
            else:
                if (min_value is not None and int_value < min_value) or (
                    max_value is not None and int_value > max_value
                ):
                    return None
                else:
                    return int_value

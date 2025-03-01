"""Validators."""

from composeui.commontypes import AnyFormItems

from qtpy.QtGui import QDoubleValidator
from typing_extensions import Literal

import typing

if typing.TYPE_CHECKING:
    from composeui.form.formview import DoubleLineEditView, Vector3DView


class FormDoubleValidator(QDoubleValidator):
    def __init__(self, view: "DoubleLineEditView[AnyFormItems]") -> None:
        super().__init__()
        self._view = view

    def fixup(self, input_text: str) -> str:
        if self._view.items is not None and input_text == "" and self._view.field_name != "":
            return str(
                self._view.items.get_value(self._view.field_name, self._view.parent_fields)
            )
        else:
            return super().fixup(input_text)


class FormVector3DValidator(QDoubleValidator):
    def __init__(self, view: "Vector3DView[AnyFormItems]", index: Literal[0, 1, 2]) -> None:
        super().__init__()
        self._view = view
        self._index = index

    def fixup(self, input_text: str) -> str:
        if self._view.items is not None and input_text == "" and self._view.field_name != "":
            values = self._view.items.get_value(
                self._view.field_name, self._view.parent_fields
            )
            if isinstance(values, tuple) and self._index < len(values):
                return str(values[self._index])
        return super().fixup(input_text)

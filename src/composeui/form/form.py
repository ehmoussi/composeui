r"""Slots of the FormView."""

from composeui.commontypes import AnyFormItems
from composeui.core import selectfiles, tools
from composeui.core.views.view import View
from composeui.form.formview import (
    ButtonsGroupView,
    CheckBoxView,
    ComboBoxItemsView,
    ComboBoxView,
    DoubleLineEditView,
    FormView,
    LabelView,
    LineEditView,
    RowItemIndexView,
    RowItemTextView,
    RowItemValueView,
    RowView,
    SelectFileView,
    SpinBoxView,
    Vector3DView,
)
from composeui.mainview.views.mainview import MainView

from typing_extensions import Concatenate, ParamSpec

from functools import wraps
from typing import Callable, Optional

P = ParamSpec("P")


def update_row_view(
    update_function: Callable[Concatenate[P], bool],
) -> Callable[Concatenate[P], None]:
    r"""Update the text/value/current index of a compound view."""

    @wraps(update_function)
    def update_with_checking_success(*args: P.args, **kwargs: P.kwargs) -> None:
        is_ok = update_function(*args, **kwargs)
        if is_ok and "view" in kwargs and isinstance(kwargs["view"], View):
            tools.update_view_with_dependencies(kwargs["view"])

    return update_with_checking_success


@update_row_view
def update_text(*, view: RowItemTextView[AnyFormItems], with_update: bool = True) -> bool:
    r"""Update the text in the form items.

    If with update is False then return False to avoid update the row view.
    Useful for the apply button that need to update only after updating all fields.
    """
    if view.items is not None:
        return (
            view.items.set_value(view.field_name, view.text, view.parent_fields)
            and with_update
        )
    return False


@update_row_view
def update_vector(*, view: Vector3DView[AnyFormItems], with_update: bool = True) -> bool:
    r"""Update the values in the form items.

    If with update is False then return False to avoid update the row view.
    Useful for the apply button that need to update only after updating all fields.
    """
    if view.items is not None:
        return (
            view.items.set_value(view.field_name, view.values, view.parent_fields)
            and with_update
        )
    return False


@update_row_view
def update_value(*, view: RowItemValueView[AnyFormItems], with_update: bool = True) -> bool:
    r"""Update the value in the form items.

    If with update is False then return False to avoid update the row view.
    Useful for the apply button that need to update only after updating all fields.
    """
    if view.items is not None:
        return (
            view.items.set_value(view.field_name, view.value, view.parent_fields)
            and with_update
        )
    return False


@update_row_view
def update_current_index(
    *, view: RowItemIndexView[AnyFormItems], with_update: bool = True
) -> bool:
    r"""Update the current index in the form items.

    If with update is False then return False to avoid update the row view.
    Useful for the apply button that need to update only after updating all fields
    """
    if view.items is not None:
        return (
            view.items.set_current_index(
                view.field_name,
                view.current_index,
                view.parent_fields,
            )
            and with_update
        )
    return False


@update_row_view
def open_select_path_view(*, view: SelectFileView[AnyFormItems], main_view: MainView) -> bool:
    """Open the select path view."""
    path = selectfiles.select_file(main_view, view.extensions, view.mode)
    if path is not None:
        view.text = str(path)
        if view.items is not None:
            return view.items.set_value(view.field_name, view.text, view.parent_fields)
    return False


def open_select_path_view_without_saving(
    *, view: SelectFileView[AnyFormItems], main_view: MainView
) -> None:
    """Open the select path view."""
    path = selectfiles.select_file(main_view, view.extensions, view.mode)
    if path is not None:
        view.text = str(path)


@update_row_view
def set_field_available(*, view: CheckBoxView[AnyFormItems]) -> bool:
    """Set if the field is available or not."""
    if view.items is not None:
        view.items.set_field_available(
            view.field_name,
            view.is_checked,
            view.parent_fields,
        )
    return False


def update_apply_form(*, view: FormView[AnyFormItems]) -> None:
    """Update the model when the button apply is clicked."""
    for child_view in view.children.values():
        if isinstance(child_view, RowView):
            field_view = child_view.field_view
            if isinstance(field_view, (DoubleLineEditView, SpinBoxView)):
                update_value(view=field_view, with_update=False)
            elif isinstance(field_view, (ComboBoxView, ComboBoxItemsView, ButtonsGroupView)):
                update_current_index(view=field_view, with_update=False)
            elif isinstance(
                field_view, (LabelView, CheckBoxView, LineEditView, SelectFileView)
            ):
                update_text(view=field_view, with_update=False)
            elif isinstance(field_view, Vector3DView):
                update_vector(view=field_view, with_update=False)
        elif isinstance(child_view, FormView):
            update_apply_form(view=child_view)


def update_infos(
    master_view: FormView[AnyFormItems],
    *,
    parent_view: Optional[RowView[AnyFormItems]] = None,
    with_color: bool = True,
) -> bool:
    if master_view.items is not None:
        infos = []
        is_children_ok = True
        for field, child_view in master_view.children.items():
            if isinstance(child_view, RowView):
                messages = master_view.items.get_error_messages(
                    field, child_view.parent_fields
                )
                for message in messages:
                    item_message = f"  * {message}"
                    if item_message not in infos:
                        infos.append(item_message)
                if with_color:
                    if len(messages) == 0:
                        if child_view is parent_view:
                            child_view.field_view.color = (186, 216, 0)
                        else:
                            child_view.field_view.color = None
                    else:
                        child_view.field_view.color = (255, 0, 0)
            elif isinstance(child_view, FormView):
                is_children_ok &= update_infos(
                    child_view, parent_view=parent_view, with_color=with_color
                )
        master_view.infos = "\n".join(infos)
        return is_children_ok and len(infos) == 0
    return True


def enable_view(
    *,
    parent_view: RowView[AnyFormItems],
    before_validation: bool = False,
) -> None:
    """Enable/Disable the view according to the status of the checkbox label."""
    if isinstance(parent_view.label_view, CheckBoxView):
        parent_view.field_view.is_enabled = parent_view.label_view.is_checked
    tools.update_view_with_dependencies(parent_view, before_validation=before_validation)

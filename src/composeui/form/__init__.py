from composeui.commontypes import AnyFormItems
from composeui.core import tools
from composeui.form import form
from composeui.form.iformview import (
    IApplyFormView,
    IButtonsGroupView,
    ICheckBoxView,
    IComboBoxItemsView,
    IComboBoxView,
    IDoubleLineEditView,
    IFormView,
    ILineEditView,
    IRowView,
    ISelectFileView,
    ISpinBoxView,
    IVector3DView,
)

from typing_extensions import OrderedDict

from functools import partial
from typing import Optional


def initialize_form_view(view: IFormView[AnyFormItems], form_items: AnyFormItems) -> None:
    """Initialize the form view."""
    view.items = form_items
    if view.field_name == "":
        parent_fields = view.parent_fields
    else:
        parent_fields = (*view.parent_fields, view.field_name)
    view.dependencies = []
    for field, child_view in view.children.items():
        if isinstance(child_view, IApplyFormView):
            child_view.validate_before_apply = True
        if isinstance(child_view, (IFormView, IRowView)):
            child_view.field_name = field
            child_view.parent_fields = parent_fields
            view.dependencies.append(child_view)
        if isinstance(child_view, IRowView):
            child_view.dependencies = [child_view.label_view, child_view.field_view]
            child_view.field_view.dependencies = []
            child_view.label_view.field_name = field
            child_view.label_view.parent_fields = parent_fields
            child_view.label_view.is_label = True
            child_view.field_view.field_name = field
            child_view.field_view.parent_fields = parent_fields
            child_view.field_view.is_label = False
            child_view.items = form_items
            child_view.label_view.items = form_items
            child_view.field_view.items = form_items
            text = form_items.get_label(field, parent_fields)
            if hasattr(child_view.label_view, "text"):
                child_view.label_view.text = text
            if isinstance(child_view.field_view, IButtonsGroupView):
                values = form_items.acceptable_displayed_values(field, parent_fields)
                if values is not None:
                    child_view.field_view.values = tuple(map(str, values))
            elif isinstance(child_view.field_view, IComboBoxView):
                values = form_items.acceptable_values(field, parent_fields)
                displayed_values = form_items.acceptable_displayed_values(field, parent_fields)
                if values is not None and displayed_values is not None:
                    child_view.field_view.values = OrderedDict(zip(values, displayed_values))
                else:
                    child_view.field_view.values = OrderedDict()
        elif isinstance(child_view, IFormView):
            initialize_form_view(child_view, form_items)
    tools.update_view_with_dependencies(view)
    form.update_infos(view, with_color=False)


def connect_form_view(
    view: IFormView[AnyFormItems],
    master_view: Optional[IFormView[AnyFormItems]] = None,
) -> bool:
    """Connect the rows and sub form views."""
    if master_view is None:
        master_view = view
    for child_view in view.children.values():
        if isinstance(child_view, IRowView):
            connect_form_row_view(child_view, view, master_view)
        elif isinstance(child_view, IApplyFormView):
            connect_apply_form_view(child_view, master_view)
            child_view.field_changed += [view.field_changed]
        elif isinstance(child_view, IFormView):
            connect_form_view(child_view, master_view)
            child_view.field_changed += [view.field_changed]
    return False


def connect_form_row_view(
    view: IRowView[AnyFormItems],
    parent_view: IFormView[AnyFormItems],
    master_view: IFormView[AnyFormItems],
) -> None:
    """Connect the slots for each row of the form view."""
    if view.items is not None:
        if isinstance(view.label_view, ICheckBoxView):
            view.label_view.status_changed = [
                [
                    form.set_field_available,
                    form.enable_view,
                    partial(form.update_infos, master_view),
                    parent_view.field_changed,
                ]
            ]
        # Be careful the order is important
        # e.g a field of type ISelectFileView will be considered as a ILineEditView
        # because all the attributes of ILineEditView are available into ISelectFileView
        if isinstance(view.field_view, ISelectFileView):
            view.field_view.editing_finished = [
                [
                    form.update_text,
                    partial(form.update_infos, master_view),
                    parent_view.field_changed,
                ]
            ]
            view.field_view.clicked = [
                [
                    form.open_select_path_view,
                    partial(form.update_infos, master_view),
                ]
            ]
        elif isinstance(view.field_view, IDoubleLineEditView):
            view.field_view.editing_finished = [
                [
                    form.update_value,
                    partial(form.update_infos, master_view),
                    parent_view.field_changed,
                ]
            ]
        elif isinstance(view.field_view, ILineEditView):
            view.field_view.editing_finished = [
                [
                    form.update_text,
                    partial(form.update_infos, master_view),
                    parent_view.field_changed,
                ]
            ]
        elif isinstance(view.field_view, ISpinBoxView):
            view.field_view.value_changed = [
                [
                    form.update_value,
                    partial(form.update_infos, master_view),
                    parent_view.field_changed,
                ]
            ]
        elif isinstance(
            view.field_view, (IComboBoxView, IComboBoxItemsView, IButtonsGroupView)
        ):
            view.field_view.current_index_changed = [
                [
                    form.update_current_index,
                    partial(form.update_infos, master_view),
                    parent_view.field_changed,
                ]
            ]
        elif isinstance(view.field_view, IVector3DView):
            view.field_view.editing_finished = [
                [
                    form.update_vector,
                    partial(form.update_infos, master_view),
                    parent_view.field_changed,
                ]
            ]


def connect_apply_form_view(
    view: IFormView[AnyFormItems],
    master_view: Optional[IFormView[AnyFormItems]] = None,
) -> bool:
    if isinstance(view, IApplyFormView) and view.items is not None:
        if view.validate_before_apply:
            view.apply_clicked = [
                [
                    partial(form.update_infos, view, parent_view=None),
                    form.update_apply_form,
                ]
            ]
        else:
            view.apply_clicked = [
                [
                    form.update_apply_form,
                    partial(form.update_infos, view, parent_view=None),
                ]
            ]
    if master_view is None:
        master_view = view
    for child_view in view.children.values():
        if isinstance(child_view, IRowView):
            connect_apply_form_row_view(child_view, view, master_view)
        elif isinstance(child_view, IFormView):
            connect_apply_form_view(child_view, master_view)
            child_view.field_changed += [view.field_changed]
    return False


def connect_apply_form_row_view(
    view: IRowView[AnyFormItems],
    parent_view: IFormView[AnyFormItems],
    master_view: IFormView[AnyFormItems],
) -> None:
    """Connect the slots for each row of the form view."""
    if view.items is not None:
        if isinstance(view.label_view, ICheckBoxView):
            view.label_view.status_changed = [
                [
                    partial(form.enable_view, before_validation=True),
                    partial(form.update_infos, master_view, parent_view=None),
                    parent_view.field_changed,
                ]
            ]
        # Be careful the order is important
        # e.g a field of type ISelectFileView will be considered as a ILineEditView
        # because all the attributes of ILineEditView are available into ISelectFileView
        if isinstance(view.field_view, ISelectFileView):
            view.field_view.clicked = [
                [
                    form.open_select_path_view_without_saving,
                    partial(
                        tools.update_view_with_dependencies,
                        view.field_view,
                        before_validation=True,
                    ),
                    partial(form.update_infos, master_view, parent_view=None),
                ]
            ]
        if isinstance(view.field_view, (IDoubleLineEditView, ILineEditView, ISelectFileView)):
            view.field_view.editing_finished = [
                [
                    partial(
                        tools.update_view_with_dependencies,
                        view.field_view,
                        before_validation=True,
                    ),
                    partial(form.update_infos, master_view, parent_view=None),
                    parent_view.field_changed,
                ]
            ]
        elif isinstance(view.field_view, ISpinBoxView):
            view.field_view.value_changed = [
                [
                    partial(
                        tools.update_view_with_dependencies,
                        view.field_view,
                        before_validation=True,
                    ),
                    partial(form.update_infos, master_view, parent_view=None),
                    parent_view.field_changed,
                ]
            ]
        elif isinstance(
            view.field_view, (IComboBoxView, IComboBoxItemsView, IButtonsGroupView)
        ):
            view.field_view.current_index_changed = [
                [
                    partial(
                        tools.update_view_with_dependencies,
                        view.field_view,
                        False,
                        before_validation=True,
                    ),
                    partial(form.update_infos, master_view, parent_view=None),
                    parent_view.field_changed,
                ]
            ]
        elif isinstance(view.field_view, IVector3DView):
            view.field_view.editing_finished = [
                [
                    partial(
                        tools.update_view_with_dependencies,
                        view.field_view,
                        before_validation=True,
                    ),
                    partial(form.update_infos, master_view, parent_view=None),
                    parent_view.field_changed,
                ]
            ]

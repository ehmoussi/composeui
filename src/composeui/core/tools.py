r"""Common tools."""

from composeui.core.views.view import View
from composeui.form import form
from composeui.form.formview import FormView, RowView
from composeui.items.table.tableview import TableView
from composeui.mainview.views.fileview import FileView
from composeui.mainview.views.mainview import MainView
from composeui.mainview.views.messageview import MessageView, MessageViewType

from typing_extensions import OrderedDict

from collections import deque
from typing import List, Optional, Set, Tuple


def update_all_views(main_view: MainView) -> None:
    r"""Update all the views."""
    # call the slots associated with the update all signal
    main_view.update_all()
    views = deque(main_view.children.values())
    while len(views) > 0:
        view = views.pop()
        views.extendleft(view.children.values())
        _update_view(view, update_visibility=False)


def update_view_with_dependencies(
    view: View, keep_selection: bool = False, before_validation: bool = False
) -> None:
    r"""Update the given view and the views which depends on it."""
    dependencies = deque([view])
    updated_dependencies: Set[View] = set()
    while len(dependencies) > 0:
        dependent_view = dependencies.popleft()
        _update_view(
            dependent_view, keep_selection=keep_selection, before_validation=before_validation
        )
        updated_dependencies.add(dependent_view)
        for dependent_child_view in dependent_view.dependencies:
            if dependent_child_view not in updated_dependencies:
                dependencies.append(dependent_child_view)


def _update_view(
    view: View,
    keep_selection: bool = False,
    before_validation: bool = False,
    update_visibility: bool = True,
) -> None:
    r"""Update the given view.

    if keep_selection is true, the current selection is preserverd.
    """
    view.block_signals = True
    try:
        if isinstance(view, TableView) and view.items is not None:
            selected_items = OrderedDict[Tuple[int, ...], List[int]]()
            if keep_selection:
                selected_items = view.selected_items
            view.update()
            if keep_selection:
                view.selected_items = selected_items
        elif isinstance(view, FormView) and view.items is not None:
            if not before_validation:
                view.update()
            is_visible = view.items.is_visible(view.field_name, view.parent_fields)
            if update_visibility:
                view.is_visible = is_visible
            view.is_enabled = view.items.is_enabled(view.field_name, view.parent_fields)
            form.update_infos(view)
        elif isinstance(view, RowView) and view.items is not None:
            if not before_validation:
                view.update()
            is_visible = view.items.is_visible(view.field_name, view.parent_fields)
            if update_visibility:
                view.is_visible = is_visible
            view.field_view.is_enabled = view.items.is_enabled(
                view.field_name, view.parent_fields
            )
        elif not before_validation:
            view.update()
    finally:
        view.block_signals = False


def find_focus_table(view: View) -> Optional[View]:
    r"""Find the table with the focus."""
    if isinstance(view, View):
        if isinstance(view, TableView) and view.has_focus:
            return view
        elif not isinstance(view, TableView):
            for child_view in view.children.values():
                if isinstance(view, MainView) and isinstance(
                    child_view, (MessageView, FileView)
                ):
                    continue
                focus_table = find_focus_table(child_view)
                if focus_table is not None:
                    return focus_table
    # elif isinstance(view, AbstractViews):
    #     for view_child in view:
    #         focus_table = find_focus_table(view_child)
    #         if focus_table is not None:
    #             return focus_table
    return None


def display_error_message(main_view: MainView, message: str) -> bool:
    r"""Display error message."""
    main_view.message_view.title = main_view.title
    main_view.message_view.message_type = MessageViewType.critical
    main_view.message_view.message = message
    result = main_view.message_view.run()
    return result is not None and result


def display_warning_message(main_view: MainView, message: str) -> bool:
    r"""Display warning message."""
    main_view.message_view.title = main_view.title
    main_view.message_view.message_type = MessageViewType.warning
    main_view.message_view.message = message
    result = main_view.message_view.run()
    return result is not None and result


def ask_confirmation(main_view: MainView, message: str) -> bool:
    r"""Display error message."""
    main_view.message_view.title = main_view.title
    main_view.message_view.message_type = MessageViewType.question
    main_view.message_view.message = message
    result = main_view.message_view.run()
    return result is not None and result

r"""Slots of table with select items and modify datas table."""

from composeui.commontypes import AnyDetailTableItems, AnyMasterTableItems, AnyModel
from composeui.core import selectfiles, tools
from composeui.core.tasks.tasks import Tasks
from composeui.items.linkedtable.exportfilelinkedtabletask import ExportFileLinkedTableTask
from composeui.items.linkedtable.ilinkedtableview import LinkedTableView
from composeui.items.linkedtable.importfilelinkedtabletask import ImportFileLinkedTableTask
from composeui.items.table.itableview import TableGroupView
from composeui.items.tree.itreeview import ExportTreeOptions
from composeui.mainview import progresspopup
from composeui.mainview.views.imainview import MainView

from functools import partial


def import_clicked(
    *,
    view: LinkedTableView[AnyMasterTableItems, AnyDetailTableItems],
    main_view: MainView,
    model: AnyModel,
) -> None:
    if view.master_table.items is not None and view.detail_table.items is not None:
        is_cleaning = view.master_table.items.get_nb_rows() != 0 and tools.ask_confirmation(
            main_view, "Do you want to delete all the rows of the tables before the import ?"
        )
        filepath, filepath_extension = selectfiles.select_table_file(
            main_view, view.import_extensions
        )
        if filepath is not None and filepath_extension:
            task = ImportFileLinkedTableTask(
                view.master_table.items,
                view.detail_table.items,
                filepath,
                is_cleaning,
                filepath_extension,
            )
            task.is_debug = model.is_debug
            progresspopup.display_view(
                main_view,
                tasks=Tasks((task,), print_to_std=True),
                finished_slots=[
                    partial(tools.update_view_with_dependencies, view.master_table),
                ],
            )


def export_clicked(
    *,
    view: LinkedTableView[AnyMasterTableItems, AnyDetailTableItems],
    main_view: MainView,
    model: AnyModel,
) -> None:
    if view.master_table.items is not None and view.detail_table.items is not None:
        filepath, filepath_extension = selectfiles.save_table_file(
            main_view, view.export_extensions
        )
        if filepath is not None and filepath_extension is not None:
            export_options = ExportTreeOptions(view.export_options)
            if (
                ExportTreeOptions.EXPORT_ASK in export_options
                and len(view.master_table.selected_items) > 0
            ):
                export_only_from_selection = tools.ask_confirmation(
                    main_view, "Export only from the current selection ?"
                )
                if export_only_from_selection and len(view.master_table.selected_items) > 0:
                    # remove the EXPORT_ALL flag
                    export_options ^= ExportTreeOptions.EXPORT_ALL
                else:
                    # remove the EXPORT_ONLY_SELECTION flag
                    export_options ^= ExportTreeOptions.EXPORT_ONLY_SELECTION
            elif (
                len(view.master_table.selected_items) == 0
                and ExportTreeOptions.EXPORT_ONLY_SELECTION in export_options
            ):
                # remove the EXPORT_ONLY_SELECTION flag
                export_options ^= ExportTreeOptions.EXPORT_ONLY_SELECTION
            task = ExportFileLinkedTableTask(
                view.master_table.items,
                view.detail_table.items,
                filepath,
                filepath_extension,
                export_options,
                view.title,
            )
            task.is_debug = model.is_debug
            progresspopup.display_view(main_view, tasks=Tasks((task,), print_to_std=True))


def update_title_detail_table(view: TableGroupView[AnyDetailTableItems]) -> None:
    r"""Update the title of the detail table according to the master table."""
    if view.items is not None:
        view.title = view.items.get_title()


# def get_current_indices(
#     view: ITableView[AbstractItems],
#     main_view: IMainView,
#     view_path: Tuple[str, ...],
#     selection_path: Tuple[str, ...] = ("selection",),
# ) -> List[List[int]]:
#     r"""Get the current indices in the datas table."""
#     return tools.get_current_indices(view, main_view, view_path, *selection_path))


# def update_current_indices(
#     master_table: ITableGroupView[IMTa],
#     detail_table: ITableGroupView[IDTa],
#     main_view: IMainView,
# ) -> None:
#     r"""Update the current indices in the datas table."""
#     indices = tools.get_current_indices(master_table, main_view)
#     update_status_detail_table(detail_table, main_view)


def update_status_detail_table(
    view: TableGroupView[AnyDetailTableItems],
    update_detail_table: bool = True,
) -> None:
    r"""Update the status of the datas table."""
    if view.items is not None:
        view.title = view.items.get_title()
        view.is_enabled = view.items.can_enable_table()
        if update_detail_table:
            view.update()


# def disable_detail_table(
#     view: ILinkedTableView[AnyMasterTableItems, AnyDetailTableItems],
#     main_view: IMainView,
#     update_detail_table: bool = False,
# ) -> None:
#     r"""Disable the datas table."""
#     update_status_detail_table(view.detail_table, update_detail_table=update_detail_table)

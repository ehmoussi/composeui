from composeui.commontypes import AnyTableItems
from composeui.figure import initialize_figure_view
from composeui.items.core.initialize import initialize_items_view
from composeui.items.table import connect_table
from composeui.linkedtablefigure.linkedtablefigureview import LinkedTableFigureView


def initialize_table_figure_view(view: LinkedTableFigureView[AnyTableItems]) -> bool:
    initialize_items_view(view.table)
    initialize_figure_view(view.figure)
    view.table.dependencies.append(view)
    return False


def connect_table_figure_view(view: LinkedTableFigureView[AnyTableItems]) -> bool:
    connect_table(view.table)
    view.table.item_edited += [update_figure]
    view.figure.clicked += [update_table_selection]
    return False


def update_figure(*, parent_view: LinkedTableFigureView[AnyTableItems]) -> None:
    assert parent_view.figure.figure is not None
    all_axes = parent_view.figure.figure.get_axes()
    assert len(all_axes) == 1
    axes = all_axes[0]
    assert parent_view.table.items is not None
    parent_view.table.items.get_selected_rows()
    axes.clear()
    x = [
        float(parent_view.table.items.get_edit_data(row, parent_view.x))
        for row in range(parent_view.table.items.get_nb_rows())
    ]
    y = [
        float(parent_view.table.items.get_edit_data(row, parent_view.y))
        for row in range(parent_view.table.items.get_nb_rows())
    ]
    axes.plot(x, y)
    axes.scatter(x, y)
    axes.set_title(parent_view.table.items.get_title())
    axes.grid(True)
    parent_view.figure.update()


def update_table_selection(*, parent_view: LinkedTableFigureView[AnyTableItems]) -> None:
    x = parent_view.figure.x_last_clicked
    y = parent_view.figure.y_last_clicked
    assert x is not None
    assert y is not None
    assert parent_view.table.items is not None
    assert parent_view.figure.figure is not None
    distances = [
        (x - float(parent_view.table.items.get_edit_data(row, parent_view.x))) ** 2
        + (y - float(parent_view.table.items.get_edit_data(row, parent_view.y))) ** 2
        for row in range(parent_view.table.items.get_nb_rows())
    ]
    # select the closest row in the table
    row = min(range(len(distances)), key=lambda i: distances[i])
    parent_view.table.items.set_selected_rows([row])
    # put a red point in the figure
    label = parent_view.table.items.get_data(row, parent_view.label)
    x = float(parent_view.table.items.get_edit_data(row, parent_view.x))
    y = float(parent_view.table.items.get_edit_data(row, parent_view.y))
    axes = parent_view.figure.figure.get_axes()[0]
    update_figure(parent_view=parent_view)
    axes.scatter([x], [y], c=["red"])
    axes.annotate(label, (x, y))
    parent_view.figure.update()

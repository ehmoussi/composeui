from examples.linkedtablefigureview.app import LinkedTableFigureViewApp
from examples.linkedtablefigureview.example import ExampleMainView

import pytest


@pytest.fixture()
def main_view(app: LinkedTableFigureViewApp) -> ExampleMainView:
    return app.main_view


def test_update_figure(main_view: ExampleMainView) -> None:
    # initial state
    assert main_view.points.table.items is not None
    assert main_view.points.figure.figure is not None
    axes = main_view.points.figure.figure.get_axes()[0]
    assert main_view.points.table.items.get_nb_rows() == 21
    assert len(axes.collections[0].get_offsets()) == 21  # type: ignore[arg-type]
    # add a point
    main_view.points.table.add_clicked()
    assert len(axes.collections[0].get_offsets()) == 22  # type: ignore[arg-type]
    # edit a point
    main_view.points.table.items.set_selected_rows([21])
    main_view.points.table.items.set_data(21, 0, "point 21")
    main_view.points.table.item_edited()
    assert len(axes.collections[0].get_offsets()) == 22  # type: ignore[arg-type]
    # remove a point
    main_view.points.table.remove_clicked()
    assert len(axes.collections[0].get_offsets()) == 21  # type: ignore[arg-type]


def test_update_table_selection(main_view: ExampleMainView) -> None:
    assert main_view.points.table.items is not None
    assert main_view.points.figure.figure is not None
    assert main_view.points.table.items.get_selected_rows() == []
    # clicked on the point with (0.0, 1.0) coordinate on the figure
    main_view.points.figure.x_last_clicked = 0.0
    main_view.points.figure.y_last_clicked = 1.0
    main_view.points.figure.clicked()
    assert main_view.points.table.items.get_selected_rows() == [5]
    assert main_view.points.table.items.get_edit_data(5, 1) == pytest.approx(0.0)
    assert main_view.points.table.items.get_edit_data(5, 2) == pytest.approx(1.0)

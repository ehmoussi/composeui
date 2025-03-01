"""Test the definition of a cube."""

from composeui.items.table.tableview import TableView
from composeui.salomewrapper.core import study
from examples.salomeview.app import ExampleSalomeApp, Module1App, Module2App
from examples.salomeview.cubedefinition import CubeDefinitionView
from examples.salomeview.cubetable import CubeTableItems

import pytest


@pytest.fixture()
def cube_definition(app: ExampleSalomeApp) -> CubeDefinitionView:
    assert isinstance(app.modules[0], Module1App)
    return app.modules[0].main_view.left_dock.cube_definition


@pytest.fixture()
def cube_table(app: ExampleSalomeApp) -> TableView[CubeTableItems]:
    assert isinstance(app.modules[1], Module2App)
    return app.modules[1].main_view.cube_table


def test_fill_form(
    cube_definition: CubeDefinitionView, cube_table: TableView[CubeTableItems]
) -> None:
    # set up
    assert cube_table.items is not None
    assert cube_table.items.get_nb_rows() == 0
    assert list(cube_definition.cube.field_view.values.values()) == ["New Cube"]
    cube_definition.parameters.name.field_view.text = "test"
    cube_definition.parameters.point_1.field_view.values = (0.0, 0.0, 0.0)
    cube_definition.parameters.point_2.field_view.values = (1.0, 1.0, 1.0)
    # click "Apply"
    cube_definition.parameters.apply_clicked()
    # check if the cube is generated and the views are updated
    assert list(cube_definition.cube.field_view.values.values()) == ["New Cube", "test"]
    assert cube_table.items.get_nb_rows() == 1
    assert cube_table.items.get_data(0, 0) == "test"  # name
    assert cube_table.items.get_data(0, 1) == "(0.0, 0.0, 0.0)"  # point 1
    assert cube_table.items.get_data(0, 2) == "(1.0, 1.0, 1.0)"  # point 2
    assert cube_table.items.get_data(0, 3) != ""  # entry
    assert study.find_object_name(cube_table.items.get_data(0, 3)) == "test"

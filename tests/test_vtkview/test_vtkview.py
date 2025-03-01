from composeui.vtk.vtkview import VTKPickType, VTKView
from examples.vtkview.app import Model, VTKViewApp
from examples.vtkview.example import ExampleMainView, VTKConfigView

import pytest

from pathlib import Path


@pytest.fixture()
def main_view(app: VTKViewApp) -> ExampleMainView:
    return app.main_view


@pytest.fixture()
def vtk_config_view(app: VTKViewApp) -> VTKConfigView:
    return app.main_view.vtk_example.configuration


@pytest.fixture()
def vtk_view(app: VTKViewApp) -> VTKView:
    return app.main_view.vtk_example.vtk_view


@pytest.fixture()
def model(app: VTKViewApp) -> Model:
    return app.model


def test_initialize(vtk_config_view: VTKConfigView, model: Model) -> None:
    # view
    assert vtk_config_view.file.field_view.text == ""
    assert vtk_config_view.scalar_field.field_view.current_index == -1
    assert vtk_config_view.edge.field_view.values == ("Yes", "No")
    assert vtk_config_view.edge.field_view.current_index == 1
    assert vtk_config_view.edge_width.field_view.value == 1.0
    assert vtk_config_view.warp.field_view.current_index == 1
    assert vtk_config_view.warp_scale.field_view.value == 1.0
    assert vtk_config_view.pick_type.field_view.current_index == 0
    # items
    assert vtk_config_view.items is not None
    assert vtk_config_view.items.get_value("file") == ""
    assert vtk_config_view.items.get_value("scalar_field") is None
    assert vtk_config_view.items.get_value("edge") is False
    assert vtk_config_view.items.get_value("edge_width") == 1.0
    assert vtk_config_view.items.get_value("warp") is False
    assert vtk_config_view.items.get_value("warp_scale") == 1.0
    assert vtk_config_view.items.get_value("pick_type") == VTKPickType.CELL
    # model
    assert model.root.vtk_filepath == ""
    assert model.root.vtk_fields == []
    assert model.root.current_vtk_field is None
    assert model.root.is_edge_visible is False
    assert model.root.edge_width == 1.0
    assert model.root.is_warp_active is False
    assert model.root.warp_scale_factor == 1.0
    assert model.root.pick_type == VTKPickType.CELL


def test_is_visible(vtk_config_view: VTKConfigView) -> None:
    # edge_width
    assert vtk_config_view.edge_width.is_visible is False
    vtk_config_view.edge.field_view.current_index = 0
    vtk_config_view.edge.field_view.current_index_changed()
    assert vtk_config_view.edge_width.is_visible is True
    # warp_scale
    assert vtk_config_view.warp_scale.is_visible is False
    vtk_config_view.warp.field_view.current_index = 0
    vtk_config_view.warp.field_view.current_index_changed()
    assert vtk_config_view.warp_scale.is_visible is True


def test_read_unknown_file(
    vtk_config_view: VTKConfigView,
    vtk_view: VTKView,
    main_view: ExampleMainView,
    tmpdir: Path,
) -> None:
    """Test to read a file which doesn't contain an unstructured grid."""
    # creating a file with the good extension but with a bad content
    # bad content and bad extension
    bad_filepath_extension = Path(tmpdir, "bad.other")
    with open(bad_filepath_extension, "w") as f:
        f.write("elqmrglqnelvnjgqmerlvn")
    # - select filepath
    vtk_config_view.file.field_view.text = str(bad_filepath_extension)
    vtk_config_view.file.field_view.editing_finished()
    vtk_config_view.apply_clicked()
    assert vtk_view.vtk_ugrid is None
    assert main_view.message_view.message != ""
    # only bad content
    main_view.message_view.message = ""
    bad_filepath = Path(tmpdir, "bad.vtk")
    with open(bad_filepath, "w") as f:
        f.write("elqmrglqnelvnjgqmerlvn")
    # - select filepath
    vtk_config_view.file.field_view.text = str(bad_filepath)
    vtk_config_view.file.field_view.editing_finished()
    vtk_config_view.apply_clicked()
    assert vtk_view.vtk_ugrid is None
    assert main_view.message_view.message != ""


def test_read_vtu(vtk_config_view: VTKConfigView, vtk_view: VTKView) -> None:
    """Test the read of a vtk/vtu file."""
    # no scalar field
    assert len(vtk_config_view.scalar_field.field_view.values) == 0
    # no vtk unstructured grid
    assert vtk_view.vtk_ugrid is None
    # select filepath
    filepath = Path("tests/test_vtkview/data/tetra.vtu")
    vtk_config_view.file.field_view.text = str(filepath)
    vtk_config_view.file.field_view.editing_finished()
    vtk_config_view.apply_clicked()
    # - the scalar field is filled
    assert len(vtk_config_view.scalar_field.field_view.values) == 1
    # select field
    vtk_config_view.scalar_field.field_view.current_index = 0
    vtk_config_view.scalar_field.field_view.current_index_changed()
    vtk_config_view.apply_clicked()
    # - vtk view is filled with a an unstructured grid
    assert vtk_view.vtk_ugrid is not None


@pytest.fixture()
def app_with_ugrid(app: VTKViewApp) -> VTKViewApp:
    vtk_config_view = app.main_view.vtk_example.configuration
    vtk_view = app.main_view.vtk_example.vtk_view
    # select filepath
    filepath = Path("tests/test_vtkview/data/tetra.vtu")
    vtk_config_view.file.field_view.text = str(filepath)
    vtk_config_view.file.field_view.editing_finished()
    vtk_config_view.apply_clicked()
    # - the scalar field is filled
    assert len(vtk_config_view.scalar_field.field_view.values) == 1
    # select field
    vtk_config_view.scalar_field.field_view.current_index = 0
    vtk_config_view.scalar_field.field_view.current_index_changed()
    vtk_config_view.apply_clicked()
    # - vtk view is filled with an unstructured grid
    assert vtk_view.vtk_ugrid is not None
    # cleaning
    app.main_view.vtk_example.informations.title = ""
    app.main_view.vtk_example.informations.text = ""
    return app


def test_pick_cell(app_with_ugrid: VTKViewApp) -> None:
    """Test the picking of a cell."""
    vtk_view = app_with_ugrid.main_view.vtk_example.vtk_view
    vtk_infos = app_with_ugrid.main_view.vtk_example.informations
    # init
    assert vtk_view.last_picked_cell_id == -1
    assert vtk_infos.is_visible is False
    assert vtk_infos.title == ""
    assert vtk_infos.text == ""
    # pick a cell
    vtk_view.last_picked_cell_id = 0
    vtk_view.cell_picked()
    # check
    assert vtk_infos.is_visible is True
    assert "0" in vtk_infos.title
    assert vtk_infos.text != ""
    assert "QUADRATIC_TETRA" in vtk_infos.text


def test_pick_point(app_with_ugrid: VTKViewApp) -> None:
    """Test the picking of a point."""
    vtk_config_view = app_with_ugrid.main_view.vtk_example.configuration
    vtk_view = app_with_ugrid.main_view.vtk_example.vtk_view
    vtk_infos = app_with_ugrid.main_view.vtk_example.informations
    # change pick type to point
    vtk_config_view.pick_type.field_view.current_index = 1
    vtk_config_view.pick_type.field_view.current_index_changed()
    vtk_config_view.apply_clicked()
    # init
    assert vtk_view.last_picked_point_id == -1
    assert vtk_infos.is_visible is False
    assert vtk_infos.title == ""
    assert vtk_infos.text == ""
    # pick a point
    vtk_view.last_picked_point_id = 9
    vtk_view.point_picked()
    # check
    assert vtk_infos.is_visible is True
    assert "9" in vtk_infos.title
    assert vtk_infos.text != ""

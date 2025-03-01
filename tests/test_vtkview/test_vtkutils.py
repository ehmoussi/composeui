"""Test of vtkutils module."""

from composeui.vtk import vtkutils
from composeui.vtk.ivtkview import VTKView
from examples.vtkview.app import VTKViewApp
from examples.vtkview.example import ExampleMainView

import pytest

from pathlib import Path


@pytest.fixture()
def main_view(app: VTKViewApp) -> ExampleMainView:
    return app.main_view


@pytest.fixture()
def vtk_view(app: VTKViewApp) -> VTKView:
    vtk_view = app.main_view.vtk_example.vtk_view
    # non existing file
    vtk_view.vtk_ugrid = vtkutils.read_file(
        Path("tests", "test_vtkview", "data", "not_existing.vtu"), main_view=app.main_view
    )
    assert vtk_view.vtk_ugrid is None
    assert app.main_view.message_view.message != ""
    app.main_view.message_view.message = ""
    # existing file
    vtk_view.vtk_ugrid = vtkutils.read_file(
        Path("tests", "test_vtkview", "data", "tetra.vtu"), main_view=app.main_view
    )
    assert vtk_view.vtk_ugrid is not None
    assert app.main_view.message_view.message == ""
    return vtk_view


def test_read_file(tmpdir: Path) -> None:
    # test inexisting file
    inexisting_filepath = Path("tests", "test_vtkview", "data", "inexsiting.vtu")
    with pytest.raises(ValueError, match="doesn't exists"):
        vtkutils.read_file(inexisting_filepath)
    # test bad content file
    bad_filepath = Path(tmpdir, "bad.vtu")
    bad_filepath.write_text("aaaa")
    with pytest.raises(ValueError, match="Error parsing input file"):
        vtkutils.read_file(bad_filepath)
    # test correct vtu file
    vtu_filepath = Path("tests", "test_vtkview", "data", "tetra.vtu")
    vtk_ugrid = vtkutils.read_file(vtu_filepath)
    assert vtk_ugrid is not None
    # test vtk extension
    vtk_filepath = Path(vtu_filepath.parent, "tetra.vtk")
    assert vtk_filepath.exists() is True
    assert vtkutils.read_file(vtk_filepath) is not None


def test_write_file(tmpdir: Path) -> None:
    """Test write_file."""
    # test correct vtu file
    vtk_filepath_ref = Path("tests", "test_vtkview", "data", "tetra.vtk")
    vtu_filepath_ref = Path("tests", "test_vtkview", "data", "tetra.vtu")
    # read the unstructured grid
    vtk_ugrid = vtkutils.read_file(vtu_filepath_ref)
    assert vtk_ugrid is not None, f"Failed to read {vtu_filepath_ref}"
    # write a vtk file
    vtk_filepath = Path(tmpdir, "tetra.vtk")
    vtkutils.write_file(vtk_ugrid, vtk_filepath)
    # - check if identical with the reference file
    assert vtk_filepath.read_text() == vtk_filepath_ref.read_text()
    # write a vtu file
    vtu_filepath = Path(tmpdir, "tetra.vtu")
    vtkutils.write_file(vtk_ugrid, vtu_filepath)
    # - check if identical with the reference file
    assert vtu_filepath.read_text() == vtu_filepath_ref.read_text()


def test_get_cell_field_value(vtk_view: VTKView) -> None:
    """Test get_cell_field_value."""
    # The scalar name is not given
    with pytest.raises(ValueError, match="Can't retrieve the value of a cell"):
        vtkutils.get_cell_field_value(0, view=vtk_view)
    # The scalar name is not correct
    vtk_view.vtk_scalar_name = "incorrect_name"
    with pytest.raises(ValueError, match="'incorrect_name' is not part of the dataset"):
        vtkutils.get_cell_field_value(0, view=vtk_view)
    # The scalar name is correct
    vtk_view.vtk_scalar_name = "scalars"
    with pytest.raises(ValueError, match="'-1' is not a valid cell id"):
        vtkutils.get_cell_field_value(-1, view=vtk_view)
    with pytest.raises(ValueError, match="Can't retrieve cell id '9'"):
        vtkutils.get_cell_field_value(9, view=vtk_view)
    assert vtkutils.get_cell_field_value(0, view=vtk_view) == {
        0: [1.0],
        1: [1.0],
        2: [1.0],
        3: [1.0],
        4: [0.0],
        5: [0.0],
        6: [0.0],
        7: [0.0],
        8: [0.0],
        9: [0.0],
    }


def test_get_point_field_value(vtk_view: VTKView) -> None:
    """Test get_point_field_value."""
    # The scalar name is not given
    with pytest.raises(ValueError, match="Can't retrieve the value of a point"):
        vtkutils.get_point_field_value(0, view=vtk_view)
    # The scalar name is not correct
    vtk_view.vtk_scalar_name = "incorrect_name"
    with pytest.raises(ValueError, match="'incorrect_name' is not part of the dataset"):
        vtkutils.get_point_field_value(0, view=vtk_view)
    # The scalar name is correct
    vtk_view.vtk_scalar_name = "scalars"
    with pytest.raises(ValueError, match="'-1' is not a valid point id"):
        vtkutils.get_point_field_value(-1, view=vtk_view)
    with pytest.raises(ValueError, match="Can't retrieve point id '900'"):
        vtkutils.get_point_field_value(900, view=vtk_view)
    assert vtkutils.get_point_field_value(0, view=vtk_view) == [1.0]


def test_get_cell_type(vtk_view: VTKView) -> None:
    """Test get_cell_type."""
    # The scalar name is not given or is not correct -> not a problem because it doesn't need
    # the scalar field to retrieve the type of the cell
    assert vtkutils.get_cell_type(0, view=vtk_view) == vtkutils.CellType.QUADRATIC_TETRA
    vtk_view.vtk_scalar_name = "incorrect_name"
    assert vtkutils.get_cell_type(0, view=vtk_view) == vtkutils.CellType.QUADRATIC_TETRA
    # The scalar name is correct
    vtk_view.vtk_scalar_name = "scalars"
    assert vtkutils.get_cell_type(0, view=vtk_view) == vtkutils.CellType.QUADRATIC_TETRA
    # The vtk unstructured grid is not given
    vtk_view.vtk_ugrid = None
    with pytest.raises(ValueError, match="Can't retrieve the type of a cell"):
        vtkutils.get_cell_type(0, view=vtk_view)

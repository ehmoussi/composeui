"""Some utilities to use with the vtk view."""

from composeui.core import tools
from composeui.mainview.interfaces.imainview import IMainView
from composeui.vtk.ivtkview import IVTKView

from typing_extensions import overload
from vtkmodules.vtkCommonCore import vtkCommand, vtkObject
from vtkmodules.vtkCommonDataModel import vtkUnstructuredGrid
from vtkmodules.vtkIOLegacy import vtkUnstructuredGridReader, vtkUnstructuredGridWriter
from vtkmodules.vtkIOXML import vtkXMLUnstructuredGridReader, vtkXMLUnstructuredGridWriter

import enum
from pathlib import Path
from typing import Dict, List, Optional, Union


def get_cell_field_value(cell_id: int, *, view: IVTKView) -> Dict[int, List[float]]:
    """Get the value of the current field for the given cell id for each point id."""
    if view.vtk_ugrid is not None and view.vtk_scalar_name is not None:
        active_array = view.vtk_ugrid.GetPointData().GetArray(view.vtk_scalar_name)
        if active_array is not None:
            nb_cells = view.vtk_ugrid.GetNumberOfCells()
            if cell_id >= nb_cells:
                msg = (
                    f"The unstructured grid has only '{nb_cells}' cells. "
                    f"Can't retrieve cell id '{cell_id}'"
                )
                raise ValueError(msg)
            elif cell_id < 0:
                msg = f"'{cell_id}' is not a valid cell id."
                raise ValueError(msg)
            cell_field: Dict[int, List[float]] = {}
            cell = view.vtk_ugrid.GetCell(cell_id)
            for i in range(cell.GetNumberOfPoints()):
                point_id = cell.GetPointId(i)
                cell_field[point_id] = list(active_array.GetTuple(point_id))
            return cell_field
        else:
            msg = f"The field '{view.vtk_scalar_name}' is not part of the dataset."
            raise ValueError(msg)
    else:
        msg = _create_invalid_vtk_view_exception_message(
            view, "Can't retrieve the value of a cell"
        )
        raise ValueError(msg)


def get_point_field_value(point_id: int, *, view: IVTKView) -> List[float]:
    """Get the value of the current field for the given point id."""
    if view.vtk_ugrid is not None and view.vtk_scalar_name is not None:
        active_array = view.vtk_ugrid.GetPointData().GetArray(view.vtk_scalar_name)
        if active_array is not None:
            nb_points = view.vtk_ugrid.GetNumberOfPoints()
            if point_id >= nb_points:
                msg = (
                    f"The unstructured grid has only '{nb_points}' points. "
                    f"Can't retrieve point id '{point_id}'"
                )
                raise ValueError(msg)
            elif point_id < 0:
                msg = f"'{point_id}' is not a valid point id."
                raise ValueError(msg)
            return list(active_array.GetTuple(point_id))
        else:
            msg = f"The field '{view.vtk_scalar_name}' is not part of the dataset."
            raise ValueError(msg)
    else:
        msg = _create_invalid_vtk_view_exception_message(
            view, "Can't retrieve the value of a point"
        )
        raise ValueError(msg)


def get_cell_type(cell_id: int, *, view: IVTKView) -> "CellType":
    """Get type of the given cell id."""
    if view.vtk_ugrid is not None:
        cell = view.vtk_ugrid.GetCell(cell_id)
        return CellType(cell.GetCellType())
    else:
        msg = (
            "Can't retrieve the type of a cell.\n"
            " - The 'vtk_ugrid' attribute of the vtk view is None."
        )
        raise ValueError(msg)


@overload
def read_file(filepath: Path) -> Optional[vtkUnstructuredGrid]: ...
@overload
def read_file(filepath: Path, *, main_view: IMainView) -> Optional[vtkUnstructuredGrid]: ...
def read_file(
    filepath: Path, *, main_view: Optional[IMainView] = None
) -> Optional[vtkUnstructuredGrid]:
    """Read a vtk/vtu file and return a vtk unstructured grid."""
    vtk_ugrid: Optional[vtkUnstructuredGrid] = None
    if filepath.suffix == ".vtk":
        if main_view is None:
            vtk_ugrid = read_vtk_file(filepath)
        else:
            vtk_ugrid = read_vtk_file(filepath, main_view=main_view)
    elif filepath.suffix == ".vtu":
        if main_view is None:
            vtk_ugrid = read_vtu_file(filepath)
        else:
            vtk_ugrid = read_vtu_file(filepath, main_view=main_view)
    else:
        msg = "Can't read the given file"
        if main_view is None:
            raise ValueError(msg)
        tools.display_error_message(main_view, msg)
    return vtk_ugrid


@overload
def read_vtk_file(filepath: Path) -> Optional[vtkUnstructuredGrid]: ...
@overload
def read_vtk_file(
    filepath: Path, *, main_view: IMainView
) -> Optional[vtkUnstructuredGrid]: ...
def read_vtk_file(
    filepath: Path, *, main_view: Optional[IMainView] = None
) -> Optional[vtkUnstructuredGrid]:
    """Read a vtk file containing a vtkUnstructuredGrid."""
    assert filepath.suffix == ".vtk", "Only vtk files are allowed"
    reader = vtkUnstructuredGridReader()
    return _read_file(reader, filepath, main_view=main_view)


@overload
def read_vtu_file(filepath: Path) -> Optional[vtkUnstructuredGrid]: ...
@overload
def read_vtu_file(
    filepath: Path, *, main_view: IMainView
) -> Optional[vtkUnstructuredGrid]: ...
def read_vtu_file(
    filepath: Path, *, main_view: Optional[IMainView] = None
) -> Optional[vtkUnstructuredGrid]:
    """Read a vtu file containing a vtkUnstructuredGrid."""
    assert filepath.suffix == ".vtu", "Only vtu files are allowed"
    reader = vtkXMLUnstructuredGridReader()
    return _read_file(reader, filepath, main_view=main_view)


@overload
def write_file(vtk_ugrid: vtkUnstructuredGrid, filepath: Path) -> None: ...
@overload
def write_file(
    vtk_ugrid: vtkUnstructuredGrid, filepath: Path, *, main_view: IMainView
) -> None: ...
def write_file(
    vtk_ugrid: vtkUnstructuredGrid, filepath: Path, *, main_view: Optional[IMainView] = None
) -> None:
    """Write the given unstructured grid into the given filepath."""
    writer: Optional[Union[vtkXMLUnstructuredGridWriter, vtkUnstructuredGridWriter]] = None
    if filepath.suffix == ".vtu":
        writer = vtkXMLUnstructuredGridWriter()
    elif filepath.suffix == ".vtk":
        writer = vtkUnstructuredGridWriter()
    else:
        msg = "Can't write the given file. Only the extensions {.vtk, .vtu} are allowed"
        if main_view is None:
            raise ValueError(msg)
        tools.display_error_message(main_view, msg)
    if writer is not None:
        writer.SetFileName(str(filepath))
        if isinstance(writer, vtkXMLUnstructuredGridWriter):
            # TODO: Make this optional
            writer.SetDataModeToAscii()
            writer.SetCompressorTypeToZLib()
        writer.SetInputData(vtk_ugrid)
        writer.Update()
        writer.Write()


def _read_file(
    reader: Union[vtkXMLUnstructuredGridReader, vtkUnstructuredGridReader],
    filepath: Path,
    *,
    main_view: Optional[IMainView] = None,
) -> Optional[vtkUnstructuredGrid]:
    """Read the unstructured grid from the given reader."""
    if not filepath.exists():
        msg = f"The file '{filepath}' doesn't exists"
        if main_view is None:
            raise ValueError(msg)
        else:
            tools.display_error_message(main_view, msg)
        return None
    reader.SetFileName(str(filepath))
    error_observer = ErrorObserver()
    reader.AddObserver(vtkCommand.ErrorEvent, error_observer)
    reader.AddObserver(vtkCommand.WarningEvent, error_observer)
    reader.Update()
    output = reader.GetOutput()
    if not isinstance(output, vtkUnstructuredGrid):
        msg = "The given file doesn't contains an unstrctured grid"
        if main_view is None:
            raise ValueError(msg)
        else:
            tools.display_error_message(main_view, msg)
    elif error_observer.error_message is not None:
        msg = error_observer.error_message
        if main_view is None:
            raise ValueError(msg)
        else:
            tools.display_error_message(main_view, msg)
    else:
        if error_observer.warning_message is not None:
            msg = error_observer.warning_message
            if main_view is None:
                raise ValueError(msg)
            else:
                tools.display_warning_message(main_view, msg)
        return output
    return None


def _create_invalid_vtk_view_exception_message(view: IVTKView, action: str) -> str:
    """Create an error message if the view has invalid unstructured grid or scalar name."""
    msg = f"{action}. \n"
    if view.vtk_ugrid is None:
        msg += " - The 'vtk_ugrid' attribute of the vtk view is None."
    if view.vtk_scalar_name is None:
        msg += " - The 'vtk_scalar_name' attribute of the vtk view is None."
    return msg


class ErrorObserver:
    def __init__(self) -> None:
        self.error_message: Optional[str] = None
        self.warning_message: Optional[str] = None
        self.CallDataType = "string0"

    def __call__(self, caller: vtkObject, event: str, message: str) -> None:
        if event == "ErrorEvent":
            self.error_message = str(message)
        elif event == "WarningEvent":
            self.warning_message = str(message)

    def clear(self) -> None:
        self._error_message: Optional[str] = None
        self._warning_message: Optional[str] = None


class CellType(enum.IntEnum):
    # Linear cells
    EMPTY_CELL = 0
    VERTEX = 1
    POLY_VERTEX = 2
    LINE = 3
    POLY_LINE = 4
    TRIANGLE = 5
    TRIANGLE_STRIP = 6
    POLYGON = 7
    PIXEL = 8
    QUAD = 9
    TETRA = 10
    VOXEL = 11
    HEXAHEDRON = 12
    WEDGE = 13
    PYRAMID = 14
    PENTAGONAL_PRISM = 15
    HEXAGONAL_PRISM = 16
    # Quadratic, isoparametric cells
    QUADRATIC_EDGE = 21
    QUADRATIC_TRIANGLE = 22
    QUADRATIC_QUAD = 23
    QUADRATIC_POLYGON = 36
    QUADRATIC_TETRA = 24
    QUADRATIC_HEXAHEDRON = 25
    QUADRATIC_WEDGE = 26
    QUADRATIC_PYRAMID = 27
    BIQUADRATIC_QUAD = 28
    TRIQUADRATIC_HEXAHEDRON = 29
    QUADRATIC_LINEAR_QUAD = 30
    QUADRATIC_LINEAR_WEDGE = 31
    BIQUADRATIC_QUADRATIC_WEDGE = 32
    BIQUADRATIC_QUADRATIC_HEXAHEDRON = 33
    BIQUADRATIC_TRIANGLE = 34
    # Cubic, isoparametric cell
    CUBIC_LINE = 35
    # Special class of cells formed by convex group of points
    CONVEX_POINT_SET = 41
    # Polyhedron cell (consisting of polygonal faces)
    POLYHEDRON = 42
    # Higher order cells in parametric form
    PARAMETRIC_CURVE = 51
    PARAMETRIC_SURFACE = 52
    PARAMETRIC_TRI_SURFACE = 53
    PARAMETRIC_QUAD_SURFACE = 54
    PARAMETRIC_TETRA_REGION = 55
    PARAMETRIC_HEX_REGION = 56
    # Higher order cells
    HIGHER_ORDER_EDGE = 60
    HIGHER_ORDER_TRIANGLE = 61
    HIGHER_ORDER_QUAD = 62
    HIGHER_ORDER_POLYGON = 63
    HIGHER_ORDER_TETRAHEDRON = 64
    HIGHER_ORDER_WEDGE = 65
    HIGHER_ORDER_PYRAMID = 66
    HIGHER_ORDER_HEXAHEDRON = 67
    # Arbitrary order Lagrange elements (formulated separated from generic higher order cells)
    LAGRANGE_CURVE = 68
    LAGRANGE_TRIANGLE = 69
    LAGRANGE_QUADRILATERAL = 70
    LAGRANGE_TETRAHEDRON = 71
    LAGRANGE_HEXAHEDRON = 72
    LAGRANGE_WEDGE = 73
    LAGRANGE_PYRAMID = 74

    def __str__(self) -> str:
        return self.name

    def __repr__(self) -> str:
        return self.name

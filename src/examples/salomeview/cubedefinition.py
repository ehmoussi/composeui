"""Cube definition view."""

from composeui import form
from composeui.core import tools
from composeui.form.abstractformitems import AbstractFormItems
from composeui.form.iformview import (
    IFormView,
    IGroupBoxApplyFormView,
    ILabelComboBoxView,
    ILabelLineEditView,
    ILabelVector3DView,
)
from composeui.salomewrapper.core import displayer, geomwrapper
from composeui.store.sqlitestore import SqliteStore

import typing
from dataclasses import dataclass, field
from functools import partial
from typing import Any, List, Optional, Sequence, Tuple

if typing.TYPE_CHECKING:
    from examples.salomeview.app import Model
    from examples.salomeview.module1 import IModule1MainView


@dataclass(eq=False)
class ICubeParametersView(IGroupBoxApplyFormView["CubeDefinitionItems"]):
    name: ILabelLineEditView["CubeDefinitionItems"] = field(
        init=False, default_factory=ILabelLineEditView
    )
    point_1: ILabelVector3DView["CubeDefinitionItems"] = field(
        init=False, default_factory=ILabelVector3DView
    )
    point_2: ILabelVector3DView["CubeDefinitionItems"] = field(
        init=False, default_factory=ILabelVector3DView
    )


@dataclass(eq=False)
class ICubeDefinitionView(IFormView["CubeDefinitionItems"]):
    cube: ILabelComboBoxView["CubeDefinitionItems"] = field(
        init=False, default_factory=ILabelComboBoxView
    )
    parameters: ICubeParametersView = field(init=False, default_factory=ICubeParametersView)


class CubeQuery:
    def __init__(self, data: SqliteStore) -> None:
        self._data = data

    def add_cube(self) -> int:
        """Add a cube and return its id."""
        with self._data.get_connection() as db_conn:
            cursor = db_conn.execute(
                """--sql
                INSERT INTO cube DEFAULT VALUES
                """
            )
            db_conn.commit()
        if cursor.lastrowid is None:
            raise ValueError("The insertion of a new cube failed")
        return cursor.lastrowid

    def remove_cube(self, c_id: int) -> None:
        """Remove a cube with the given id."""
        with self._data.get_connection() as db_conn:
            db_conn.execute(
                """--sql
                DELETE FROM cube WHERE c_id=:c_id
                """,
                {"c_id": c_id},
            )
            db_conn.commit()

    def count(self) -> int:
        with self._data.get_connection() as db_conn:
            result = db_conn.execute(
                """--sql
                SELECT COUNT(*) FROM cube
                """
            ).fetchone()
        if result is not None:
            return int(result[0])
        return 0

    def get_id(self, index: int) -> int:
        """Get the id of the cube at the given index.

        The table is ordered using ROWID to have a consistent response
        """
        with self._data.get_connection() as db_conn:
            result = db_conn.execute(
                """--sql
                SELECT c_id FROM cube ORDER BY ROWID LIMIT 1 OFFSET :index
                """,
                {"index": index},
            ).fetchone()
        if result is not None:
            return int(result[0])
        raise IndexError("index out of range")

    def get_ids(self) -> List[int]:
        """Get the ids of all the cubes."""
        with self._data.get_connection() as db_conn:
            result = db_conn.execute(
                """--sql
                SELECT c_id FROM cube ORDER BY ROWID
                """
            ).fetchall()
        return [int(row["c_id"]) for row in result]

    def get_name(self, c_id: int) -> str:
        """Get the name of the cube with the given id."""
        with self._data.get_connection() as db_conn:
            result = db_conn.execute(
                """--sql
                SELECT name FROM cube WHERE c_id=:c_id
                """,
                {"c_id": c_id},
            ).fetchone()
        if result is not None:
            return str(result["name"])
        return ""

    def get_names(self) -> List[str]:
        """Get the names of all the cubes."""
        with self._data.get_connection() as db_conn:
            result = db_conn.execute(
                """--sql
                SELECT name FROM cube
                """
            ).fetchall()
        return [str(row["name"]) for row in result]

    def set_name(self, c_id: int, name: str) -> None:
        """Set the name of the cube with the given id."""
        with self._data.get_connection() as db_conn:
            db_conn.execute(
                """--sql
                UPDATE cube
                    SET name=:name
                    WHERE c_id=:c_id
                """,
                {"c_id": c_id, "name": name},
            )
            db_conn.commit()

    def get_point_1(self, c_id: int) -> Tuple[float, float, float]:
        """Get the point 1 of the cube with the given id."""
        with self._data.get_connection() as db_conn:
            result = db_conn.execute(
                """--sql
                SELECT p_1_x, p_1_y, p_1_z FROM cube WHERE c_id=:c_id
                """,
                {"c_id": c_id},
            ).fetchone()
        if result is not None:
            return (float(result["p_1_x"]), float(result["p_1_y"]), float(result["p_1_z"]))
        return (0.0, 0.0, 0.0)

    def set_point_1(self, c_id: int, x: float, y: float, z: float) -> None:
        """Set the point 1 of the cube with the given id."""
        with self._data.get_connection() as db_conn:
            db_conn.execute(
                """--sql
                UPDATE cube
                    SET p_1_x=:x, p_1_y=:y, p_1_z=:z
                    WHERE c_id=:c_id
                """,
                {"c_id": c_id, "x": x, "y": y, "z": z},
            )
            db_conn.commit()

    def get_point_2(self, c_id: int) -> Tuple[float, float, float]:
        """Get the point 2 of the cube with the given id."""
        with self._data.get_connection() as db_conn:
            result = db_conn.execute(
                """--sql
                SELECT p_2_x, p_2_y, p_2_z FROM cube WHERE c_id=:c_id
                """,
                {"c_id": c_id},
            ).fetchone()
        if result is not None:
            return (float(result["p_2_x"]), float(result["p_2_y"]), float(result["p_2_z"]))
        return (0.0, 0.0, 0.0)

    def set_point_2(self, c_id: int, x: float, y: float, z: float) -> None:
        """Set the point 2 of the cube with the given id."""
        with self._data.get_connection() as db_conn:
            db_conn.execute(
                """--sql
                UPDATE cube
                    SET p_2_x=:x, p_2_y=:y, p_2_z=:z
                    WHERE c_id=:c_id
                """,
                {"c_id": c_id, "x": x, "y": y, "z": z},
            )
            db_conn.commit()

    def get_entry(self, c_id: int) -> Optional[str]:
        """Get the entry of the cube with the given id."""
        with self._data.get_connection() as db_conn:
            result = db_conn.execute(
                """--sql
                SELECT entry FROM cube WHERE c_id=:c_id
                """,
                {"c_id": c_id},
            ).fetchone()
        if result is not None and result["entry"] is not None:
            return str(result["entry"])
        return None

    def set_entry(self, c_id: int, entry: Optional[str]) -> None:
        """Set the salome entry of the cube with the given id."""
        with self._data.get_connection() as db_conn:
            db_conn.execute(
                """--sql
                UPDATE cube
                    SET entry=:entry
                    WHERE c_id=:c_id
                """,
                {"c_id": c_id, "entry": entry},
            )
            db_conn.commit()


class CubeDefinitionItems(AbstractFormItems["Model", "ICubeDefinitionView"]):
    def __init__(self, model: "Model", view: ICubeDefinitionView) -> None:
        super().__init__(model, view)
        self._current_id: Optional[int] = None

    @property
    def current_id(self) -> Optional[int]:
        return self._current_id

    def is_enabled(self, field: str, _: Tuple[str, ...] = ()) -> bool:
        # disable the fields if "New Cube" or an existing cube is not selected
        return field in ("", "cube") or self._view.cube.field_view.current_index != -1

    def get_value(self, field: str, _: Tuple[str, ...] = ()) -> Any:
        if field == "cube":
            return self._current_id
        if self._current_id is not None:
            if field == "name":
                return self._model.cube_query.get_name(self._current_id)
            elif field == "point_1":
                return self._model.cube_query.get_point_1(self._current_id)
            elif field == "point_2":
                return self._model.cube_query.get_point_2(self._current_id)
        return None

    def set_value(self, field: str, value: Any, _: Tuple[str, ...] = ()) -> bool:
        if field == "cube":
            self._current_id = self.to_int_value(value)
            return True
        if self._current_id is None:
            self._current_id = self._model.cube_query.add_cube()
        if field == "name":
            self._model.cube_query.set_name(self._current_id, str(value))
            return True
        elif field in ("point_1", "point_2"):
            assert isinstance(value, tuple), f"Incorrect value for {field}"
            assert len(value) == 3, f"Incorrect number of values for {field}"
            x, y, z = map(self.to_float_value, value)
            if x is None or y is None or z is None:
                return False
            if field == "point_1":
                self._model.cube_query.set_point_1(self._current_id, x, y, z)
            if field == "point_2":
                self._model.cube_query.set_point_2(self._current_id, x, y, z)
            return True
        return False

    def acceptable_values(
        self, field: str, _: Tuple[str, ...] = ()
    ) -> Optional[Sequence[Any]]:
        if field == "cube":
            return [None, *self._model.cube_query.get_ids()]
        return None

    def acceptable_displayed_values(
        self, field: str, _: Tuple[str, ...] = ()
    ) -> Optional[Sequence[str]]:
        if field == "cube":
            return ["New Cube", *self._model.cube_query.get_names()]
        return None


def generate_cube(
    *, view: ICubeParametersView, main_view: "IModule1MainView", model: "Model"
) -> None:
    """Generate a cube from the data of the view using GEOM module."""
    # retrieve the data
    name = view.name.field_view.text
    x_1, y_1, z_1 = view.point_1.field_view.values
    x_2, y_2, z_2 = view.point_2.field_view.values
    # check the data
    if name == "":
        tools.display_error_message(main_view, "Can't generate a cube with an empty name.")
        return
    if x_1 is None or y_1 is None or z_1 is None:
        tools.display_error_message(
            main_view, "Can't generate a cube with the given coordinates of the first point."
        )
        return
    if x_2 is None or y_2 is None or z_2 is None:
        tools.display_error_message(
            main_view, "Can't generate a cube with the given coordinates of the first point."
        )
        return
    # build the cube in GEOM
    try:
        entry = build_cube_geometry(name, x_1, y_1, z_1, x_2, y_2, z_2)
    except RuntimeError as e:
        tools.display_error_message(main_view, f"Failed to build the geometry:\n{e.args[0]}.")
        return
    # update the model
    if view.items is not None and view.items.current_id is not None:
        # remove the old entry if it exists
        old_entry = model.cube_query.get_entry(view.items.current_id)
        if old_entry is not None:
            geomwrapper.remove_geom_object_from_study(old_entry)
        # save its entry
        model.cube_query.set_entry(view.items.current_id, entry)
    # update the views
    tools.update_view_with_dependencies(main_view.salome_tree)
    displayer.display_entity(entry)
    displayer.add_to_selection([entry])


def build_cube_geometry(
    name: str, x_1: float, y_1: float, z_1: float, x_2: float, y_2: float, z_2: float
) -> str:
    """Build a cube using the GEOM Module and returns its entry in the salome study."""
    import salome.geom.geomBuilder

    geompy = salome.geom.geomBuilder.New()
    point_1 = geompy.MakeVertex(x_1, y_1, z_1)
    point_2 = geompy.MakeVertex(x_2, y_2, z_2)
    cube = geompy.MakeBoxTwoPnt(point_1, point_2)
    entry = geompy.addToStudy(cube, name)
    return str(entry)


def initialize_cube_definition(view: ICubeDefinitionView, model: "Model") -> None:
    form.initialize_form_view(view, CubeDefinitionItems(model, view))
    view.cube.field_view.dependencies.append(view.parameters)


def connect_cube_definition(view: ICubeDefinitionView) -> None:
    view.parameters.apply_clicked += [
        generate_cube,
        partial(tools.update_view_with_dependencies, view.cube.field_view),
    ]

from composeui.items.core.itemsutils import DelegateProps, FloatDelegateProps
from composeui.items.tree.abstracttreeitems import AbstractTreeItems
from composeui.items.tree.itreeview import ExportTreeOptions, TreeGroupView
from composeui.store.sqlitestore import SqliteStore

from typing import TYPE_CHECKING, Any, List, Optional, Tuple

if TYPE_CHECKING:
    from examples.treeview.app import Model
    from examples.treeview.example import ExampleMainView

ILinesView = TreeGroupView["LinesItems"]


class LinesQuery:
    def __init__(self, data: SqliteStore) -> None:
        self._data = data

    def is_expanded(self, index: int) -> bool:
        l_id = self.get_line_id(index)
        with self._data.get_connection() as db_conn:
            result = db_conn.execute(
                "SELECT is_expanded FROM line_tree WHERE l_id=:l_id",
                {"l_id": l_id},
            ).fetchone()
        if result is not None:
            return bool(result["is_expanded"])
        else:
            return True

    def set_expansion_status(self, index: int, is_expanded: bool) -> None:
        l_id = self.get_line_id(index)
        with self._data.get_connection() as db_conn:
            db_conn.execute(
                "UPDATE line_tree SET is_expanded=:is_expanded WHERE l_id=:l_id",
                {"l_id": l_id, "is_expanded": is_expanded},
            )
            db_conn.commit()

    def insert_line(self, index: int, name: str = "line") -> int:
        """Insert a line at the given index and return its id."""
        with self._data.get_connection() as db_conn:
            # to keep the lines sorted
            db_conn.execute(
                "UPDATE line SET l_index=l_index+1 WHERE l_index >= :l_index",
                {"l_index": index},
            )
            cursor = db_conn.execute(
                "INSERT INTO line(l_index, l_name) VALUES(:l_index, :l_name)",
                {"l_index": index, "l_name": name},
            )
            if cursor.lastrowid is None:
                raise ValueError("Unexpected failure occurred during the insertion.")
            if name == "line":
                db_conn.execute(
                    "UPDATE line SET l_name=:l_name WHERE l_id=:l_id",
                    {"l_id": cursor.lastrowid, "l_name": f"{name} {cursor.lastrowid}"},
                )
            db_conn.commit()
        return cursor.lastrowid

    def remove_line(self, line_index: int) -> None:
        """Remove the line at the given index."""
        l_id = self.get_line_id(line_index)
        with self._data.get_connection() as db_conn:
            db_conn.execute(
                "DELETE FROM line WHERE l_id=:l_id",
                {"l_id": l_id},
            )
            db_conn.execute(
                "UPDATE line SET l_index=l_index-1 WHERE l_index > :l_index",
                {"l_index": line_index},
            )
            db_conn.commit()

    def count_lines(self) -> int:
        """Get the number of lines."""
        with self._data.get_connection() as db_conn:
            result = db_conn.execute(
                "SELECT COUNT(*) FROM line",
            ).fetchone()
        if result is not None:
            return int(result[0])
        else:
            return 0

    def get_line_name(self, line_index: int) -> str:
        """Get the name of the line at the given index."""
        l_id = self.get_line_id(line_index)
        with self._data.get_connection() as db_conn:
            result = db_conn.execute(
                "SELECT l_name FROM line WHERE l_id=:l_id",
                {"l_id": l_id},
            ).fetchone()
        if result is not None:
            return str(result["l_name"])
        else:
            raise IndexError

    def set_line_name(self, line_index: int, name: str) -> None:
        """Set the name of the line at the given index."""
        l_id = self.get_line_id(line_index)
        with self._data.get_connection() as db_conn:
            db_conn.execute(
                "UPDATE line SET l_name=:l_name WHERE l_id=:l_id",
                {"l_id": l_id, "l_name": name},
            )
            db_conn.commit()

    def insert_point(
        self,
        line_index: int,
        index: int,
        name: str = "point",
        x: float = 0.0,
        y: float = 0.0,
        z: float = 0.0,
    ) -> int:
        """Insert a point at the given index and return its id."""
        line_id = self.get_line_id(line_index)
        with self._data.get_connection() as db_conn:
            # to keep the points sorted
            db_conn.execute(
                "UPDATE point SET p_index=p_index + 1 WHERE p_index>=:p_index AND l_id=:l_id",
                {"l_id": line_id, "p_index": index},
            )
            cursor = db_conn.execute(
                """--sql
                INSERT INTO point(l_id, p_index, p_name, x, y, z)
                VALUES(:l_id, :p_index, :p_name, :x, :y, :z)
                """,
                {"l_id": line_id, "p_index": index, "p_name": name, "x": x, "y": y, "z": z},
            )
            if cursor.lastrowid is None:
                raise ValueError("Unexpected failure occurred during the insertion.")
            if name == "point":
                db_conn.execute(
                    "UPDATE point SET p_name=:p_name WHERE p_id=:p_id",
                    {"p_id": cursor.lastrowid, "p_name": f"{name} {cursor.lastrowid}"},
                )
            db_conn.commit()
        return cursor.lastrowid

    def remove_point(self, line_index: int, index: int) -> None:
        """Remove the point at the given index."""
        l_id = self.get_line_id(line_index)
        with self._data.get_connection() as db_conn:
            db_conn.execute(
                "DELETE FROM point WHERE p_index=:p_index AND l_id=:l_id",
                {"p_index": index, "l_id": l_id},
            )
            db_conn.execute(
                "UPDATE point SET p_index=p_index - 1 WHERE p_index>:p_index AND l_id=:l_id",
                {"l_id": l_id, "p_index": index},
            )
            db_conn.commit()

    def count_points(self, line_index: int) -> int:
        """Get the number of points."""
        l_id = self.get_line_id(line_index)
        with self._data.get_connection() as db_conn:
            result = db_conn.execute(
                "SELECT COUNT(*) FROM point WHERE l_id=:l_id",
                {"l_id": l_id},
            ).fetchone()
        if result is not None:
            return int(result[0])
        else:
            return 0

    def get_point(self, line_index: int, index: int) -> Tuple[str, float, float, float]:
        """Get the name and the coordinates of the point at the given index."""
        p_id = self.get_point_id(line_index, index)
        with self._data.get_connection() as db_conn:
            result = db_conn.execute(
                "SELECT p_name, x, y, z FROM point WHERE p_id=:p_id",
                {"p_id": p_id},
            ).fetchone()
        if result is not None:
            return (
                str(result["p_name"]),
                float(result["x"]),
                float(result["y"]),
                float(result["z"]),
            )
        else:
            raise IndexError

    def get_point_name(self, line_index: int, index: int) -> str:
        """Get the name of the point at the given index."""
        p_id = self.get_point_id(line_index, index)
        with self._data.get_connection() as db_conn:
            result = db_conn.execute(
                "SELECT p_name FROM point WHERE p_id=:p_id",
                {"p_id": p_id},
            ).fetchone()
        if result is not None:
            return str(result["p_name"])
        else:
            raise IndexError

    def set_point_name(self, line_index: int, index: int, name: str) -> None:
        """Set the name of the point at the given index."""
        p_id = self.get_point_id(line_index, index)
        with self._data.get_connection() as db_conn:
            db_conn.execute(
                "UPDATE point SET p_name=:p_name WHERE p_id=:p_id",
                {"p_id": p_id, "p_name": name},
            )
            db_conn.commit()

    def get_x(self, line_index: int, index: int) -> float:
        """Get the x coordinate of the point at the given index."""
        p_id = self.get_point_id(line_index, index)
        with self._data.get_connection() as db_conn:
            result = db_conn.execute(
                "SELECT x FROM point WHERE p_id=:p_id",
                {"p_id": p_id},
            ).fetchone()
        if result is not None:
            return float(result["x"])
        else:
            raise IndexError

    def set_x(self, line_index: int, index: int, x: float) -> None:
        """Set the x coordinate of the point at the given index."""
        p_id = self.get_point_id(line_index, index)
        with self._data.get_connection() as db_conn:
            db_conn.execute(
                "UPDATE point SET x=:x WHERE p_id=:p_id",
                {"p_id": p_id, "x": x},
            )
            db_conn.commit()

    def get_y(self, line_index: int, index: int) -> float:
        """Get the y coordinate of the point at the given index."""
        p_id = self.get_point_id(line_index, index)
        with self._data.get_connection() as db_conn:
            result = db_conn.execute(
                "SELECT y FROM point WHERE p_id=:p_id",
                {"p_id": p_id},
            ).fetchone()
        if result is not None:
            return float(result["y"])
        else:
            raise IndexError

    def set_y(self, line_index: int, index: int, y: float) -> None:
        """Set the y coordinate of the point at the given index."""
        p_id = self.get_point_id(line_index, index)
        with self._data.get_connection() as db_conn:
            db_conn.execute(
                "UPDATE point SET y=:y WHERE p_id=:p_id",
                {"p_id": p_id, "y": y},
            )
            db_conn.commit()

    def get_z(self, line_index: int, index: int) -> float:
        """Get the z coordinate of the point at the given index."""
        p_id = self.get_point_id(line_index, index)
        with self._data.get_connection() as db_conn:
            result = db_conn.execute(
                "SELECT z FROM point WHERE p_id=:p_id",
                {"p_id": p_id},
            ).fetchone()
        if result is not None:
            return float(result["z"])
        else:
            raise IndexError

    def set_z(self, line_index: int, index: int, z: float) -> None:
        """Set the z coordinate of the point at the given index."""
        p_id = self.get_point_id(line_index, index)
        with self._data.get_connection() as db_conn:
            db_conn.execute(
                "UPDATE point SET z=:z WHERE p_id=:p_id",
                {"p_id": p_id, "z": z},
            )
            db_conn.commit()

    def get_point_id(self, line_index: int, index: int) -> int:
        l_id = self.get_line_id(line_index)
        with self._data.get_connection() as db_conn:
            result = db_conn.execute(
                "SELECT p_id FROM point WHERE p_index=:p_index AND l_id=:l_id",
                {"p_index": index, "l_id": l_id},
            ).fetchone()
        if result is not None:
            return int(result["p_id"])
        else:
            msg = f"Index out of range: {index}"
            raise IndexError(msg)

    def get_line_id(self, index: int) -> int:
        with self._data.get_connection() as db_conn:
            result = db_conn.execute(
                "SELECT l_id FROM line WHERE l_index=:l_index",
                {"l_index": index},
            ).fetchone()
        if result is not None:
            return int(result["l_id"])
        else:
            raise IndexError("Index out of range")

    def get_ordered_point_ids(self, line_id: int) -> List[int]:
        """Get the ids by the index order."""
        with self._data.get_connection() as db_conn:
            result = db_conn.execute(
                "SELECT p_id FROM point ORDER BY p_index WHERE l_id=:line_id",
                {"l_id": line_id},
            ).fetchall()
        return [int(row["p_id"]) for row in result if row is not None]

    def get_ordered_line_ids(self) -> List[int]:
        """Get the ids by the index order."""
        with self._data.get_connection() as db_conn:
            result = db_conn.execute("SELECT l_id FROM line ORDER BY l_index").fetchall()
        return [int(row["l_id"]) for row in result if row is not None]


class LinesItems(AbstractTreeItems["Model"]):
    def __init__(self, view: "ILinesView", model: "Model") -> None:
        super().__init__(view, model, title="Lines")
        self._titles = ["Name", "X", "Y", "Z", "Id"]

    def get_exported_column_indices(self, parent_rows: Tuple[int, ...] = ()) -> List[int]:
        if len(parent_rows) == 0:
            columns = [0]
            if self._model.is_debug:
                columns.append(4)
            return columns
        else:
            return super().get_exported_column_indices(parent_rows)

    def get_nb_columns(self) -> int:
        if self._model.is_debug:
            return len(self._titles)
        else:
            return len(self._titles) - 1

    def get_column_title(self, column: int) -> str:
        return self._titles[column]

    def get_nb_rows(self, parent_rows: Tuple[int, ...] = ()) -> int:
        if len(parent_rows) == 0:
            return self._model.lines_query.count_lines()
        elif len(parent_rows) == 1:
            return self._model.lines_query.count_points(parent_rows[0])
        else:
            return 0

    def insert(self, row: int, parent_rows: Tuple[int, ...] = ()) -> Optional[Tuple[int, ...]]:
        if len(parent_rows) == 0:
            self._model.lines_query.insert_line(row)
            return (row,)
        elif len(parent_rows) == 1:
            self._model.lines_query.insert_point(parent_rows[0], row)
            return (*parent_rows, row)
        else:
            return ()

    def remove(self, row: int, parent_rows: Tuple[int, ...] = ()) -> Optional[Tuple[int, ...]]:
        if len(parent_rows) == 0:
            self._model.lines_query.remove_line(row)
        elif len(parent_rows) == 1:
            self._model.lines_query.remove_point(parent_rows[0], row)
        return super().remove(row, parent_rows)

    def get_data(self, row: int, column: int, parent_rows: Tuple[int, ...] = ()) -> str:
        if len(parent_rows) == 0:
            if column == 0:
                return self._model.lines_query.get_line_name(row)
            elif column == 4:
                return str(self._model.lines_query.get_line_id(row))
        elif len(parent_rows) == 1:
            line_row = parent_rows[0]
            if column == 0:
                return self._model.lines_query.get_point_name(line_row, row)
            elif column == 1:
                return self.display_float(self._model.lines_query.get_x(line_row, row), 2)
            elif column == 2:
                return self.display_float(self._model.lines_query.get_y(line_row, row), 2)
            elif column == 3:
                return self.display_float(self._model.lines_query.get_z(line_row, row), 2)
            elif column == 4:
                return str(self._model.lines_query.get_point_id(line_row, row))
        return super().get_data(row, column, parent_rows)

    def get_edit_data(self, row: int, column: int, parent_rows: Tuple[int, ...] = ()) -> Any:
        if len(parent_rows) == 1:
            line_row = parent_rows[0]
            if column == 1:
                return self._model.lines_query.get_x(line_row, row)
            elif column == 2:
                return self._model.lines_query.get_y(line_row, row)
            elif column == 3:
                return self._model.lines_query.get_z(line_row, row)
        return super().get_edit_data(row, column, parent_rows)

    def is_editable(self, row: int, column: int, parent_rows: Tuple[int, ...] = ()) -> bool:
        if len(parent_rows) == 0:
            return column == 0
        return column < 4

    def set_data(
        self, row: int, column: int, value: str, parent_rows: Tuple[int, ...] = ()
    ) -> bool:
        if len(parent_rows) == 0 and column == 0:
            self._model.lines_query.set_line_name(row, str(value))
            return True
        elif len(parent_rows) == 1:
            line_row = parent_rows[0]
            if column == 0:
                self._model.lines_query.set_point_name(line_row, row, str(value))
                return True
            elif 1 <= column <= 3:
                float_value = self.to_float_value(value, 0.0)
                if float_value is not None:
                    if column == 1:
                        self._model.lines_query.set_x(line_row, row, float_value)
                    elif column == 2:
                        self._model.lines_query.set_y(line_row, row, float_value)
                    elif column == 3:
                        self._model.lines_query.set_z(line_row, row, float_value)
                    return True
        return False

    def get_delegate_props(
        self, row: int, column: int, parent_rows: Tuple[int, ...] = ()
    ) -> Optional[DelegateProps]:
        if 1 <= column <= 3:
            return FloatDelegateProps()
        return super().get_delegate_props(row, column, parent_rows)

    def get_expand_positions(self) -> List[Tuple[int, ...]]:
        return [
            (row,)
            for row in range(self.get_nb_rows())
            if self._model.lines_query.is_expanded(row)
        ]

    def set_expanded(
        self, row: int, is_expanded: bool, parent_rows: Tuple[int, ...] = ()
    ) -> None:
        if len(parent_rows) == 0:
            self._model.lines_query.set_expansion_status(row, is_expanded)


def initialize_lines(
    view: TreeGroupView[LinesItems], main_view: "ExampleMainView", model: "Model"
) -> None:
    view.is_visible = True
    view.title = "Lines"
    view.has_import = True
    view.has_export = True
    view.has_add = True
    view.has_remove = True
    view.has_pagination = True
    view.can_select_items = True
    view.export_options = ExportTreeOptions.ASK_WITH_PARENT_SHEET_NAMES
    view.items = LinesItems(view, model)

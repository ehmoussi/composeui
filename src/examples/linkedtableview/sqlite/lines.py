from composeui.items.core.itemsutils import DelegateProps, FloatDelegateProps
from composeui.items.linkedtable.ilinkedtableview import LinkedTableView
from composeui.items.table.abstracttableitems import AbstractTableItems
from composeui.items.table.itableview import TableView
from composeui.items.tree.itreeview import ExportTreeOptions
from composeui.store.sqlitestore import SqliteStore

from typing import TYPE_CHECKING, Any, Generator, List, Optional

if TYPE_CHECKING:
    from examples.linkedtableview.sqlite.app import Model
    from examples.linkedtableview.sqlite.example import ExampleMainView


class LinesQuery:
    def __init__(self, data: SqliteStore) -> None:
        self._data = data

    def add_line(self) -> int:
        return self.insert_line(-1)

    def insert_line(self, index: int, name: str = "line") -> int:
        """Insert a line at the given index and return its id."""
        if index < 0:
            nb_lines = self.count_lines()
            index = max(nb_lines + index + 1, 0)
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
        with self._data.get_connection() as db_conn:
            db_conn.execute(
                "DELETE FROM line WHERE l_index=:l_index",
                {"l_index": line_index},
            )
            db_conn.execute(
                "UPDATE line SET l_index=l_index-1 WHERE l_index > :l_index",
                {"l_index": line_index},
            )
            db_conn.commit()

    def remove_all(self) -> None:
        with self._data.get_connection() as db_conn:
            db_conn.execute("DELETE FROM line")
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

    def add_point(self, line_index: int) -> int:
        return self.insert_point(line_index, -1)

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
        if index < 0:
            nb_points = self.count_points(line_index)
            index = max(nb_points + index + 1, 0)
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
        p_id = self.get_point_id(line_index, index)
        with self._data.get_connection() as db_conn:
            db_conn.execute(
                "DELETE FROM point WHERE p_id=:p_id",
                {"p_id": p_id},
            )
            db_conn.execute(
                "UPDATE point SET p_index=p_index - 1 WHERE p_index>:p_index AND l_id=:l_id",
                {"l_id": l_id, "p_index": index},
            )
            db_conn.commit()

    def count_points(self, line_index: int) -> int:
        """Get the number of points."""
        line_id = self.get_line_id(line_index)
        with self._data.get_connection() as db_conn:
            result = db_conn.execute(
                "SELECT COUNT(*) FROM point WHERE l_id=:l_id",
                {"l_id": line_id},
            ).fetchone()
        if result is not None:
            return int(result[0])
        else:
            return 0

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
            raise IndexError("Index out of range")

    def get_line_id(self, index: int) -> int:
        with self._data.get_connection() as db_conn:
            result = db_conn.execute(
                "SELECT l_id FROM line WHERE l_index=:l_index",
                {"l_index": index},
            ).fetchone()
        if result is not None:
            return int(result["l_id"])
        else:
            msg = f"Index out of range: {index}"
            raise IndexError(msg)

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


class LinesItems(AbstractTableItems["Model"]):
    def __init__(self, view: TableView["LinesItems"], model: "Model") -> None:
        super().__init__(view, model)
        self._titles = ["Name", "Id"]

    def get_nb_columns(self) -> int:
        if self._model.is_debug:
            return len(self._titles)
        else:
            return len(self._titles) - 1

    def get_column_title(self, column: int) -> str:
        return self._titles[column]

    def get_exported_column_indices(self) -> List[int]:
        return [0]

    def get_nb_rows(self) -> int:
        return self._model.lines_query.count_lines()

    def insert(self, row: int) -> Optional[int]:
        self._model.lines_query.insert_line(row)
        return row

    def remove(self, row: int) -> Optional[int]:
        self._model.lines_query.remove_line(row)
        return super().remove(row)

    def remove_all(self) -> None:
        self._model.lines_query.remove_all()

    def get_data(self, row: int, column: int) -> Any:
        if column == 0:
            return self._model.lines_query.get_line_name(row)
        elif column == 1:
            return self._model.lines_query.get_line_id(row)
        return super().get_data(row, column)

    def is_editable(self, row: int, column: int) -> bool:
        return column == 0

    def set_data(self, row: int, column: int, value: str) -> bool:
        if column == 0:
            self._model.lines_query.set_line_name(row, str(value))
            return True
        return False


class PointsItems(AbstractTableItems["Model"]):
    def __init__(self, view: TableView["PointsItems"], model: "Model") -> None:
        super().__init__(view, model)
        self._titles = ["Name", "X", "Y", "Z", "Id"]

    def get_lines_items(self) -> LinesItems:
        assert len(self._dependencies) == 1, "LinesItems is missing as a dependency"
        assert isinstance(
            self._dependencies[0], LinesItems
        ), "The dependency is not of type LinesItems"
        return self._dependencies[0]

    def get_current_line_index(self) -> int:
        if len(self._dependencies) > 0:
            lines_items = self.get_lines_items()
            selected_rows = lines_items.get_selected_rows()
            if len(selected_rows) > 0:
                return selected_rows[-1]
        return -1

    def can_enable_table(self) -> bool:
        return self.get_current_line_index() != -1

    def get_exported_column_indices(self) -> List[int]:
        return list(range(4))

    def get_nb_columns(self) -> int:
        if self._model.is_debug:
            return len(self._titles)
        else:
            return len(self._titles) - 1

    def get_column_title(self, column: int) -> str:
        return self._titles[column]

    def get_nb_rows(self) -> int:
        line_index = self.get_current_line_index()
        if line_index != -1:
            return self._model.lines_query.count_points(line_index)
        else:
            return 0

    def insert(self, row: int) -> Optional[int]:
        self._model.lines_query.insert_point(self.get_current_line_index(), row)
        return row

    def remove(self, row: int) -> Optional[int]:
        self._model.lines_query.remove_point(self.get_current_line_index(), row)
        return super().remove(row)

    def get_data(self, row: int, column: int) -> str:
        line_row = self.get_current_line_index()
        if column == 0:
            return self._model.lines_query.get_point_name(line_row, row)
        elif 1 <= column <= 3:
            if column == 1:
                value = self._model.lines_query.get_x(line_row, row)
            elif column == 2:
                value = self._model.lines_query.get_y(line_row, row)
            else:
                value = self._model.lines_query.get_z(line_row, row)
            return self.display_float(value, nb_decimals=2)
        elif column == 4:
            return str(self._model.lines_query.get_point_id(line_row, row))
        return super().get_data(row, column)

    def get_edit_data(self, row: int, column: int) -> Any:
        line_row = self.get_current_line_index()
        if column == 1:
            return self._model.lines_query.get_x(line_row, row)
        elif column == 2:
            return self._model.lines_query.get_y(line_row, row)
        elif column == 3:
            return self._model.lines_query.get_z(line_row, row)
        return super().get_edit_data(row, column)

    def is_editable(self, row: int, column: int) -> bool:
        return column < 4

    def set_data(self, row: int, column: int, value: str) -> bool:
        line_row = self.get_current_line_index()
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

    def get_delegate_props(self, row: int, column: int) -> Optional[DelegateProps]:
        if 1 <= column <= 3:
            return FloatDelegateProps()
        return super().get_delegate_props(row, column)

    def get_title(self) -> str:
        line_index = self.get_current_line_index()
        if line_index != -1:
            return self._model.lines_query.get_line_name(line_index)
        else:
            return ""

    def iter_trigger_dependencies(self) -> Generator[None, None, None]:
        lines_items = self.get_lines_items()
        for row in range(lines_items.get_nb_rows()):
            lines_items.set_selected_rows([row])
            yield


def initialize_lines(
    view: LinkedTableView[LinesItems, PointsItems],
    main_view: "ExampleMainView",
    model: "Model",
) -> None:
    view.has_import = True
    view.has_export = True
    view.export_options = ExportTreeOptions.ASK_WITH_PARENT_SHEET_NAMES
    view.master_table.items = LinesItems(view.master_table, model)
    view.detail_table.items = PointsItems(view.detail_table, model)
    view.detail_table.items.add_dependency(view.master_table.items)

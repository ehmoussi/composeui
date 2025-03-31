from composeui.items.core.itemsutils import DelegateProps, FloatDelegateProps
from composeui.items.table.abstracttableitems import AbstractTableItems
from composeui.items.table.tableview import TableView
from composeui.store.sqlitestore import SqliteStore

from typing_extensions import TypeAlias

from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from examples.tableview.app import Model
    from examples.tableview.example import ExampleMainView

IPointsView: TypeAlias = TableView["PointsItems"]


class PointsQuery:
    def __init__(self, data: SqliteStore) -> None:
        self._data = data

    def add(self) -> int:
        return self.insert(-1)

    def insert(
        self,
        index: int,
        name: str = "point",
        x: float = 0.0,
        y: float = 0.0,
        z: float = 0.0,
    ) -> int:
        """Insert a point at the given index and return its id."""
        nb_points = self.count()
        if index < 0:
            index = max(nb_points - index + 1, 0)
        elif index > nb_points:
            index = nb_points
        with self._data.get_connection() as db_conn:
            # update the p_index of the other points
            db_conn.execute(
                "UPDATE points SET p_index=p_index+1 WHERE p_index >= :index",
                {"index": index},
            )
            # insert the point
            cursor = db_conn.execute(
                """
                INSERT INTO points(p_index, p_name, x, y, z)
                VALUES(:p_index, :p_name, :x, :y, :z)
                """,
                {"p_index": index, "p_name": name, "x": x, "y": y, "z": z},
            )
            if cursor.lastrowid is None:
                db_conn.rollback()
                raise ValueError("Unexpected failure occurred during the insertion.")
            # update the name to use the id if the name is just point
            if name == "point":
                db_conn.execute(
                    "UPDATE points SET p_name=:p_name WHERE p_id=:p_id",
                    {"p_id": cursor.lastrowid, "p_name": f"{name} {cursor.lastrowid}"},
                )
            db_conn.commit()
        return cursor.lastrowid

    def remove(self, index: int) -> None:
        """Remove the point at the given index."""
        with self._data.get_connection() as db_conn:
            db_conn.execute(
                "DELETE FROM points WHERE p_index=:p_index",
                {"p_index": index},
            )
            # update the p_index of the other points
            db_conn.execute(
                "UPDATE points SET p_index=p_index-1 WHERE p_index >= :index",
                {"index": index},
            )
            db_conn.commit()

    def count(self) -> int:
        """Get the number of points."""
        with self._data.get_connection() as db_conn:
            result = db_conn.execute(
                "SELECT COUNT(*) FROM points",
            ).fetchone()
        if result is not None:
            return int(result[0])
        else:
            return 0

    def get_name(self, index: int) -> str:
        """Get the name of the point at the given index."""
        with self._data.get_connection() as db_conn:
            result = db_conn.execute(
                "SELECT p_name FROM points WHERE p_index=:p_index",
                {"p_index": index},
            ).fetchone()
        if result is not None:
            return str(result["p_name"])
        else:
            raise IndexError

    def set_name(self, index: int, name: str) -> None:
        """Set the name of the point at the given index."""
        with self._data.get_connection() as db_conn:
            db_conn.execute(
                "UPDATE points SET p_name=:p_name WHERE p_index=:p_index",
                {"p_index": index, "p_name": name},
            )
            db_conn.commit()

    def get_x(self, index: int) -> float:
        """Get the x coordinate of the point at the given index."""
        with self._data.get_connection() as db_conn:
            result = db_conn.execute(
                "SELECT x FROM points WHERE p_index=:p_index",
                {"p_index": index},
            ).fetchone()
        if result is not None:
            return float(result["x"])
        else:
            raise IndexError

    def set_x(self, index: int, x: float) -> None:
        """Set the x coordinate of the point at the given index."""
        with self._data.get_connection() as db_conn:
            db_conn.execute(
                "UPDATE points SET x=:x WHERE p_index=:p_index",
                {"p_index": index, "x": x},
            )
            db_conn.commit()

    def get_y(self, index: int) -> float:
        """Get the y coordinate of the point at the given index."""
        with self._data.get_connection() as db_conn:
            result = db_conn.execute(
                "SELECT y FROM points WHERE p_index=:p_index",
                {"p_index": index},
            ).fetchone()
        if result is not None:
            return float(result["y"])
        else:
            raise IndexError

    def set_y(self, index: int, y: float) -> None:
        """Set the y coordinate of the point at the given index."""
        with self._data.get_connection() as db_conn:
            db_conn.execute(
                "UPDATE points SET y=:y WHERE p_index=:p_index",
                {"p_index": index, "y": y},
            )
            db_conn.commit()

    def get_z(self, index: int) -> float:
        """Get the z coordinate of the point at the given index."""
        with self._data.get_connection() as db_conn:
            result = db_conn.execute(
                "SELECT z FROM points WHERE p_index=:p_index",
                {"p_index": index},
            ).fetchone()
        if result is not None:
            return float(result["z"])
        else:
            raise IndexError

    def set_z(self, index: int, z: float) -> None:
        """Set the z coordinate of the point at the given index."""
        with self._data.get_connection() as db_conn:
            db_conn.execute(
                "UPDATE points SET z=:z WHERE p_index=:p_index",
                {"p_index": index, "z": z},
            )
            db_conn.commit()

    def get_id(self, index: int) -> int:
        with self._data.get_connection() as db_conn:
            result = db_conn.execute(
                "SELECT p_id FROM points WHERE p_index=:index",
                {"index": index},
            ).fetchone()
            if result is not None:
                return int(result["p_id"])
            else:
                return -1


class PointsItems(AbstractTableItems["Model"]):
    def __init__(self, view: "IPointsView", model: "Model") -> None:
        super().__init__(view, model)
        self._titles = ["Name", "X", "Y", "Z", "Id"]

    def get_title(self) -> str:
        return "Points"

    def get_nb_columns(self) -> int:
        if self._model.is_debug:
            return len(self._titles)
        else:
            return len(self._titles) - 1

    def get_column_title(self, column: int) -> str:
        return self._titles[column]

    def get_nb_rows(self) -> int:
        return self._model.points_query.count()

    def insert(self, row: int) -> Optional[int]:
        self._model.points_query.insert(row)
        return row

    def _remove_by_id(self, rid: Any) -> None:
        row = self.get_row_from_id(rid)
        self._model.points_query.remove(row)

    def get_data(self, row: int, column: int) -> str:
        if column == 0:
            return self._model.points_query.get_name(row)
        elif column == 1:
            return self.display_float(self._model.points_query.get_x(row), 2)
        elif column == 2:
            return self.display_float(self._model.points_query.get_y(row), 2)
        elif column == 3:
            return self.display_float(self._model.points_query.get_z(row), 2)
        elif column == 4:
            return str(self._model.points_query.get_id(row))
        return super().get_data(row, column)

    def get_data_by_id(self, rid: Any, column: int) -> str:
        return self.get_data(self.get_row_from_id(rid), column)

    def get_edit_data(self, row: int, column: int) -> Any:
        if column == 1:
            return self._model.points_query.get_x(row)
        elif column == 2:
            return self._model.points_query.get_y(row)
        elif column == 3:
            return self._model.points_query.get_z(row)
        return super().get_edit_data(row, column)

    def is_editable(self, row: int, column: int) -> bool:
        return column < 4

    def set_data(self, row: int, column: int, value: str) -> bool:
        if column == 0:
            self._model.points_query.set_name(row, value)
            return True
        elif 1 <= column <= 3:
            float_value = self.to_float_value(value, 0.0)
            if float_value is not None:
                if column == 1:
                    self._model.points_query.set_x(row, float_value)
                elif column == 2:
                    self._model.points_query.set_y(row, float_value)
                elif column == 3:
                    self._model.points_query.set_z(row, float_value)
                return True
        return False

    def get_delegate_props(
        self, column: int, *, row: Optional[int] = None
    ) -> Optional[DelegateProps]:
        if 1 <= column <= 3:
            return FloatDelegateProps()
        return super().get_delegate_props(column, row=row)


def initialize_points(view: IPointsView, main_view: "ExampleMainView", model: "Model") -> None:
    view.is_visible = True
    view.has_import = True
    view.has_export = True
    view.has_add = True
    view.has_remove = True
    view.has_pagination = True
    view.can_select_items = True
    view.items = PointsItems(view, model)

"""Cube table."""

from composeui.items.table.abstracttableitems import AbstractTableItems
from composeui.items.table.itableview import TableView
from composeui.salomewrapper.core import displayer, geomwrapper
from examples.salomeview.module2 import Module2MainView

from typing_extensions import Self, TypeAlias

import typing
from typing import Optional

if typing.TYPE_CHECKING:
    from examples.salomeview.app import Model


CubeTable: TypeAlias = TableView["CubeTableItems"]


class CubeTableItems(AbstractTableItems["Model"]):
    def __init__(self, view: TableView[Self], model: "Model") -> None:
        super().__init__(view, model, title="Cubes")
        self._column_titles = ["Name", "Point 1", "Point 2", "Entry"]

    def get_column_title(self, column: int) -> str:
        return self._column_titles[column]

    def get_nb_columns(self) -> int:
        return len(self._column_titles)

    def get_nb_rows(self) -> int:
        return self._model.cube_query.count()

    def remove(self, row: int) -> Optional[int]:
        c_id = self._model.cube_query.get_id(row)
        self._model.cube_query.remove_cube(c_id)
        return super().remove(row)

    def get_data(self, row: int, column: int) -> str:
        c_id = self._model.cube_query.get_id(row)
        if column == 0:
            return self._model.cube_query.get_name(c_id)
        elif column == 1:
            return str(self._model.cube_query.get_point_1(c_id))
        elif column == 2:
            return str(self._model.cube_query.get_point_2(c_id))
        elif column == 3:
            entry = self._model.cube_query.get_entry(c_id)
            if entry is not None:
                return entry
            return ""
        return super().get_data(row, column)


def remove_selected_cubes(*, view: CubeTable, model: "Model") -> None:
    assert view.items is not None
    selected_rows = view.items.get_selected_rows()
    for row in selected_rows:
        cube_id = model.cube_query.get_id(row)
        entry = model.cube_query.get_entry(cube_id)
        if entry is not None:
            displayer.hide_entity(entry)
            geomwrapper.remove_geom_object_from_study(entry)


def initialize_cube_table(view: CubeTable, main_view: Module2MainView, model: "Model") -> None:
    view.has_remove = True
    view.items = CubeTableItems(view, model)
    view.dependencies.append(main_view.salome_tree)


def connect_cube_table(view: CubeTable) -> None:
    # To remove the geometry we need the entry so the removing in the sql table need to be done
    # after the removing of the salome object
    view.remove_clicked.insert(0, remove_selected_cubes)

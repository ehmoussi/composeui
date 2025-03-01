from composeui.items.simpletable.simpletableitems import SimpleTableItems

from typing_extensions import TypeAlias

from collections import OrderedDict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from examples.simpletableview.app import Model
    from examples.simpletableview.example import ExampleMainView, PointsTableView

PointsItems: TypeAlias = SimpleTableItems["Model"]


def initialize_points(
    view: "PointsTableView", main_view: "ExampleMainView", model: "Model"
) -> None:
    view.is_visible = True
    view.has_import = True
    view.has_export = True
    view.has_add = True
    view.has_remove = True
    view.drag_drop_enabled = True
    view.items = PointsItems(
        view,
        model,
        model.sqlite_store,
        table_name="points",
        columns=OrderedDict(
            {
                "p_name": "Name",
                "x": "X",
                "y": "Y",
                "z": "Z",
            }
        ),
        order_column="p_index",
        increment_columns=["p_name"],
        is_read_only=False,
    )

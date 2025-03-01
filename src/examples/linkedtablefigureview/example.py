from composeui import figure, linkedtablefigure
from composeui.core.views.iactionview import IActionView
from composeui.items.simpletable.simpletableitems import SimpleTableItems
from composeui.linkedtablefigure.ilinkedtablefigureview import ILinkedTableFigureView
from composeui.mainview.interfaces.imaintoolbar import IMainToolBar
from composeui.mainview.interfaces.imainview import IMainView
from composeui.mainview.interfaces.itoolbar import ICheckableToolBar

from typing_extensions import OrderedDict, TypeAlias

import math
import typing
from dataclasses import dataclass, field

if typing.TYPE_CHECKING:
    from examples.linkedtablefigureview.app import Model


PointsItems: TypeAlias = SimpleTableItems["Model"]


@dataclass(eq=False)
class INavigationToolBar(ICheckableToolBar):
    points: IActionView = field(init=False, default_factory=IActionView)


@dataclass(eq=False)
class IExampleMainToolBar(IMainToolBar):
    navigation: INavigationToolBar = field(init=False, default_factory=INavigationToolBar)


@dataclass(eq=False)
class IExampleMainView(IMainView):
    toolbar: IExampleMainToolBar = field(init=False, default_factory=IExampleMainToolBar)
    points: ILinkedTableFigureView[PointsItems] = field(
        init=False, default_factory=ILinkedTableFigureView
    )


def initialize_navigation(view: INavigationToolBar) -> None:
    view.points.text = "Points"
    view.points.is_checked = True
    view.is_exclusive = True


def initialize_point(view: ILinkedTableFigureView[PointsItems], model: "Model") -> None:
    view.table.has_add = True
    view.table.has_remove = True
    items = SimpleTableItems(
        view.table,
        model,
        model.sqlite_store,
        "point",
        columns=OrderedDict[str, str](
            (
                ("p_name", "Name"),
                ("x", "X"),
                ("y", "Y"),
            )
        ),
        order_column="p_order",
        is_read_only=False,
    )
    _create_circle(items)
    view.table.items = items
    view.figure.has_toolbar = True
    figure.initialize_figure_axes(view.figure)
    linkedtablefigure.update_figure(parent_view=view)


def _create_circle(items: PointsItems) -> None:
    nb_points = 20
    step = 2 * math.pi / nb_points
    for i in range(nb_points + 1):
        theta = i * step
        items.insert(i)
        items.set_data(i, 0, f"Point {i+1}")
        items.set_data(i, 1, str(math.cos(theta)))
        items.set_data(i, 2, str(math.sin(theta)))

from composeui import figure, linkedtablefigure
from composeui.core.views.actionview import ActionView
from composeui.items.simpletable.simpletableitems import SimpleTableItems
from composeui.linkedtablefigure.linkedtablefigureview import LinkedTableFigureView
from composeui.mainview.views.maintoolbar import MainToolBar
from composeui.mainview.views.mainview import MainView
from composeui.mainview.views.toolbar import CheckableToolBar

from typing_extensions import OrderedDict, TypeAlias

import math
import typing
from dataclasses import dataclass, field

if typing.TYPE_CHECKING:
    from examples.linkedtablefigureview.app import Model


PointsItems: TypeAlias = SimpleTableItems["Model"]


@dataclass(eq=False)
class NavigationToolBar(CheckableToolBar):
    points: ActionView = field(init=False, default_factory=ActionView)


@dataclass(eq=False)
class ExampleMainToolBar(MainToolBar):
    navigation: NavigationToolBar = field(init=False, default_factory=NavigationToolBar)


@dataclass(eq=False)
class ExampleMainView(MainView):
    toolbar: ExampleMainToolBar = field(init=False, default_factory=ExampleMainToolBar)
    points: LinkedTableFigureView[PointsItems] = field(
        init=False, default_factory=LinkedTableFigureView
    )


def initialize_navigation(view: NavigationToolBar) -> None:
    view.points.text = "Points"
    view.points.is_checked = True
    view.is_exclusive = True


def initialize_point(view: LinkedTableFigureView[PointsItems], model: "Model") -> None:
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

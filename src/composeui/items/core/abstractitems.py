from composeui.commontypes import AnyItemsView, AnyModel
from composeui.items.core.textfinder import TextFinder

from typing_extensions import OrderedDict

import math
import typing
from abc import ABC, abstractmethod
from typing import Generator, Generic, List, Optional, Tuple, TypeVar

if typing.TYPE_CHECKING:
    from composeui.items.core.views.iitemsview import ItemsView

V = TypeVar("V", bound="ItemsView")


class AbstractItems(ABC, Generic[V, AnyModel]):
    def __init__(self, view: V, model: AnyModel, *, title: str = "") -> None:
        self._view: V = view
        self._model: AnyModel = model
        self._title = title
        self.filter_manager = TextFinder()
        self.filter_column_indices: Tuple[int, ...] = ()
        self._dependencies: List[AbstractItems[AnyItemsView, AnyModel]] = []
        self._is_view_selection_suspended = False

    def get_dependencies(self) -> Tuple["AbstractItems[AnyItemsView, AnyModel]", ...]:
        """Get the items that can be used to generate the data of the current items.

        A function is used here to ease the implementation of TableToTreeItems and
        TreeToTableItems which returns directly the values of the real items.
        """
        return tuple(self._dependencies)

    def set_dependencies(
        self, dependencies: List["AbstractItems[AnyItemsView, AnyModel]"]
    ) -> None:
        """Set the items that can be used to generate the data of the current items.

        A function is used here to ease the implementation of TableToTreeItems and
        TreeToTableItems which returns directly the values of the real items.
        """
        self._dependencies = dependencies

    def add_dependency(self, dependency: "AbstractItems[AnyItemsView, AnyModel]") -> None:
        """Add an items that can be used to generate the data of the current items.

        A function is used here to ease the implementation of TableToTreeItems and
        TreeToTableItems which returns directly the values of the real items.
        """
        self._dependencies.append(dependency)

    def is_view_selection_suspended(self) -> bool:
        """Check if the view selection is suspended.

        A function is used here to ease the implementation of TableToTreeItems and
        TreeToTableItems which returns directly the values of the real items.
        """
        return self._is_view_selection_suspended

    def set_view_selection_suspend_status(self, is_suspended: bool) -> None:
        """Suspend/Resume the view selection.

        A function is used here to ease the implementation of TableToTreeItems and
        TreeToTableItems which returns directly the values of the real items.
        """
        self._is_view_selection_suspended = is_suspended

    @abstractmethod
    def get_nb_columns(self) -> int:
        """Get the number of columns."""
        return 0

    @abstractmethod
    def get_column_title(self, column: int) -> str:
        """Get the title of the given column."""
        return ""

    def can_enable_table(self) -> bool:
        """Check if the table/tree can be enabled.

        Override this method if the table/tree is dependent of other tables/trees.
        Returns if the table/tree should be enabled or not according to its dependencies.
        By default returns True.
        """
        return True

    def get_column_titles(self) -> List[str]:
        """Get the column titles that will be displayed."""
        return [self.get_column_title(column) for column in range(self.get_nb_columns())]

    def get_column_names(self) -> List[str]:
        """Get the internal column names.

        The internal column names don't have special characters, spaces, ...
        They are used to name the columns during the export into dataframe/csv/markdown/...
        """
        # TODO: clean the titles automatically
        return list(self.get_column_titles())

    @abstractmethod
    def remove_all(self) -> None:
        """Remove all the rows of the table/tree."""

    def get_confirmation_message(self) -> str:
        """Get a confirmation message before removing the current selected rows.

        An empty message means there is no confirmation message before removing rows.
        """
        return ""

    def get_selected_items(self) -> OrderedDict[Tuple[int, ...], List[int]]:
        """Get the selected items."""
        return OrderedDict(self._view.selected_items)

    def set_selected_items(
        self, selected_items: OrderedDict[Tuple[int, ...], List[int]]
    ) -> None:
        """Set the selected items."""
        self._view.selected_items = selected_items

    def get_selected_positions(self) -> List[Tuple[int, ...]]:
        """Get the selected positions."""
        return list(self._view.selected_items)

    def set_selected_positions(self, positions: List[Tuple[int, ...]]) -> None:
        """Set the selected positions."""
        columns = list(range(self.get_nb_columns()))
        selected_items = OrderedDict()
        for position in positions:
            selected_items[position] = columns
        self._view.selected_items = selected_items

    def clear_selection(self) -> None:
        """Clear the current selection."""
        self.set_selected_items(OrderedDict())

    def iter_trigger_dependencies(self) -> Generator[None, None, None]:
        """Generate all possible events that trigger the dependencies and impact this table.

        Each yielded event represents a situation where one or more dependencies are impacted,
        allowing for the generation of combined data based on these interactions.

        It can be used for example for a LinkedTableView by yielding after
        selecting each row of the master table.
        """
        yield

    @staticmethod
    def display_float(value: float, nb_decimals: int = -1) -> str:
        """Get the float value in a string format.

        If the number of decimals is negative the value is not truncated.
        If the value is nan an empty string is returned.
        """
        if math.isnan(value):
            return ""
        elif nb_decimals < 0:
            return f"{value}"
        elif nb_decimals == 0:
            return str(int(round(value, nb_decimals)))
        else:
            return f"{round(value, nb_decimals):.{nb_decimals}f}"

    @staticmethod
    def to_float_value(
        value: Optional[str],
        default: Optional[float] = None,
        min_value: Optional[float] = None,
        max_value: Optional[float] = None,
    ) -> Optional[float]:
        """Transform the given string to a float value or return None if failed."""
        if value == "" or value is None:
            return default
        else:
            try:
                float_value = float(value)
            except ValueError:
                return None
            else:
                if (min_value is not None and float_value < min_value) or (
                    max_value is not None and float_value > max_value
                ):
                    return None
                else:
                    return float_value

    @staticmethod
    def to_int_value(
        value: Optional[str],
        default: Optional[int] = None,
        min_value: Optional[int] = None,
        max_value: Optional[int] = None,
    ) -> Optional[int]:
        """Transform the given string to an int value or return None if failed."""
        if value == "" or value is None:
            return default
        else:
            try:
                int_value = int(float(value))
            except ValueError:
                return None
            else:
                if (min_value is not None and int_value < min_value) or (
                    max_value is not None and int_value > max_value
                ):
                    return None
                else:
                    return int_value

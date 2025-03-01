from composeui.commontypes import AnyModel, AnyTableItems
from composeui.items.core.qt.qtitemsview import ItemsGroupView, QtItemsView
from composeui.items.simpletable import ISimpleTableView
from composeui.items.simpletable.simpletableitems import SimpleTableItems
from composeui.items.table.itableview import ITableGroupView, ITableView
from composeui.items.table.qt.widgets.tableitemmodel import TableItemModel
from composeui.items.table.qt.widgets.tablewidget import TableWidget

from dataclasses import InitVar, dataclass, field
from typing import Optional, cast


@dataclass(eq=False)
class QtTableView(QtItemsView, ITableView[AnyTableItems]):
    r"""Table view."""

    double_clicked_is_check: InitVar[bool] = False
    table_widget: TableWidget = field(init=False)
    view: TableWidget = field(init=False)

    def __post_init__(self, double_clicked_is_check: bool) -> None:
        self.table_widget = TableWidget(double_clicked_is_check)
        self.view = self.table_widget
        super().__post_init__()

    @property  # type: ignore[misc]
    def items(self) -> Optional[AnyTableItems]:
        if self.table_widget.items is not None:
            return cast(AnyTableItems, self.table_widget.items)
        else:
            return None

    @items.setter
    def items(self, items: Optional[AnyTableItems]) -> None:
        self.table_widget.items = items
        self.selection_changed.add_qt_signals(
            (self.table.selectionModel(), self.table.selectionModel().selectionChanged)
        )
        model = self.table.model()
        assert isinstance(model, TableItemModel)
        self.item_toggled.add_qt_signals((model.source_model, model.source_model.item_toggled))


@dataclass(eq=False)
class SimpleTableView(QtTableView[SimpleTableItems[AnyModel]], ISimpleTableView[AnyModel]):
    items: SimpleTableItems[AnyModel] = field(init=False)


@dataclass(eq=False)
class TableGroupView(ItemsGroupView, ITableGroupView[AnyTableItems]):
    r"""Table inside a groupbox."""

    double_clicked_is_check: InitVar[bool] = False
    table_widget: TableWidget = field(init=False)

    def __post_init__(self, double_clicked_is_check: bool) -> None:
        self.table_widget = TableWidget(double_clicked_is_check)
        super().__post_init__()

    @property  # type: ignore[misc]
    def items(self) -> Optional[AnyTableItems]:
        if self.table_widget.items is not None:
            return cast(AnyTableItems, self.table_widget.items)
        else:
            return None

    @items.setter
    def items(self, items: Optional[AnyTableItems]) -> None:
        self.table_widget.items = items
        self.selection_changed.add_qt_signals(
            (self.table.selectionModel(), self.table.selectionModel().selectionChanged)
        )

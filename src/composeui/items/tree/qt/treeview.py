from composeui.commontypes import AnyTreeItems
from composeui.items.core.qt.itemsview import ItemsGroupView, ItemsView
from composeui.items.tree.itreeview import ITreeGroupView, ITreeView
from composeui.items.tree.qt.treeitemmodel import TreeItemModel
from composeui.items.tree.qt.widgets.treewidget import TreeWidget

from dataclasses import InitVar, dataclass, field
from typing import Optional, cast


@dataclass(eq=False)
class TreeView(ItemsView, ITreeView[AnyTreeItems]):
    r"""Tree view."""

    double_clicked_is_check: InitVar[bool] = False
    table_widget: TreeWidget = field(init=False)
    view: TreeWidget = field(init=False)

    def __post_init__(self, double_clicked_is_check: bool) -> None:
        self.table_widget = TreeWidget(double_clicked_is_check)
        self.view: TreeWidget = self.table_widget
        super().__post_init__()

    @property  # type: ignore[misc]
    def items(self) -> Optional[AnyTreeItems]:
        if self.table_widget.items is not None:
            return cast(AnyTreeItems, self.table_widget.items)
        else:
            return None

    @items.setter
    def items(self, items: Optional[AnyTreeItems]) -> None:
        self.table_widget.items = items
        self.selection_changed.add_qt_signals(
            (self.table.selectionModel(), self.table.selectionModel().selectionChanged)
        )

    @property  # type: ignore[misc]
    def is_expansion_animated(self) -> bool:
        return self.table_widget.table.isAnimated()

    @is_expansion_animated.setter
    def is_expansion_animated(self, is_expansion_animated: bool) -> None:
        self.table_widget.table.setAnimated(is_expansion_animated)


@dataclass(eq=False)
class TreeGroupView(
    ItemsGroupView, ITreeGroupView[AnyTreeItems]
):  # TODO: check if using TreeView as a base class is better
    r"""Tree view in a group view."""

    double_clicked_is_check: InitVar[bool] = False
    table_widget: TreeWidget = field(init=False)

    def __post_init__(self, double_clicked_is_check: bool) -> None:
        self.table_widget = TreeWidget(double_clicked_is_check)
        super().__post_init__()

    @property  # type: ignore[misc]
    def items(self) -> Optional[AnyTreeItems]:
        if self.table_widget.items is not None:
            return cast(AnyTreeItems, self.table_widget.items)
        else:
            return None

    @items.setter
    def items(self, items: Optional[AnyTreeItems]) -> None:
        self.table_widget.items = items
        self.selection_changed.add_qt_signals(
            (self.table.selectionModel(), self.table.selectionModel().selectionChanged)
        )
        model = self.table.model()
        assert isinstance(model, TreeItemModel)
        self.item_toggled.add_qt_signals((model.source_model, model.source_model.item_toggled))

    @property  # type: ignore[misc]
    def is_expansion_animated(self) -> bool:
        return self.table_widget.table.isAnimated()

    @is_expansion_animated.setter
    def is_expansion_animated(self, is_expansion_animated: bool) -> None:
        self.table_widget.table.setAnimated(is_expansion_animated)

from composeui.core.basesignal import BaseSignal
from composeui.core.views.ipendingview import IPendingView
from composeui.items.core.views.ifiltertableview import IFilterTableView
from composeui.items.core.views.ipaginationview import IPaginationView

from typing_extensions import OrderedDict

import enum
from dataclasses import dataclass, field
from typing import List, Set, Tuple


class FormatExtension(enum.Flag):
    CSV = enum.auto()
    EXCEL = enum.auto()
    CSVEXCEL = CSV | EXCEL
    JSON = enum.auto()
    # PARQUET = enum.auto() // TODO: Add it ? Is it useful ?
    # HDF5 = enum.auto() // TODO: Add HDF5
    IMPORT_EXTENSIONS = CSVEXCEL | JSON
    MARKDOWN = enum.auto()
    HTML = enum.auto()
    ALL = CSV | EXCEL | JSON | MARKDOWN | HTML


@dataclass(eq=False)
class IItemsView(IPendingView):
    has_import: bool = field(init=False, default=False)
    has_export: bool = field(init=False, default=False)
    has_add: bool = field(init=False, default=False)
    has_remove: bool = field(init=False, default=False)
    has_pagination: bool = field(init=False, default=False)
    selected_items: OrderedDict[Tuple[int, ...], List[int]] = field(
        init=False, default_factory=OrderedDict[Tuple[int, ...], List[int]]
    )
    is_single_selection: bool = field(init=False, default=False)
    can_select_items: bool = field(init=False, default=False)
    has_focus: bool = field(init=False, default=False)
    has_context_menu: bool = field(init=False, default=False)
    has_check_all: bool = field(init=False, default=False)
    sorting_enabled: bool = field(init=False, default=False)
    is_filtered: bool = field(init=False, default=False)
    drag_drop_enabled: bool = field(init=False, default=False)
    help_text: str = field(init=False, default="")
    import_extensions: FormatExtension = field(
        init=False, default=FormatExtension.IMPORT_EXTENSIONS
    )
    export_extensions: FormatExtension = field(init=False, default=FormatExtension.ALL)
    # signals
    clicked: BaseSignal = field(init=False, default=BaseSignal())
    double_clicked: BaseSignal = field(init=False, default=BaseSignal())
    item_edited: BaseSignal = field(init=False, default=BaseSignal())
    item_toggled: BaseSignal = field(init=False, default=BaseSignal())
    selection_changed: BaseSignal = field(init=False, default=BaseSignal())
    context_menu_requested: BaseSignal = field(init=False, default=BaseSignal())
    shortcut_clear: BaseSignal = field(init=False, default=BaseSignal())
    shortcut_add: BaseSignal = field(init=False, default=BaseSignal())
    shortcut_delete: BaseSignal = field(init=False, default=BaseSignal())
    shortcut_copy: BaseSignal = field(init=False, default=BaseSignal())
    shortcut_paste: BaseSignal = field(init=False, default=BaseSignal())
    check_all: BaseSignal = field(init=False, default=BaseSignal())
    filter_changed: BaseSignal = field(init=False, default=BaseSignal())
    import_clicked: BaseSignal = field(init=False, default=BaseSignal())
    export_clicked: BaseSignal = field(init=False, default=BaseSignal())
    add_clicked: BaseSignal = field(init=False, default=BaseSignal())
    remove_clicked: BaseSignal = field(init=False, default=BaseSignal())
    # views
    filter_view: IFilterTableView = field(init=False, default_factory=IFilterTableView)
    pagination_view: IPaginationView = field(init=False, default_factory=IPaginationView)

    @property
    def context_menu_selection(self) -> Tuple[Tuple[int, ...], int]:
        return ((), 0)

    @property
    def context_menu_position(self) -> Tuple[int, int]:
        return (0, 0)

    def failed_highlight(self, items: Set[Tuple[int, Tuple[int, ...], int]]) -> None: ...
    def successful_highlight(self, items: Set[Tuple[int, Tuple[int, ...], int]]) -> None: ...

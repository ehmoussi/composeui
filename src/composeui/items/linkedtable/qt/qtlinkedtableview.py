r"""Select/Modify view using a combination of two table."""

from composeui.commontypes import AnyDetailTableItems, AnyMasterTableItems
from composeui.core.qt.qtview import QtView
from composeui.items.linkedtable.linkedtableview import LinkedTableView
from composeui.items.table.qt.qttableview import QtTableGroupView

from qtpy.QtCore import Qt
from qtpy.QtGui import QIcon
from qtpy.QtWidgets import QGroupBox, QHBoxLayout, QPushButton, QSplitter, QVBoxLayout, QWidget

from dataclasses import InitVar, dataclass, field
from typing import Tuple, Union


@dataclass(eq=False)
class QtLinkedTableView(QtView, LinkedTableView[AnyMasterTableItems, AnyDetailTableItems]):
    r"""view using a combination of two tables.

    - The master table is used to select an item
    - The detail table is displaying the details for the current selection of the selection
    of the master table.

    """

    view: Union[QWidget, QGroupBox] = field(init=False, repr=False)
    master_table: QtTableGroupView[AnyMasterTableItems] = field(
        init=False, repr=False, default_factory=QtTableGroupView[AnyMasterTableItems]
    )
    detail_table: QtTableGroupView[AnyDetailTableItems] = field(
        init=False, repr=False, default_factory=QtTableGroupView[AnyDetailTableItems]
    )

    is_horizontal: InitVar[bool] = True
    stretch_factor: InitVar[Tuple[int, int]] = (1, 3)
    has_groupbox: bool = False

    _title: str = field(init=False, repr=False, default="")

    def __post_init__(self, is_horizontal: bool, stretch_factor: Tuple[int, int]) -> None:
        super().__post_init__()
        if self.has_groupbox:
            self.view = QGroupBox()
        else:
            self.view = QWidget()
        self.layout = QVBoxLayout()
        self.view.setLayout(self.layout)
        # import/export buttons
        import_export_layout = QHBoxLayout()
        import_export_layout.addStretch()
        self.import_button = QPushButton("Import")
        self.import_button.setIcon(QIcon(":/icons/import.png"))
        self.import_button.setToolTip("Import")
        self.import_button.setVisible(False)
        import_export_layout.addWidget(self.import_button)
        self.export_button = QPushButton("Export")
        self.export_button.setIcon(QIcon(":/icons/export.png"))
        self.export_button.setToolTip("Export")
        self.export_button.setVisible(False)
        import_export_layout.addWidget(self.export_button)
        self.layout.addLayout(import_export_layout)
        # tables
        if is_horizontal:
            self.splitter = QSplitter(Qt.Horizontal)
        else:
            self.splitter = QSplitter(Qt.Vertical)
        # - selection table
        self.splitter.addWidget(self.master_table.view)
        self.splitter.setStretchFactor(0, stretch_factor[0])
        self.splitter.setCollapsible(0, False)
        # - datas table
        self.splitter.addWidget(self.detail_table.view)
        self.splitter.setStretchFactor(1, stretch_factor[1])
        self.splitter.setCollapsible(1, False)
        self.layout.addWidget(self.splitter)
        # assign signals
        self.import_clicked.add_qt_signals((self.import_button, self.import_button.clicked))
        self.export_clicked.add_qt_signals((self.export_button, self.export_button.clicked))

    @property  # type: ignore[misc]
    def title(self) -> str:
        return self._title

    @title.setter
    def title(self, title: str) -> None:
        self._title = title
        if isinstance(self.view, QGroupBox):
            self.view.setTitle(title)

    @property  # type: ignore[misc]
    def has_import(self) -> bool:
        return self.import_button.isVisible()

    @has_import.setter
    def has_import(self, has_import: bool) -> None:
        self.import_button.setVisible(has_import)

    @property  # type: ignore[misc]
    def has_export(self) -> bool:
        return self.export_button.isVisible()

    @has_export.setter
    def has_export(self, has_export: bool) -> None:
        self.export_button.setVisible(has_export)

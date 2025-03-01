"""Salome Dock View."""

from composeui.core.qt.qtview import QtView
from composeui.mainview.interfaces.idockview import DockArea, IDockView

from qtpy.QtCore import Qt
from qtpy.QtWidgets import QDockWidget, QVBoxLayout, QWidget

from dataclasses import dataclass, field
from functools import reduce


@dataclass(eq=False)
class QtDockView(QtView, IDockView):
    view: QDockWidget = field(init=False, default_factory=QDockWidget)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.view.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)
        # central view
        self.central_view = QWidget()
        self.central_layout = QVBoxLayout()
        self.central_view.setLayout(self.central_layout)
        self.view.setWidget(self.central_view)

    @property  # type: ignore[misc]
    def title(self) -> str:
        return str(self.view.windowTitle())

    @title.setter
    def title(self, title: str) -> None:
        self.view.setWindowTitle(title)
        # useful for Salomé to remove a warning
        self.view.setObjectName(title.replace(" ", "_").lower())

    @property  # type: ignore[misc]
    def area(self) -> DockArea:
        allowed_areas_view = self.view.allowedAreas()
        if hasattr(allowed_areas_view, "value"):
            allowed_areas = allowed_areas_view.value
        else:
            allowed_areas = int(allowed_areas_view)
        return reduce(
            lambda x, y: x | y,
            (dock_area for dock_area in DockArea if allowed_areas & dock_area.value),
        )

    @area.setter
    def area(self, area: DockArea) -> None:
        allowed_areas = Qt.LeftDockWidgetArea & area.value
        allowed_areas |= Qt.RightDockWidgetArea & area.value
        allowed_areas |= Qt.TopDockWidgetArea & area.value
        allowed_areas |= Qt.BottomDockWidgetArea & area.value
        self.view.setAllowedAreas(Qt.DockWidgetAreas(allowed_areas))

"""Qt Figure view."""

from composeui.core.pendingupdate import pending_until_visible
from composeui.core.qt.qtview import QtView
from composeui.core.qt.widgets.widget import GroupBox, Widget
from composeui.figure.figureview import FigureGroupView, FigureView

try:
    from composeui.figure.qtfiguretoolbar import QtFigureToolbar

    from matplotlib.backend_bases import Event, MouseEvent

    try:
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
    except ModuleNotFoundError:
        from matplotlib.backends.backend_qt5agg import (  # type: ignore[attr-defined, no-redef]
            FigureCanvas,
        )

    from matplotlib.figure import Figure
except (ImportError, ModuleNotFoundError) as e:
    raise ValueError("Can't use FigureView without matplotlib.") from e

from qtpy.QtWidgets import QVBoxLayout

from dataclasses import InitVar, dataclass, field
from typing import Any, Optional, Union


@dataclass(eq=False)
class QtFigureView(QtView, FigureView):
    """Figure View."""

    has_groupbox: InitVar[bool] = False

    view: Union[GroupBox, Widget] = field(init=False)

    # Figure
    toolbar: Optional[QtFigureToolbar] = field(init=False, repr=False, default=None)
    figure_canvas_view: Optional[FigureCanvas] = field(init=False, repr=False, default=None)

    _has_toolbar: bool = field(init=False, repr=False, default=False)
    _figure: Optional[Figure] = field(init=False, repr=False, default=None)

    def __post_init__(self, has_groupbox: bool) -> None:
        super().__post_init__()
        self.clicked.allow_calling = True
        if has_groupbox:
            self.view = GroupBox()
            self.view.setCheckable(False)
        else:
            self.view = Widget()
        self.layout = QVBoxLayout()
        self.view.setLayout(self.layout)
        # connect to an internal slot to manage the pending of the update
        self.view.view_visible.connect(self._update_if_pending)

    @property  # type: ignore[misc]
    def has_toolbar(self) -> bool:
        return self._has_toolbar

    @has_toolbar.setter
    def has_toolbar(self, has_toolbar: bool) -> None:
        if not has_toolbar and self.toolbar is not None:
            self.layout.removeWidget(self.toolbar)
            self.toolbar.deleteLater()
            self.toolbar = None
        elif has_toolbar and self.figure_canvas_view is not None:
            self.toolbar = QtFigureToolbar(
                self.figure_canvas_view,
                self.view,
            )
            self.layout.insertWidget(0, self.toolbar)
        elif has_toolbar:
            raise ValueError("Can't have a toolbar without a figure.")
        self._has_toolbar = has_toolbar

    @property  # type: ignore[misc]
    def figure(self) -> Optional[Figure]:
        return self._figure

    @figure.setter
    def figure(self, figure: Figure) -> None:
        self._figure = figure
        self._create_figure_canvas()

    def _create_figure_canvas(self) -> None:
        if self.figure_canvas_view is not None:
            self.layout.removeWidget(self.figure_canvas_view)
            self.figure_canvas_view.deleteLater()
        if self.toolbar is not None:
            self.layout.removeWidget(self.toolbar)
            self.toolbar.deleteLater()
        self.figure_canvas_view = FigureCanvas(self._figure)  # type: ignore[no-untyped-call]
        self.figure_canvas_view.mpl_connect("button_press_event", self._on_click)
        if self.has_toolbar:
            self.toolbar = QtFigureToolbar(
                self.figure_canvas_view,
                self.view,
            )
            self.layout.insertWidget(0, self.toolbar)
        else:
            self.toolbar = None
        self.layout.addWidget(self.figure_canvas_view)

    def _on_click(self, event: Event) -> Any:
        if self.figure is not None and isinstance(event, MouseEvent):
            self.x_last_clicked = event.xdata
            self.y_last_clicked = event.ydata
            self.last_clicked_axes = event.inaxes
        self.clicked()

    def _update_if_pending(self) -> None:
        r"""Update the table if an update is pending."""
        if self.is_update_pending:
            self.update()

    @pending_until_visible
    def update(self) -> None:
        r"""Redraw the figure."""
        if self.toolbar is not None:
            self.toolbar.show_legend()
        if self.figure_canvas_view is not None:
            self.figure_canvas_view.draw_idle()  # type: ignore[no-untyped-call]


@dataclass(eq=False)
class QtFigureGroupView(QtFigureView, FigureGroupView):
    """Figure view inside a Groupbox."""

    view: GroupBox = field(init=False, default_factory=GroupBox)

    def __post_init__(self) -> None:  # type: ignore[override]
        super().__post_init__(has_groupbox=True)

    @property  # type: ignore[misc]
    def title(self) -> str:
        return self.view.title()

    @title.setter
    def title(self, title: str) -> None:
        self.view.setTitle(title)

    @property  # type: ignore[misc]
    def is_checkable(self) -> bool:
        return self.view.isCheckable()

    @is_checkable.setter
    def is_checkable(self, is_checkable: bool) -> None:
        self.view.setCheckable(is_checkable)

    @property  # type: ignore[misc]
    def is_checked(self) -> bool:
        return self.view.isChecked()

    @is_checked.setter
    def is_checked(self, is_checked: bool) -> None:
        self.view.setChecked(is_checked)

"""A chart widget over pyqtgraph: fast with long series, zoomed and panned with the mouse."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

import numpy as np
import pyqtgraph as pg
from qtpy.QtCore import QEvent, QPointF
from qtpy.QtGui import QColor, QPalette

from composeui.core.chartcolors import is_dashed, series_color

if TYPE_CHECKING:
    from qtpy.QtWidgets import QWidget

    from composeui.core.view import Series

#: the hover values' rate, per second: a mouse sends far more moves than that
_HOVER_RATE = 30
#: the lightness (of 255) under which a background is dark
_DARK_LIGHTNESS = 128


def _format(value: float, unit: str) -> str:
    return f"{value:.4g} {unit}".rstrip()


class QChart(pg.PlotWidget):  # type: ignore[misc]
    """A chart of series; hovering it shows each series' point nearest the cursor's x.

    Its colors follow the application's palette, changing with it (a dark scheme).
    """

    #: whether `__init__` is done: pyqtgraph's own changes the palette before it is
    _is_built = False

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._series: list[Series] = []
        self._units = ("", "")
        self._items: list[pg.PlotDataItem] = []
        plot = self.getPlotItem()
        self._legend = plot.addLegend()
        # pyqtgraph thins and clips what it draws itself: a million points stay fluid
        plot.setDownsampling(auto=True, mode="peak")
        plot.setClipToView(True)
        plot.showGrid(x=True, y=True, alpha=0.15)
        self._crosshair = pg.InfiniteLine(angle=90, movable=False)
        self._crosshair.setVisible(False)
        self._hover = pg.TextItem(anchor=(0, 1))
        self._hover.setVisible(False)
        for item in (self._crosshair, self._hover):
            plot.addItem(item, ignoreBounds=True)
        self._mouse_proxy = pg.SignalProxy(
            self.scene().sigMouseMoved, rateLimit=_HOVER_RATE, slot=self._on_mouse_moved
        )
        self._is_built = True
        self._apply_palette()

    def set_title(self, title: str) -> None:
        self.getPlotItem().setTitle(title or None)

    def set_axis(self, axis: str, title: str, unit: str) -> None:
        """Label the `axis` ("bottom" or "left"); pyqtgraph scales the unit, e.g. into ms."""
        self.getPlotItem().setLabel(axis, title or None, units=unit or None)
        x_unit, y_unit = self._units
        self._units = (unit, y_unit) if axis == "bottom" else (x_unit, unit)

    def set_series(self, series: list[Series]) -> None:
        """Show `series`, reusing the curves drawn: the zoom stays where the user put it."""
        self._series = series
        plot = self.getPlotItem()
        while len(self._items) > len(series):
            plot.removeItem(self._items.pop())
        while len(self._items) < len(series):
            self._items.append(plot.plot(connect="finite"))
        for item, curve in zip(self._items, series):
            item.setData(np.asarray(curve.x, dtype=float), np.asarray(curve.y, dtype=float))
            item.opts["name"] = curve.name
        self._apply_colors()
        self._hover.setVisible(False)
        self._crosshair.setVisible(False)

    def legend_names(self) -> list[str]:
        return [label.text for _sample, label in self._legend.items]

    def hover_text(self) -> str:
        """Get the values the hover shows, empty while the cursor is off the chart."""
        return str(self._hover.toPlainText()) if self._hover.isVisible() else ""

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange and self._is_built:
            self._apply_palette()

    def _is_dark(self) -> bool:
        return bool(self.palette().color(QPalette.ColorRole.Window).lightness() < _DARK_LIGHTNESS)

    def _apply_palette(self) -> None:
        palette = self.palette()
        background = palette.color(QPalette.ColorRole.Window)
        text = palette.color(QPalette.ColorRole.WindowText)
        self.setBackground(background)
        plot = self.getPlotItem()
        for name in ("bottom", "left"):
            axis = plot.getAxis(name)
            axis.setPen(text)
            axis.setTextPen(text)
        plot.titleLabel.setText(plot.titleLabel.text, color=text)
        self._legend.setLabelTextColor(text)
        self._hover.setColor(text)
        crosshair = QColor(text)
        crosshair.setAlpha(120)
        self._crosshair.setPen(pg.mkPen(crosshair))
        self._apply_colors()

    def _apply_colors(self) -> None:
        is_dark = self._is_dark()
        for index, item in enumerate(self._items):
            style = {"dash": [6, 4]} if is_dashed(index) else {}
            item.setPen(pg.mkPen(series_color(index, is_dark=is_dark), width=2, **style))
        # the legend's samples draw the pens their curves had when added
        self._legend.clear()
        for item, curve in zip(self._items, self._series):
            self._legend.addItem(item, curve.name)

    def _on_mouse_moved(self, event: tuple[Any, ...]) -> None:
        self.show_hover(event[0])

    def show_hover(self, scene_position: QPointF) -> None:
        """Show the values nearest `scene_position`'s x, or hide them off the plot."""
        view_box = self.getPlotItem().vb
        if not view_box.sceneBoundingRect().contains(scene_position) or len(self._series) == 0:
            self._hover.setVisible(False)
            self._crosshair.setVisible(False)
            return
        position = view_box.mapSceneToView(scene_position)
        x_unit, y_unit = self._units
        lines = [_format(position.x(), x_unit)]
        for curve in self._series:
            point = _nearest(curve, position.x())
            if point is not None:
                lines.append(f"{curve.name}: {_format(point[1], y_unit)}")
        self._crosshair.setPos(position.x())
        self._crosshair.setVisible(True)
        self._hover.setText("\n".join(lines))
        self._hover.setPos(position)
        self._hover.setVisible(True)


def _nearest(series: Series, x: float) -> tuple[float, float] | None:
    """Get the drawn point of `series` with the x nearest `x`, None when none is drawn."""
    xs = np.asarray(series.x, dtype=float)
    ys = np.asarray(series.y, dtype=float)
    drawn = np.isfinite(xs) & np.isfinite(ys)
    if not drawn.any():
        return None
    distances = np.where(drawn, np.abs(xs - x), math.inf)
    index = int(np.argmin(distances))
    return float(xs[index]), float(ys[index])

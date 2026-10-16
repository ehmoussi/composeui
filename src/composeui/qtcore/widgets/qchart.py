"""A chart widget over pyqtgraph: fast with long series, zoomed and panned with the mouse."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

import numpy as np
import pyqtgraph as pg
from qtpy.QtCore import QEvent, QPointF
from qtpy.QtGui import QColor, QPalette

from composeui.core.chartcolors import is_dashed, series_color
from composeui.core.view import ChartKind, ChartView

if TYPE_CHECKING:
    from qtpy.QtWidgets import QWidget

    from composeui.core.view import Series

#: the hover values' rate, per second: a mouse sends far more moves than that
_HOVER_RATE = 30
#: the lightness (of 255) under which a background is dark
_DARK_LIGHTNESS = 128
#: a scatter's dots, in pixels
_DOT_SIZE = 8


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
        self._kind = ChartKind.LINE
        self._categories: list[str] = []
        self._bars: list[pg.BarGraphItem] = []
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

    def set_kind(self, kind: ChartKind) -> None:
        """Draw the series as `kind`, unless they say otherwise (`Series.kind`)."""
        self._kind = kind
        self._draw()

    def set_categories(self, categories: list[str]) -> None:
        """Name a bar chart's categories, under their groups of bars."""
        self._categories = categories
        self._draw()

    def set_series(self, series: list[Series]) -> None:
        """Show `series`, reusing the items drawn: the zoom stays where the user put it."""
        self._series = series
        self._draw()
        self._hover.setVisible(False)
        self._crosshair.setVisible(False)

    def _draw(self) -> None:
        """Draw the series as curves, or as a bar chart's bars, and their legend."""
        plot = self.getPlotItem()
        is_bar = self._kind is ChartKind.BAR
        curve_count, bar_count = (0, len(self._series)) if is_bar else (len(self._series), 0)
        for items, count, make in (
            (self._items, curve_count, lambda: plot.plot(connect="finite")),
            (self._bars, bar_count, self._make_bars),
        ):
            while len(items) > count:
                plot.removeItem(items.pop())
            while len(items) < count:
                items.append(make())
        for item, curve in zip(self._items, self._series):
            item.setData(np.asarray(curve.x, dtype=float), np.asarray(curve.y, dtype=float))
            item.opts["name"] = curve.name
        ticks = [list(enumerate(self._categories))] if is_bar else None
        plot.getAxis("bottom").setTicks(ticks)
        self._apply_styles()

    def _make_bars(self) -> pg.BarGraphItem:
        bars = pg.BarGraphItem(x0=[], height=[], width=1)
        self.getPlotItem().addItem(bars)
        return bars

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
        # over the data, so its names stay readable over a curve or a bar
        legend_background = QColor(background)
        legend_background.setAlpha(200)
        self._legend.setBrush(legend_background)
        self._hover.setColor(text)
        crosshair = QColor(text)
        crosshair.setAlpha(120)
        self._crosshair.setPen(pg.mkPen(crosshair))
        self._apply_styles()

    def _apply_styles(self) -> None:
        is_dark = self._is_dark()
        background = self.palette().color(QPalette.ColorRole.Window)
        for index, (item, curve) in enumerate(zip(self._items, self._series)):
            color = series_color(index, is_dark=is_dark)
            if ChartView.kind_of(curve, self._kind) is ChartKind.SCATTER:
                item.setPen(None)
                # past the palette, around again as triangles
                item.setSymbol("t" if is_dashed(index) else "o")
                item.setSymbolSize(_DOT_SIZE)
                item.setSymbolBrush(color)
                # a ring of the background: overlapping dots stay apart
                item.setSymbolPen(pg.mkPen(background, width=1))
            else:
                item.setSymbol(None)
                style = {"dash": [6, 4]} if is_dashed(index) else {}
                item.setPen(pg.mkPen(color, width=2, **style))
        for index, (bars, curve) in enumerate(zip(self._bars, self._series)):
            heights = np.asarray(ChartView.bar_heights(curve, len(self._categories)))
            categories = np.flatnonzero(np.isfinite(heights))  # a NaN: no bar
            offset, width = ChartView.bar_slot(index, len(self._series))
            bars.setOpts(
                x0=categories + offset - width / 2,
                height=heights[categories],
                width=width,
                brush=series_color(index, is_dark=is_dark),
                # a line of the background between neighbouring bars
                pen=pg.mkPen(background, width=1),
                name=curve.name,
            )
        # the legend's samples draw the styles their items had when added
        self._legend.clear()
        for item, curve in zip(self._items or self._bars, self._series):
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
        lines = self._hover_lines(position.x())
        if len(lines) == 0:  # between a bar chart's categories, or past them
            self._hover.setVisible(False)
            self._crosshair.setVisible(False)
            return
        self._crosshair.setPos(position.x())
        self._crosshair.setVisible(True)
        self._hover.setText("\n".join(lines))
        self._hover.setPos(position)
        self._hover.setVisible(True)

    def _hover_lines(self, x: float) -> list[str]:
        """Get what the hover shows at `x`: where it is, then each series' value there."""
        x_unit, y_unit = self._units
        if self._kind is ChartKind.BAR:
            category = round(x)
            if not 0 <= category < len(self._categories):
                return []
            lines = [self._categories[category]]
            for curve in self._series:
                height = ChartView.bar_heights(curve, len(self._categories))[category]
                if math.isfinite(height):
                    lines.append(f"{curve.name}: {_format(height, y_unit)}")
            return lines
        lines = [_format(x, x_unit)]
        for curve in self._series:
            point = _nearest(curve, x)
            if point is not None:
                lines.append(f"{curve.name}: {_format(point[1], y_unit)}")
        return lines


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

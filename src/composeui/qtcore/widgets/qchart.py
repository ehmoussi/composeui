"""A chart widget over pyqtgraph: fast with long series, zoomed and panned with the mouse."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

import numpy as np
import pyqtgraph as pg
from qtpy.QtCore import QEvent, QPointF, QRectF, QSize, Qt
from qtpy.QtCore import Signal as QtSignal
from qtpy.QtGui import QAction, QColor, QFont, QPalette
from qtpy.QtWidgets import QGraphicsItem

from composeui.core import chartimage
from composeui.core.chartcolors import is_dashed, series_color
from composeui.core.view import Axis, BarMode, ChartKind, ChartView, LineStyle

if TYPE_CHECKING:
    import numpy.typing as npt
    from qtpy.QtWidgets import QWidget

    from composeui.core.view import ReferenceLine, Series

#: the hover values' rate, per second: a mouse sends far more moves than that
_HOVER_RATE = 30
#: the lightness (of 255) under which a background is dark
_DARK_LIGHTNESS = 128
#: the size a chart asks of its layout, in pixels: pyqtgraph's own, before it is shown
_SIZE_HINT = (600, 480)
#: a scatter's dots, in pixels
_DOT_SIZE = 8


#: a reference line's pen style, by its style
_LINE_STYLES = {
    LineStyle.SOLID: Qt.PenStyle.SolidLine,
    LineStyle.DASHED: Qt.PenStyle.DashLine,
    LineStyle.DOTTED: Qt.PenStyle.DotLine,
    LineStyle.DASH_DOT: Qt.PenStyle.DashDotLine,
}


def _format(value: float, unit: str, *, is_whole: bool = False) -> str:
    # a count as it is; else its trailing zeros kept: as many digits wherever the cursor
    # is, as on the web
    text = f"{value:.0f}" if is_whole else f"{value:#.4g}"
    return f"{text} {unit}".rstrip()


def _tabular_font() -> QFont:
    """Get the application's font with digits of one width, where Qt has them (6.7)."""
    font = QFont()
    if hasattr(font, "setFeature") and hasattr(QFont, "Tag"):  # pragma: no branch
        font.setFeature(QFont.Tag("tnum"), 1)
    return font


def _values(bounds: list[float], *, is_log: bool) -> tuple[float, float]:
    """Get the values of a view's range: on a log axis, the view holds their logs."""
    low, high = bounds
    if is_log:
        return float(10**low), float(10**high)
    return float(low), float(high)


class _XExtent(pg.GraphicsObject):  # type: ignore[misc]
    """The x that the second y axis' items reach, for the plot's own view to fit.

    That view fits its own items alone, and the second view follows its x: without it,
    a bar of the second y axis past the others would be cut. It draws nothing.
    """

    def __init__(self) -> None:
        super().__init__()
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemHasNoContents)
        self._bounds: list[float] | None = None

    def set_bounds(self, bounds: list[float] | None) -> None:
        self._bounds = bounds
        self.informViewBoundsChanged()

    def dataBounds(  # noqa: N802
        self,
        ax: int,
        frac: float = 1.0,
        orthoRange: object = None,  # noqa: N803
    ) -> list[float] | None:
        """Get its bounds along the x axis (0), as pyqtgraph asks an item: none along y."""
        del frac, orthoRange
        return self._bounds if ax == 0 else None

    def boundingRect(self) -> QRectF:  # noqa: N802
        return QRectF()


class QChart(pg.PlotWidget):  # type: ignore[misc]
    """A chart of series; hovering it shows each series' point nearest the cursor's x.

    Its colors follow the application's palette, changing with it (a dark scheme).
    """

    #: the user asked for the chart's image, from its context menu's Save Image
    save_image_requested = QtSignal()
    #: the user clicked the plot at a point, as the axes' values (not their logs)
    point_clicked = QtSignal(float, float)
    #: whether `__init__` is done: pyqtgraph's own changes the palette before it is
    _is_built = False

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._series: list[Series] = []
        self._categories: list[str] = []
        self._bar_mode = BarMode.GROUPED
        self._x = Axis()
        self._y = Axis()
        self._y2 = Axis()
        #: each series' item, of its kind: a curve (its dots too) or its bars
        self._items: list[pg.PlotDataItem | pg.BarGraphItem] = []
        #: whether each of `_items` is in the second y axis' view
        self._on_y2: list[bool] = []
        self._reference_lines: list[ReferenceLine] = []
        #: each reference line drawn, and whether it is in the second y axis' view
        self._line_items: list[tuple[pg.InfiniteLine, bool]] = []
        plot = self.getPlotItem()
        #: the view of what is on the second y axis, at the plot's x and drawn over the
        #: plot's own series, e.g. a line over bars
        self._view2 = pg.ViewBox()
        self._view2.setZValue(1)
        # the mouse goes to the plot's own view, under it: that one zooms and pans, and
        # this one follows its x, and its y in proportion (see `_follow_y`)
        self._view2.setEnabled(False)
        #: the x that the second view's items reach, which the plot's view fits too
        self._extent2 = _XExtent()
        plot.addItem(self._extent2)
        #: over both views, for the legend: the second view would draw over it
        self._overlay = pg.GraphicsWidget()
        self._overlay.setZValue(2)
        for item in (self._view2, self._overlay):
            plot.scene().addItem(item)
        plot.getAxis("right").linkToView(self._view2)
        self._view2.setXLink(plot)
        plot.getViewBox().sigResized.connect(self._fit_view2)
        #: the plot's own y range, before its last change, which the second view follows
        self._y_range = tuple(plot.getViewBox().viewRange()[1])
        # the axes' bounds first, which `_follow_y` then reads
        plot.getViewBox().sigXRangeChanged.connect(self._keep_x_bounds)
        plot.getViewBox().sigYRangeChanged.connect(self._keep_y_bounds)
        plot.getViewBox().sigYRangeChanged.connect(self._follow_y)
        self._view2.sigYRangeChanged.connect(self._keep_y2_bounds)
        self._legend = plot.addLegend()
        self._legend.setParentItem(self._overlay)
        # pyqtgraph thins and clips what it draws itself: a million points stay fluid
        plot.setDownsampling(auto=True, mode="peak")
        plot.setClipToView(True)
        self._show_grid()
        self._crosshair = pg.InfiniteLine(angle=90, movable=False)
        self._crosshair.setVisible(False)
        self._hover = pg.TextItem(anchor=(0, 1))
        # its values change as the cursor moves, without changing their width
        self._hover.setFont(_tabular_font())
        self._hover.setVisible(False)
        # in the second view, over everything either view draws; it has the plot's x
        for item in (self._crosshair, self._hover):
            self._add(item, z=2, on_y2=True, ignore_bounds=True)
        self.scene().sigMouseClicked.connect(self._on_mouse_clicked)
        self._mouse_proxy = pg.SignalProxy(
            self.scene().sigMouseMoved, rateLimit=_HOVER_RATE, slot=self._on_mouse_moved
        )
        #: beside pyqtgraph's own Export, which stays for CSV; only with matplotlib, which
        #: draws the image
        self.save_image_action = QAction(self)
        self.save_image_action.triggered.connect(self.save_image_requested.emit)
        if chartimage.is_available():
            plot.getViewBox().menu.addAction(self.save_image_action)
        self._is_built = True
        self._apply_palette()

    def set_title(self, title: str) -> None:
        self.getPlotItem().setTitle(title or None)

    def set_axis(self, side: str, axis: Axis) -> None:
        """Show `axis` at a `side`, labeled, as a log axis or a linear one.

        At the "bottom" the x, at the "left" the y, and at the "right" the second y, which
        shows only with something on it. pyqtgraph scales the unit, e.g. into ms. An x of
        categories or bars stays linear.
        """
        self.getPlotItem().setLabel(side, axis.title or None, units=axis.unit or None)
        view_box = self.getPlotItem().getViewBox()
        old = {"bottom": self._x, "left": self._y}.get(side, self._y2)
        if side == "bottom":
            self._x = axis
        elif side == "left":
            self._y = axis
        else:
            self._y2 = axis
        self._draw()
        if (old.minimum, old.maximum) != (axis.minimum, axis.maximum):
            # the app's new bounds, over the user's zoom: the view fits the data again
            view = self._view2 if side == "right" else view_box
            index = 0 if side == "bottom" else 1
            view.enableAutoRange(axis=index)
            self._keep_bounds(view, index)

    def _keep_x_bounds(self, view_box: pg.ViewBox, _x_range: tuple[float, float]) -> None:
        self._keep_bounds(view_box, 0)

    def _keep_y_bounds(self, view_box: pg.ViewBox, _y_range: tuple[float, float]) -> None:
        self._keep_bounds(view_box, 1)

    def _keep_y2_bounds(self, view_box: pg.ViewBox, _y_range: tuple[float, float]) -> None:
        self._keep_bounds(view_box, 1)

    def _keep_bounds(self, view_box: pg.ViewBox, index: int) -> None:
        """Give a view that fits its data its axis' bounds: pyqtgraph fits the data alone.

        Not once the user zoomed, which stops it fitting: back out, it fits them again. An
        x axis of categories has no bounds.
        """
        if index == 0:
            axis, is_log = self._x, self._x_log
            if len(self._categories) > 0:
                return
        elif view_box is self._view2:
            axis, is_log = self._y2, self._y2.is_log
        else:
            axis, is_log = self._y, self._y.is_log
        if not axis.has_bounds or view_box.autoRangeEnabled()[index] is False:
            return
        shown = view_box.viewRange()[index]
        low, high = (10**value for value in shown) if is_log else shown
        bounded = axis.bounded(low, high)
        target = [math.log10(value) for value in bounded] if is_log else list(bounded)
        if not np.allclose(target, shown):
            # still fitting the data: a change of the data fits it again
            view_box.setRange(
                **{"xRange" if index == 0 else "yRange": target},
                padding=0,
                disableAutoRange=False,
            )

    def _follow_y(self, view_box: pg.ViewBox, _y_range: tuple[float, float]) -> None:
        """Zoom and pan the second y axis as the user does the first, in proportion.

        The two axes then show the same part of the plot. While the first fits its data,
        e.g. once the user double clicks, the second fits its own. The view's range, not
        the signal's: `_keep_bounds` may have bounded it since.
        """
        (low, high), self._y_range = self._y_range, tuple(view_box.viewRange()[1])
        y_range = self._y_range
        if view_box.autoRangeEnabled()[1] is not False:
            self._view2.enableAutoRange(y=True)
            return
        # pyqtgraph never gives a view an empty range
        low2, high2 = self._view2.viewRange()[1]
        scale = (high2 - low2) / (high - low)
        self._view2.setYRange(
            low2 + (y_range[0] - low) * scale, low2 + (y_range[1] - low) * scale, padding=0
        )

    def _fit_view2(self) -> None:
        """Keep the second y axis' view over the plot's own, as the plot is laid out."""
        view_box = self.getPlotItem().getViewBox()
        for item in (self._view2, self._overlay):
            item.setGeometry(view_box.sceneBoundingRect())
        self._view2.linkedViewChanged(view_box, self._view2.XAxis)

    def _holder(self, *, on_y2: bool) -> pg.PlotItem | pg.ViewBox:
        """Get what holds the items of a y axis: the plot, or the second y axis' view."""
        return self._view2 if on_y2 else self.getPlotItem()

    def _is_log(self, *, on_y2: bool) -> bool:
        return self._y2.is_log if on_y2 else self._y.is_log

    @property
    def _x_log(self) -> bool:
        return ChartView.is_x_log(self._x, self._categories, self._series)

    def set_bar_mode(self, bar_mode: BarMode) -> None:
        """Place the bars at an x beside each other, or stacked."""
        self._bar_mode = bar_mode
        self._draw()

    def set_categories(self, categories: list[str]) -> None:
        """Show the categories on the x axis, each at its index."""
        self._categories = categories
        self._draw()

    def set_series(self, series: list[Series]) -> None:
        """Show `series`, reusing the items drawn: the zoom stays where the user put it."""
        self._series = series
        self._draw()
        self._hover.setVisible(False)
        self._crosshair.setVisible(False)

    def set_reference_lines(self, lines: list[ReferenceLine]) -> None:
        """Draw lines at values, each in its style, labeled beside itself."""
        self._reference_lines = lines
        self._draw()

    def _show_grid(self) -> None:
        plot = self.getPlotItem()
        plot.showGrid(x=True, y=True, alpha=0.15)
        # each axis, a new one too: `showGrid` changes only what its menu's boxes don't hold
        plot.updateGrid()
        plot.getAxis("right").setGrid(False)  # the left axis' lines alone

    def _fit_bottom_axis(self) -> None:
        """Give a time axis pyqtgraph's dates, in UTC as they were given; numbers else."""
        plot = self.getPlotItem()
        is_time = ChartView.is_x_time(self._x, self._categories)
        if isinstance(plot.getAxis("bottom"), pg.DateAxisItem) == is_time:
            return
        plot.setAxisItems(
            {"bottom": pg.DateAxisItem(utcOffset=0) if is_time else pg.AxisItem("bottom")}
        )
        # the new axis has none of the old one's settings
        plot.setLabel("bottom", self._x.title or None, units=self._x.unit or None)
        self._show_grid()
        self._apply_palette()

    def _draw(self) -> None:
        """Draw each series as its kind, on its y axis, and their legend."""
        self._fit_bottom_axis()
        plot = self.getPlotItem()
        plot.showAxis("right", ChartView.has_y2(self._series, self._reference_lines))
        for index, curve in enumerate(self._series):
            is_bars = curve.kind is ChartKind.BAR
            if index < len(self._items):
                is_same_kind = isinstance(self._items[index], pg.BarGraphItem) == is_bars
                if is_same_kind and self._on_y2[index] == curve.on_y2:
                    continue  # reused: the zoom stays where the user put it
                self._holder(on_y2=self._on_y2[index]).removeItem(self._items[index])
            self._items[index : index + 1] = [self._make_item(is_bars=is_bars, on_y2=curve.on_y2)]
            self._on_y2[index : index + 1] = [curve.on_y2]
        while len(self._items) > len(self._series):
            self._holder(on_y2=self._on_y2.pop()).removeItem(self._items.pop())
        x_log = self._x_log
        # the curves draw their log themselves; the bars are given theirs (see `_apply_styles`)
        plot.setLogMode(x=x_log, y=self._y.is_log)
        # the plot gave its right axis the left one's scale
        plot.getAxis("right").setLogMode(self._y2.is_log)
        for item, curve in zip(self._items, self._series):
            if isinstance(item, pg.BarGraphItem):
                continue  # drawn with their styles (see `_apply_styles`)
            y_log = self._is_log(on_y2=curve.on_y2)
            x, y = ChartView.drawn_points(curve, x_log=x_log, y_log=y_log)
            if self._is_step(curve):
                x, y = ChartView.step_points(x, y)
            # the plot tells its own items their log; the second view's are told here
            item.setLogMode(x_log, y_log)
            item.setData(np.asarray(x, dtype=float), np.asarray(y, dtype=float))
            item.opts["name"] = curve.name
        ticks = [list(enumerate(self._categories))] if len(self._categories) > 0 else None
        plot.getAxis("bottom").setTicks(ticks)
        self._draw_reference_lines(x_log=x_log)
        self._apply_styles()
        self._extent2.set_bounds(self._view2.childrenBounds()[0])

    def _draw_reference_lines(self, *, x_log: bool) -> None:
        """Draw the reference lines afresh: a log axis takes their logs, as pyqtgraph doesn't."""
        for item, on_y2 in self._line_items:
            self._holder(on_y2=on_y2).removeItem(item)
        self._line_items = []
        for line in self._drawn_lines():
            is_log = x_log if line.vertical else self._is_log(on_y2=line.is_on_y2)
            item = pg.InfiniteLine(
                pos=math.log10(line.value) if is_log else line.value,
                angle=90 if line.vertical else 0,
                movable=False,
                # the label is a format of the line's value: braces of its own are text
                label=line.label.replace("{", "{{").replace("}", "}}"),
                # a horizontal one's at its right end, over it; a vertical one's at its
                # top, left of it (now, after the data)
                labelOpts={
                    "position": 0.98,
                    "anchors": [(1, 0), (1, 0)] if line.vertical else [(1, 1), (1, 1)],
                },
            )
            self._add(item, z=1, on_y2=line.is_on_y2)  # over the series
            self._line_items.append((item, line.is_on_y2))

    def _drawn_lines(self) -> list[ReferenceLine]:
        return ChartView.drawn_lines(
            self._reference_lines,
            x_log=self._x_log,
            y_log=self._y.is_log,
            y2_log=self._y2.is_log,
        )

    def _make_item(self, *, is_bars: bool, on_y2: bool) -> pg.PlotDataItem | pg.BarGraphItem:
        item: pg.PlotDataItem | pg.BarGraphItem
        if is_bars:
            item = pg.BarGraphItem(x0=[], height=[], width=1)
        else:
            item = pg.PlotDataItem(connect="finite")
            # as the plot's own items, which it thins and clips itself
            item.setDownsampling(auto=True, method="peak")
            item.setClipToView(True)
        self._add(item, z=-1 if is_bars else 0, on_y2=on_y2)  # the bars under the lines and dots
        return item

    def _add(
        self, item: pg.GraphicsObject, *, z: float, on_y2: bool, ignore_bounds: bool = False
    ) -> None:
        """Add `item` to the view of a y axis, stacked at `z` among that view's items.

        Set after: a view raises an item stacked under itself, as the second one is.
        """
        self._holder(on_y2=on_y2).addItem(item, ignoreBounds=ignore_bounds)
        item.setZValue(z)

    def shown_range(self) -> tuple[tuple[float, float], tuple[float, float]]:
        """Get the x and y ranges the chart shows, e.g. zoomed into; not their logs."""
        x_range, y_range = self.getPlotItem().getViewBox().viewRange()
        return _values(x_range, is_log=self._x_log), _values(y_range, is_log=self._y.is_log)

    def shown_y2_range(self) -> tuple[float, float] | None:
        """Get the range the second y axis shows, not its logs; None while it doesn't show."""
        if not ChartView.has_y2(self._series, self._reference_lines):
            return None
        return _values(self._view2.viewRange()[1], is_log=self._y2.is_log)

    def sizeHint(self) -> QSize:  # noqa: N802
        # not its scene's, which follows its own size: a height it was given once would stay
        return QSize(*_SIZE_HINT)

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
        for name in ("bottom", "left", "right"):
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
        all_bars = {
            index: ChartView.bars_of(curve, self._categories, y_log=self._is_log(on_y2=curve.on_y2))
            for index, curve in enumerate(self._series)
            if curve.kind is ChartKind.BAR
        }
        slots = ChartView.bar_slots(self._series, self._categories, self._bar_mode)
        stacks = (
            ChartView.stack_bases(self._series, self._categories)
            if self._bar_mode is BarMode.STACKED
            else {}
        )
        for index, (item, curve) in enumerate(zip(self._items, self._series)):
            color = curve.color or series_color(index, is_dark=is_dark)
            if isinstance(item, pg.BarGraphItem):
                is_log = self._is_log(on_y2=curve.on_y2)
                drawn = [
                    height
                    for other, (_xs, heights) in all_bars.items()
                    if self._series[other].on_y2 == curve.on_y2
                    for height in heights
                ]
                # on a log axis, the bars rise from the power of 10 under the lowest of its
                base = math.floor(math.log10(min(drawn))) if is_log and len(drawn) > 0 else 0
                xs, heights = (np.asarray(values, dtype=float) for values in all_bars[index])
                tops = np.log10(heights) if is_log else heights
                # each bar's own start when stacked, else the one of them all
                starts: float | npt.NDArray[np.float64] = base
                if index in stacks:  # on the values before it: never on a log axis
                    starts = np.asarray(stacks[index], dtype=float)
                    tops = starts + heights
                offset, width = slots[index]
                item.setOpts(
                    x0=xs + offset - width / 2,
                    y0=starts,
                    height=tops - starts,
                    width=width,
                    brush=color,
                    # a line of the background between neighbouring bars
                    pen=pg.mkPen(background, width=1),
                    name=curve.name,
                )
                continue
            # filled down to 0, e.g. a shape
            item.setFillLevel(0 if curve.fill else None)
            item.setBrush((curve.fill_color or color) if curve.fill else None)
            if curve.kind is ChartKind.SCATTER:
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
        text = self.palette().color(QPalette.ColorRole.WindowText)
        for (item, _on_y2), line in zip(self._line_items, self._drawn_lines()):
            ink = QColor(line.color) if line.color is not None else text
            item.setPen(pg.mkPen(ink, width=1.5, style=_LINE_STYLES[line.style]))
            item.label.setColor(ink)
        # the legend's samples draw the styles their items had when added
        self._legend.clear()
        for item, curve in zip(self._items, self._series):
            self._legend.addItem(item, curve.name)

    def _on_mouse_clicked(self, event: Any) -> None:
        if event.button() != Qt.MouseButton.LeftButton or event.double():
            return  # the right button opens the context menu
        self.click(event.scenePos())

    def click(self, scene_position: QPointF) -> None:
        """Emit `point_clicked` for a click at `scene_position`, if it is on the plot."""
        view_box = self.getPlotItem().getViewBox()
        if not view_box.sceneBoundingRect().contains(scene_position):
            return
        position = view_box.mapSceneToView(scene_position)
        x, y = position.x(), position.y()
        # the view's values are their logs on a log axis
        if self._x_log:
            x = 10**x
        if self._y.is_log:
            y = 10**y
        self.point_clicked.emit(float(x), float(y))

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
        # the view's x is its log on a log axis
        lines = self._hover_lines(10 ** position.x() if self._x_log else position.x())
        if len(lines) == 0:  # past the categories
            self._hover.setVisible(False)
            self._crosshair.setVisible(False)
            return
        self._crosshair.setPos(position.x())
        self._crosshair.setVisible(True)
        self._hover.setText("\n".join(lines))
        # in the second view's values, where it is drawn
        self._hover.setPos(self._view2.mapSceneToView(scene_position))
        self._hover.setVisible(True)

    def _hover_lines(self, x: float) -> list[str]:
        """Get what the hover shows at `x`: where it is, then each series' value there."""
        if len(self._categories) > 0:
            category = round(x)
            if not 0 <= category < len(self._categories):
                return []
            lines = [self._categories[category]]
        elif ChartView.is_x_time(self._x, self._categories):
            # as precise as the series' own times
            time_format = ChartView.time_format(x for curve in self._series for x in curve.x)
            lines = [ChartView.time_text(x, time_format)]
        else:
            lines = [_format(x, self._x.unit)]
        # a bar is hovered across its group's room
        reach = ChartView.bar_step(self._series, self._categories) / 2
        for curve in self._series:
            y: float | None
            y_log = self._is_log(on_y2=curve.on_y2)
            if curve.kind is ChartKind.BAR:
                point = _nearest(*ChartView.bars_of(curve, self._categories, y_log=y_log), x)
                y = None if point is None or abs(point[0] - x) > reach else point[1]
            else:
                points = ChartView.drawn_points(curve, x_log=self._x_log, y_log=y_log)
                if self._is_step(curve):
                    # the value held there, rather than the next point's
                    held = ChartView.held_value(*points, x)
                    y = None if held is None or math.isnan(held) else held
                else:
                    point = _nearest(*points, x)
                    y = None if point is None else point[1]
            if y is not None:
                # in its own y axis' unit
                unit = self._y2.unit if curve.on_y2 else self._y.unit
                value = _format(y, unit, is_whole=ChartView.is_whole(curve.y))
                lines.append(f"{curve.name}: {value}")
        return lines

    def _is_step(self, curve: Series) -> bool:
        """Tell whether `curve` is drawn in steps: a line's points only, not dots."""
        return curve.step and curve.kind is ChartKind.LINE


def _nearest(x_values: list[float], y_values: list[float], x: float) -> tuple[float, float] | None:
    """Get the drawn point with the x nearest `x`, None when none is drawn."""
    xs = np.asarray(x_values, dtype=float)
    ys = np.asarray(y_values, dtype=float)
    drawn = np.isfinite(xs) & np.isfinite(ys)
    if not drawn.any():
        return None
    distances = np.where(drawn, np.abs(xs - x), math.inf)
    index = int(np.argmin(distances))
    return float(xs[index]), float(ys[index])

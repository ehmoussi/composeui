from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from qtpy.QtCore import QPointF, QRectF, QSize, Qt
from qtpy.QtGui import QBrush, QColor, QFontMetricsF, QPainter, QPalette, QPen, QPolygonF
from qtpy.QtWidgets import QSizePolicy, QWidget

from composeui.core.view import (
    ArrowShape,
    CircleShape,
    DrawingPlacement,
    DrawingView,
    LineShape,
    LineStyle,
    LineWeight,
    PolygonShape,
    PolylineShape,
    TextAnchor,
    TextShape,
)
from composeui.qtcore.widgets.qplaintext import plain_tool_tip
from composeui.qtcore.widgets.qtextrole import role_color, role_font, role_palette_color

if TYPE_CHECKING:
    from qtpy.QtGui import QPaintEvent

    from composeui.core.view import Shape

#: a line's width and an arrow head's length, in pixels at any scale
_LINE_WIDTHS = {LineWeight.LIGHT: 1.0, LineWeight.NORMAL: 2.0, LineWeight.HEAVY: 4.0}
_ARROW_HEAD_LENGTH = 11.0
_DEFAULT_HEIGHT = 288
_PEN_STYLES = {
    LineStyle.SOLID: Qt.PenStyle.SolidLine,
    LineStyle.DASHED: Qt.PenStyle.DashLine,
    LineStyle.DOTTED: Qt.PenStyle.DotLine,
    LineStyle.DASH_DOT: Qt.PenStyle.DashDotLine,
}


class QDrawing(QWidget):
    """A `DrawingView`'s shapes, painted to fit the widget with one scale for both axes."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.shapes: list[Shape] = []
        self.bounds: tuple[float, float, float, float] | None = None
        self.description = ""
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt's name)
        return QSize(_DEFAULT_HEIGHT * 2, _DEFAULT_HEIGHT)

    def set_drawing(self) -> None:
        """Paint the shapes again and describe them."""
        description = DrawingView.shown_description(self.description, self.shapes)
        self.setAccessibleDescription(description)
        self.setToolTip(plain_tool_tip(description))
        self.update()

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 (Qt's name)
        bounds = DrawingView.shown_bounds(self.shapes, self.bounds)
        placement = DrawingView.placement(bounds, self.width(), self.height())
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setClipRect(
                QRectF(
                    _point(placement, (bounds[0], bounds[3])),
                    _point(placement, (bounds[2], bounds[1])),
                )
            )
            for shape in self.shapes:
                self._paint_shape(painter, placement, bounds, shape)
        finally:
            # a painter left open refuses the next paint of this widget
            painter.end()

    def _color(self, color: str | None) -> QColor:
        return (
            self.palette().color(QPalette.ColorRole.WindowText) if color is None else QColor(color)
        )

    def _text_color(self, shape: TextShape) -> QColor:
        """Get a text's color: its own, else its role's, else the theme's text color."""
        if shape.color is not None:
            return QColor(shape.color)
        color = role_color(shape.role)
        if color is not None:
            return QColor(color)
        palette_role = role_palette_color(shape.role)
        if palette_role == QPalette.ColorRole.NoRole:
            palette_role = QPalette.ColorRole.WindowText
        return self.palette().color(palette_role)

    def _paint_shape(
        self,
        painter: QPainter,
        placement: DrawingPlacement,
        bounds: tuple[float, float, float, float],
        shape: Shape,
    ) -> None:
        color = self._color(shape.color)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setClipping(True)
        if isinstance(shape, TextShape):
            if DrawingView.in_bounds(shape.position, bounds):
                # past the edge too: a label near it stays readable
                painter.setClipping(False)
                painter.setFont(role_font(shape.role).resolve(self.font()))
                painter.setPen(self._text_color(shape))
                _paint_text(painter, placement.point(shape.position), shape)
            return
        painter.setPen(QPen(color, _LINE_WIDTHS[shape.weight], _PEN_STYLES[shape.style]))
        if isinstance(shape, LineShape):
            painter.drawLine(_point(placement, shape.start), _point(placement, shape.end))
        elif isinstance(shape, ArrowShape):
            self._paint_arrow(painter, placement, bounds, shape, color)
        elif isinstance(shape, PolylineShape):
            painter.drawPolyline(QPolygonF([_point(placement, p) for p in shape.points]))
        else:
            if shape.fill:
                painter.setBrush(QBrush(color))
            if isinstance(shape, PolygonShape):
                painter.drawPolygon(QPolygonF([_point(placement, p) for p in shape.points]))
            else:
                assert isinstance(shape, CircleShape)
                radius = shape.radius * placement.scale
                painter.drawEllipse(_point(placement, shape.center), radius, radius)

    @staticmethod
    def _paint_arrow(
        painter: QPainter,
        placement: DrawingPlacement,
        bounds: tuple[float, float, float, float],
        shape: ArrowShape,
        color: QColor,
    ) -> None:
        tail, tip = placement.point(shape.start), placement.point(shape.end)
        left, right = DrawingView.arrow_head(tail, tip, _ARROW_HEAD_LENGTH)
        # the line stops inside the head, so that its end doesn't poke through the tip
        middle = QPointF((left[0] + right[0]) / 2, (left[1] + right[1]) / 2)
        if math.dist(tail, tip) > _ARROW_HEAD_LENGTH:
            painter.drawLine(QPointF(*tail), middle)
        if not DrawingView.in_bounds(shape.end, bounds):
            return
        painter.setClipping(False)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(color))
        painter.drawPolygon(QPolygonF([QPointF(*tip), QPointF(*left), QPointF(*right)]))


def _point(placement: DrawingPlacement, point: tuple[float, float]) -> QPointF:
    return QPointF(*placement.point(point))


def _paint_text(painter: QPainter, position: tuple[float, float], shape: TextShape) -> None:
    metrics = QFontMetricsF(painter.font())
    rect: QRectF = metrics.boundingRect(shape.text)
    shift = {TextAnchor.START: 0.0, TextAnchor.MIDDLE: 0.5, TextAnchor.END: 1.0}[shape.anchor]
    painter.drawText(
        QPointF(
            position[0] - rect.width() * shift,
            position[1] + (metrics.ascent() - metrics.descent()) / 2,
        ),
        shape.text,
    )

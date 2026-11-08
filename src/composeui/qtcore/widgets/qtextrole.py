"""How Qt shows a `TextRole`: its font and its color."""

from __future__ import annotations

from typing import TYPE_CHECKING

from qtpy.QtGui import QFont, QPalette
from qtpy.QtWidgets import QApplication

from composeui.core.view import TextRole

if TYPE_CHECKING:
    from typing import Optional

#: the size of a role's text, as a factor of the app's font, and its weight
_ROLE_FONTS = {
    TextRole.TITLE: (1.5, QFont.Weight.Bold),
    TextRole.SUBTITLE: (1.2, QFont.Weight.DemiBold),
    TextRole.CAPTION: (0.85, QFont.Weight.Normal),
}
_ROLE_COLORS = {
    TextRole.ERROR: "red",
    TextRole.WARNING: "orange",
    TextRole.SUCCESS: "green",
}
_MUTED_ROLES = (TextRole.CAPTION, TextRole.MUTED, TextRole.SUBTITLE)


def role_font(role: TextRole) -> QFont:
    """Get the font of `role`: one that sets nothing takes all of its parent's."""
    font = QFont()
    if role in _ROLE_FONTS:
        factor, weight = _ROLE_FONTS[role]
        app_font = QApplication.font()
        # a font has its size in points or in pixels: the other one reads as -1
        if app_font.pixelSize() > 0:
            font.setPixelSize(round(app_font.pixelSize() * factor))
        else:
            font.setPointSizeF(app_font.pointSizeF() * factor)
        font.setWeight(weight)
    return font


def role_palette_color(role: TextRole) -> QPalette.ColorRole:
    """Get the palette's color of `role`: `NoRole` follows the widget's own."""
    return QPalette.ColorRole.PlaceholderText if role in _MUTED_ROLES else QPalette.ColorRole.NoRole


def role_color(role: TextRole) -> Optional[str]:
    """Get the name of the color of `role` that no palette holds, if it has one."""
    return _ROLE_COLORS.get(role)

from __future__ import annotations

from typing import Any

from qtpy.QtCore import Qt
from qtpy.QtWidgets import QLabel, QVBoxLayout, QWidget

#: the badge's text color and its tint behind, for a rise and a fall; readable on a light
#: and a dark palette alike
_RISE_STYLE = "QLabel { color: #16a34a; background: rgba(22, 163, 74, 0.15); }"
_FALL_STYLE = "QLabel { color: #dc2626; background: rgba(220, 38, 38, 0.15); }"
_FLAT_STYLE = "QLabel { background: rgba(128, 128, 128, 0.15); }"
_BADGE_STYLE = "QLabel { border-radius: 4px; padding: 1px 6px; }"


class QMetric(QWidget):
    """A metric: its label, its value in a large bold font, then its change as a badge."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel()
        layout.addWidget(self.label)
        self.value = QLabel()
        font = self.value.font()
        font.setPointSizeF(font.pointSizeF() * 2)
        font.setBold(True)
        self.value.setFont(font)
        layout.addWidget(self.value)
        self.badge = QLabel()
        self.badge.setVisible(False)
        # as wide as its text, not the column
        layout.addWidget(self.badge, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addStretch()

    def set_delta(self, badge: str, sign: int) -> None:
        """Show `badge`, colored by the `sign` of its change; an empty one hides it."""
        self.badge.setText(badge)
        self.badge.setVisible(badge != "")
        tint = _RISE_STYLE if sign > 0 else _FALL_STYLE if sign < 0 else _FLAT_STYLE
        self.badge.setStyleSheet(f"{_BADGE_STYLE} {tint}")

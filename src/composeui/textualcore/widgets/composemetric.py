from __future__ import annotations

from typing import TYPE_CHECKING

from textual.containers import Vertical
from textual.widgets import Label

if TYPE_CHECKING:
    from textual.app import ComposeResult


class ComposeMetric(Vertical):
    """A metric: its label, its value in bold, then its change as a badge.

    A terminal has one font size; the value stands out by its weight alone.
    """

    DEFAULT_CSS = """
    ComposeMetric {
        height: auto;
        width: 1fr;
    }
    ComposeMetric > .metric--label {
        color: $text-muted;
    }
    ComposeMetric > .metric--value {
        text-style: bold;
    }
    ComposeMetric > .metric--badge {
        padding: 0 1;
        background: $surface-lighten-1;
        &.-rise {
            color: $text-success;
            background: $success-muted;
        }
        &.-fall {
            color: $text-error;
            background: $error-muted;
        }
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.label = Label(classes="metric--label")
        self.value = Label(classes="metric--value")
        self.badge = Label(classes="metric--badge")
        self.badge.display = False

    def compose(self) -> ComposeResult:
        yield self.label
        yield self.value
        yield self.badge

    def set_delta(self, badge: str, sign: int) -> None:
        """Show `badge`, colored by the `sign` of its change; an empty one hides it."""
        self.badge.update(badge)
        self.badge.display = badge != ""
        self.badge.set_class(sign > 0, "-rise")
        self.badge.set_class(sign < 0, "-fall")

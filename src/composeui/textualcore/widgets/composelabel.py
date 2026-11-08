"""A label styled by its text role."""

from __future__ import annotations

from typing import ClassVar

from textual.widgets import Label

from composeui.core.view import TextRole


class ComposeLabel(Label):
    """A `Label` with the look of a `TextRole`, from the app's theme."""

    # a terminal has one text size: a title differs from a subtitle by its color
    DEFAULT_CSS: ClassVar[str] = """
    ComposeLabel {
        &.-title { text-style: bold; }
        &.-subtitle { color: $text-muted; text-style: bold; }
        &.-caption { color: $text-muted; text-style: italic; }
        &.-muted { color: $text-muted; }
        &.-error { color: $text-error; }
        &.-warning { color: $text-warning; }
        &.-success { color: $text-success; }
    }
    """

    def show_role(self, role: TextRole) -> None:
        """Take the look of `role`, in place of the last one."""
        for member in TextRole:
            self.set_class(member is role, f"-{member.name.lower()}")

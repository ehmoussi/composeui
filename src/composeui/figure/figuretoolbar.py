r"""Abstract Figure view."""

try:
    from matplotlib.backends.backend_qt import NavigationToolbar2QT as NavigationToolbar
except ModuleNotFoundError:
    from matplotlib.backends.backend_qt5agg import (  # type: ignore[attr-defined]
        NavigationToolbar2QT as NavigationToolbar,
    )

from qtpy.QtGui import QIcon

from typing import Any


class FigureToolbar(NavigationToolbar):
    r"""Toolbar of Figure."""

    toolitems = list(NavigationToolbar.toolitems)  # type: ignore[has-type, assignment]  # noqa: RUF012
    toolitems.insert(  # type: ignore[has-type]
        # Add 'Legend' action after 'Customize' which is after 'Subplots'
        [name for name, *_ in toolitems].index("Subplots") + 2,  # type: ignore[has-type]
        ("Legend", "Show/Hide legend", "", "show_legend"),
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[no-untyped-call]
        self._actions["show_legend"].setIcon(QIcon(":/icons/log.png"))
        self._actions["show_legend"].setCheckable(True)
        self._actions["show_legend"].setChecked(True)

    def show_legend(self) -> None:
        r"""Show and Hide the legends."""
        for axes in self.canvas.figure.get_axes():
            legend = axes.get_legend()
            if legend is not None:
                is_visible = self._actions["show_legend"].isChecked()
                legend.set_visible(is_visible)
        self.canvas.draw()

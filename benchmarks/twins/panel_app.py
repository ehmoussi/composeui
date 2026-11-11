"""The frameworks benchmark's app on Panel: the same pages, as tabs, rows and Apply as ComposeUI's.

The tabs are `dynamic`: the browser draws only the shown one.

    panel serve panel_app.py --port PORT
"""

from __future__ import annotations

import panel as pn

PAGES = 20
ROWS = 10


def row(index: int) -> pn.Row:
    label = pn.pane.Markdown("Field")
    apply = pn.widgets.Button(name="Apply")

    def applied(_event: object) -> None:
        label.object = f"Applied {index}"

    apply.on_click(applied)
    return pn.Row(
        label,
        pn.widgets.TextInput(),
        pn.widgets.IntInput(),
        pn.widgets.Checkbox(name="On"),
        apply,
    )


def page(number: int) -> pn.Column:
    return pn.Column(pn.pane.Markdown(f"Content {number}"), *(row(r) for r in range(ROWS)))


pn.Tabs(*((f"Page {number}", page(number)) for number in range(PAGES)), dynamic=True).servable()

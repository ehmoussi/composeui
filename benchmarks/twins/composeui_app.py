"""The frameworks benchmark's app on ComposeUI, served on the web by Uvicorn.

20 pages of 10 rows. A row has a label, a text input, an int input, a checkbox and an Apply
button; Apply writes "Applied <row>" in its row's label. Each page starts with "Content <page>".

    python composeui_app.py PORT
"""

from __future__ import annotations

import sys
from typing import Any

import attrs
import uvicorn

from composeui.core.view import (
    ButtonView,
    CheckBoxView,
    HorizontalView,
    InputView,
    IntInputView,
    LabelView,
    MainView,
    PageView,
    Router,
    child,
    define_view,
)
from composeui.webcore.webapplication import WebApplication

PAGES = 20
ROWS = 10


@define_view
class Row(HorizontalView):
    index: int = attrs.field(default=0)
    label: LabelView = child(LabelView, text="Field")
    name: InputView = child(InputView)
    count: IntInputView = child(IntInputView)
    flag: CheckBoxView = child(CheckBoxView, text="On")
    apply: ButtonView = child(ButtonView, text="Apply")

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.apply.clicked.connect(self.applied)

    def applied(self) -> None:
        self.label.text = f"Applied {self.index}"


def _page(number: int) -> type[PageView]:
    """Build the page class `Page<number>`: a heading, then the rows."""
    annotations: dict[str, Any] = {"heading": LabelView}
    namespace: dict[str, Any] = {
        "route": f"p{number}",
        "page_title": f"Page {number}",
        "heading": child(LabelView, text=f"Content {number}"),
    }
    for row in range(ROWS):
        annotations[f"r{row}"] = Row
        namespace[f"r{row}"] = child(Row, index=row)
    namespace["__annotations__"] = annotations
    return define_view(type(f"Page{number}", (PageView,), namespace))


_PAGE_CLASSES = [_page(number) for number in range(PAGES)]
Pages = define_view(
    type(
        "Pages",
        (Router,),
        {
            "__annotations__": {f"p{n}": cls for n, cls in enumerate(_PAGE_CLASSES)},
            **{f"p{n}": child(cls) for n, cls in enumerate(_PAGE_CLASSES)},
        },
    )
)


@define_view
class BenchMainView(MainView):
    app_title = "Benchmark"
    extension = ".bench"

    pages: Pages = child(Pages)


def main() -> None:
    app = WebApplication(build_main_view=BenchMainView).create_starlette_app()
    uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]), log_level="warning")


if __name__ == "__main__":
    main()

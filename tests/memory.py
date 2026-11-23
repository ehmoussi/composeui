"""A memory typed as "4 GB" or "4096 MB", shared by the tests of `ParsedInputView`."""

from __future__ import annotations

import re

from attrs import Factory

from composeui.core.view import (
    FormView,
    LabelRowParsedInputView,
    MainView,
    child,
    define_view,
)

_MEMORY = re.compile(r"\s*(\d+)\s*(MB|GB)?\s*", re.IGNORECASE)


def memory_mb(text: str) -> int:
    """Read a memory in MB, e.g. 4000 from "4 GB" or "4gb", 4096 from "4096" or "4096 MB"."""
    matched = _MEMORY.fullmatch(text)
    if matched is None:
        msg = f"{text!r} isn't a memory"
        raise ValueError(msg)
    factor = 1000 if (matched[2] or "MB").upper() == "GB" else 1
    return int(matched[1]) * factor


def memory_text(value: int) -> str:
    """Write a memory in GB when it is a whole number of them, else in MB."""
    return f"{value // 1000} GB" if value % 1000 == 0 else f"{value} MB"


@define_view
class MemoryForm(FormView):
    memory: LabelRowParsedInputView[int] = child(
        LabelRowParsedInputView, label="Memory", parse=memory_mb, format=memory_text, value=4096
    )


@define_view
class MemoryMainView(MainView):
    app_title = "Memory"
    extension = ".memory"

    form: MemoryForm = Factory(MemoryForm)

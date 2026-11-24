"""The rules of the text, number, date and file path fields on every backend."""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

import pytest
from attrs import Factory

from composeui.core.view import (
    DateInputView,
    FilePathInputView,
    FloatInputView,
    InputView,
    IntInputView,
    MainView,
    define_view,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from tests.contracts.support import Driver


@define_view
class _FieldsMainView(MainView):
    name: InputView = Factory(InputView)
    ratio: FloatInputView = Factory(FloatInputView)
    count: IntInputView = Factory(IntInputView)
    day: DateInputView = Factory(DateInputView)
    path: FilePathInputView = Factory(FilePathInputView)


def _set_name(view: _FieldsMainView) -> None:
    view.name.text = "Ada"


def _set_ratio(view: _FieldsMainView) -> None:
    view.ratio.value = 2.5


def _set_count(view: _FieldsMainView) -> None:
    view.count.value = 3


def _set_day(view: _FieldsMainView) -> None:
    view.day.value = datetime.date(2026, 1, 2)
    view.day.date_format = "dd/MM/yyyy"  # the text shown again, in the new format


def _set_path(view: _FieldsMainView) -> None:
    view.path.text = "flows.csv"


class _Case(NamedTuple):
    name: str  # of the field
    set_by_code: Callable[[_FieldsMainView], None]
    typed: str
    read: Callable[[_FieldsMainView], object]  # the field's value
    expected: object  # its value once typed


_CASES = [
    _Case("name", _set_name, "Bo", lambda view: view.name.text, "Bo"),
    _Case("ratio", _set_ratio, "7.5", lambda view: view.ratio.value, 7.5),
    _Case("count", _set_count, "12", lambda view: view.count.value, 12),
    _Case("day", _set_day, "03/01/2026", lambda view: view.day.value, datetime.date(2026, 1, 3)),
    _Case("path", _set_path, "sites.csv", lambda view: view.path.path, Path("sites.csv")),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("case", _CASES, ids=[case.name for case in _CASES])
async def test_a_field_reports_the_user_s_text_not_the_code_s_and_finishes_editing_when_left(
    driver: Driver, case: _Case
) -> None:
    view = _FieldsMainView()
    field = getattr(view, case.name)
    seen: list[tuple[str, str]] = []
    field.text_changed.connect(lambda text: seen.append(("changed", text)))
    field.text_edited.connect(lambda text: seen.append(("edited", text)))
    field.editing_finished.connect(lambda: seen.append(("finished", "")))

    async with driver.open(view):
        case.set_by_code(view)
        await driver.type(field, case.typed)

        edits = [text for kind, text in seen if kind == "edited"]
        # each key's text, or the page's one post: never the text code set
        assert edits[-1:] == [case.typed]
        assert all(case.typed.startswith(text) for text in edits)
        # each also as a change, in either order: Qt's line edit reports the edit first
        assert [text for kind, text in seen if kind == "changed"] == edits
        assert len(seen) == 2 * len(edits)
        assert (driver.shown_text(field), case.read(view)) == (case.typed, case.expected)

        await driver.leave(field)
        assert seen[2 * len(edits) :] == [("finished", "")]

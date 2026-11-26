"""The rules of the text, number, date and path fields on every backend."""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

import pytest
from attrs import Factory

from composeui.core.view import (
    DateInputView,
    DateRangeInputView,
    FilePathInputView,
    FloatInputView,
    FolderPathInputView,
    InputView,
    IntInputView,
    MainView,
    ParsedInputView,
    SavePathInputView,
    TextAreaView,
    define_view,
)
from tests.memory import memory_mb, memory_text
from tests.ranges import FIRST_DAY, LAST_DAY

if TYPE_CHECKING:
    from collections.abc import Callable

    from tests.contracts.support import Driver


@define_view
class _FieldsMainView(MainView):
    name: InputView = Factory(InputView)
    ratio: FloatInputView = Factory(FloatInputView)
    count: IntInputView = Factory(IntInputView)
    # bounded, as an app's date mostly is: a field cleared has both bounds
    day: DateInputView = Factory(
        lambda: DateInputView(
            minimum=datetime.date(2026, 1, 1), maximum=datetime.date(2026, 12, 31)
        )
    )
    path: FilePathInputView = Factory(FilePathInputView)
    notes: TextAreaView = Factory(TextAreaView)
    memory: ParsedInputView[int] = Factory(
        lambda: ParsedInputView(parse=memory_mb, format=memory_text)
    )
    folder: FolderPathInputView = Factory(FolderPathInputView)
    report: SavePathInputView = Factory(lambda: SavePathInputView(extensions={"PDF": (".pdf",)}))


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


def _set_notes(view: _FieldsMainView) -> None:
    view.notes.text = "One\nline each"


def _set_memory(view: _FieldsMainView) -> None:
    view.memory.value = 4096


def _set_folder(view: _FieldsMainView) -> None:
    view.folder.text = "runs"


def _set_report(view: _FieldsMainView) -> None:
    view.report.text = "summary.pdf"


class _Case(NamedTuple):
    name: str  # of the field
    set_by_code: Callable[[_FieldsMainView], None]
    typed: str
    read: Callable[[_FieldsMainView], object]  # the field's value
    expected: object  # its value once typed
    # set once the user's change is done, and the text it shows
    set_again: Callable[[_FieldsMainView], None]
    shown_again: str
    reports_value: bool = False  # whether the field reports its value too (`value_changed`)


def _clear_name(view: _FieldsMainView) -> None:
    view.name.text = ""


def _set_ratio_again(view: _FieldsMainView) -> None:
    view.ratio.value = 0.25


def _set_count_again(view: _FieldsMainView) -> None:
    view.count.value = 4


def _clear_day(view: _FieldsMainView) -> None:
    view.day.value = None


def _set_path_again(view: _FieldsMainView) -> None:
    view.path.text = "rates.csv"


def _set_notes_again(view: _FieldsMainView) -> None:
    view.notes.text = "Set by the app"


def _set_memory_again(view: _FieldsMainView) -> None:
    view.memory.value = 2000


def _set_folder_again(view: _FieldsMainView) -> None:
    view.folder.text = "archive"


def _set_report_again(view: _FieldsMainView) -> None:
    view.report.text = "totals"


_CASES = [
    _Case("name", _set_name, "Bo", lambda view: view.name.text, "Bo", _clear_name, ""),
    _Case("ratio", _set_ratio, "7.5", lambda view: view.ratio.value, 7.5, _set_ratio_again, "0.25"),
    _Case("count", _set_count, "12", lambda view: view.count.value, 12, _set_count_again, "4"),
    _Case(
        "day",
        _set_day,
        "03/01/2026",
        lambda view: view.day.value,
        datetime.date(2026, 1, 3),
        _clear_day,
        "",
        reports_value=True,
    ),
    _Case(
        "path",
        _set_path,
        "sites.csv",
        lambda view: view.path.path,
        Path("sites.csv"),
        _set_path_again,
        "rates.csv",
    ),
    _Case(
        "notes",
        _set_notes,
        "North\nside",
        lambda view: view.notes.text,
        "North\nside",
        _set_notes_again,
        "Set by the app",
    ),
    _Case(
        "memory",
        _set_memory,
        "4gb",
        lambda view: view.memory.value,
        4000,
        _set_memory_again,
        "2 GB",
    ),
    _Case(
        "folder",
        _set_folder,
        "results",
        lambda view: view.folder.path,
        Path("results"),
        _set_folder_again,
        "archive",
    ),
    _Case(
        "report",
        _set_report,
        "flows",
        lambda view: view.report.path,
        Path("flows.pdf"),
        _set_report_again,
        "totals",
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("case", _CASES, ids=[case.name for case in _CASES])
async def test_a_field_reports_the_user_s_text_not_the_code_s_and_finishes_editing_when_left(
    driver: Driver, case: _Case
) -> None:
    view = _FieldsMainView()
    field = getattr(view, case.name)
    seen: list[tuple[str, object]] = []
    field.text_changed.connect(lambda text: seen.append(("changed", text)))
    field.text_edited.connect(lambda text: seen.append(("edited", text)))
    field.editing_finished.connect(lambda: seen.append(("finished", "")))
    if case.reports_value:
        field.value_changed.connect(lambda value: seen.append(("value", value)))

    async with driver.open(view):
        async with driver.by_code():
            case.set_by_code(view)
        await driver.type(field, case.typed)

        edits = driver.edits(case.typed)  # never the text code set, nor one twice
        values = [("value", case.expected)] if case.reports_value else []  # once a date
        # each also as a change, in either order: Qt's line edit reports the edit first
        assert sorted(seen, key=repr) == sorted(
            [
                *(("edited", text) for text in edits),
                *(("changed", text) for text in edits),
                *values,
            ],
            key=repr,
        )
        assert (driver.shown_text(field), case.read(view)) == (case.typed, case.expected)

        typed = len(seen)
        await driver.leave(field)
        assert seen[typed:] == [("finished", "")]

        # a change by code after the user's: shown, and not reported
        reported = len(seen)
        async with driver.by_code():
            case.set_again(view)
        assert (driver.shown_text(field), seen[reported:]) == (case.shown_again, [])


@define_view
class _RangeMainView(MainView):
    # bounded: a date typed before the first day stays shown until the app replaces it
    days: DateRangeInputView = Factory(
        lambda: DateRangeInputView(minimum=FIRST_DAY, maximum=LAST_DAY, value=(FIRST_DAY, None))
    )


@pytest.mark.asyncio
async def test_a_date_range_reports_the_user_s_dates_not_the_code_s(driver: Driver) -> None:
    view = _RangeMainView()
    days = view.days
    changes: list[tuple[datetime.date | None, datetime.date | None]] = []
    days.value_changed.connect(changes.append)
    august = datetime.date(2014, 8, 31)

    async with driver.open(view):
        await driver.type(days, "08/31/2014", part=1)  # before the start: the start follows

        assert (days.value, changes) == ((august, august), [(august, august)])
        assert [driver.shown_text(days, part=part) for part in (0, 1)] == ["08/31/2014"] * 2

        async with driver.by_code():  # out of bounds replaced: an end emptied, the other set
            days.value = (None, FIRST_DAY)
        assert [driver.shown_text(days, part=part) for part in (0, 1)] == ["", "09/01/2014"]

        async with driver.by_code():  # the end alone of a range already open
            days.value = (None, datetime.date(2014, 9, 9))
            days.maximum = datetime.date(2014, 9, 15)
        assert [driver.shown_text(days, part=part) for part in (0, 1)] == ["", "09/09/2014"]
        assert changes == [(august, august)]
